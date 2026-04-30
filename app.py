import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import polars as pl
from pydantic import BaseModel, Field, ValidationError
from flask import Flask, render_template_string, jsonify, request

# ---------------------------------------------------------
# CONSTANTS & PATH RESOLUTION
# ---------------------------------------------------------
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
STATE_FILE = DATA_DIR / "srs_state.json"
CSV_FILE = BASE_DIR / "JLPT_N5_Vocab.csv"


# ---------------------------------------------------------
# PYDANTIC V2 SCHEMA
# ---------------------------------------------------------
class SRSMetrics(BaseModel):
    repetition: int = 0
    interval: int = 0
    ease_factor: float = 2.5
    next_review: date = Field(default_factory=date.today)


class VocabItem(BaseModel):
    kanji: str
    furigana: str
    romaji: str
    meaning: str
    metrics: SRSMetrics = Field(default_factory=SRSMetrics)


class DeckState(BaseModel):
    last_study_date: Optional[date] = None
    new_words_studied_today: int = 0
    vocab_db: Dict[str, VocabItem] = Field(default_factory=dict)


# ---------------------------------------------------------
# CORE LOGIC & ALGORITHMS
# ---------------------------------------------------------
class SM2Engine:
    @staticmethod
    def calculate_next_interval(metrics: SRSMetrics, quality: int) -> SRSMetrics:
        q_map = {1: 0, 2: 2, 3: 4, 4: 5}
        sm2_q = q_map.get(quality, 0)

        if sm2_q < 3:
            metrics.repetition = 0
            metrics.interval = 1
        else:
            if metrics.repetition == 0:
                metrics.interval = 1
            elif metrics.repetition == 1:
                metrics.interval = 6
            else:
                metrics.interval = round(metrics.interval * metrics.ease_factor)
            metrics.repetition += 1

        metrics.ease_factor = metrics.ease_factor + (
            0.1 - (5 - sm2_q) * (0.08 + (5 - sm2_q) * 0.02)
        )
        if metrics.ease_factor < 1.3:
            metrics.ease_factor = 1.3

        metrics.next_review = date.today() + timedelta(days=metrics.interval)
        return metrics


class ContextualMissionGenerator:
    ENVIRONMENTS = ["Customer Interaction (Bar)", "Commute Observation", "Daily Life"]

    @classmethod
    def generate(cls, word: VocabItem) -> dict:
        env = random.choice(cls.ENVIRONMENTS)

        if "Bar" in env:
            mission = f"Find a way to naturally use or identify '{word.kanji}' while managing the bar tonight. Alternatively, write it on a coaster."
        elif "Commute" in env:
            mission = f"Look for '{word.kanji}' on train station signage or listen for it in announcements during your commute."
        else:
            mission = f"Associate '{word.kanji}' with an object or action in your apartment today. Speak it aloud when you see it."

        return {
            "kanji": word.kanji,
            "furigana": word.furigana,
            "meaning": word.meaning,
            "environment": env,
            "mission": mission,
        }


class JLPTAppManager:
    def __init__(self):
        self.state: DeckState = self._load_state()
        self.session_queue: List[str] = []
        self.successful_reviews: List[VocabItem] = []
        self.is_ready = CSV_FILE.exists() or STATE_FILE.exists()

    def _load_csv_with_polars(self) -> Dict[str, VocabItem]:
        if not CSV_FILE.exists():
            return {}

        df = pl.read_csv(CSV_FILE, has_header=False, skip_rows=1)
        df.columns = ["Kanji", "Furigana", "Romaji", "Meaning"]
        clean_df = df.filter(
            (pl.col("Meaning").is_not_null()) & (pl.col("Meaning") != "Meaning")
        )

        vocab_dict = {}
        for row in clean_df.iter_rows(named=True):
            k = row["Kanji"] if row["Kanji"] else row["Furigana"]
            key = f"{row['Romaji']}_{row['Meaning']}"
            vocab_dict[key] = VocabItem(
                kanji=k,
                furigana=row["Furigana"],
                romaji=row["Romaji"],
                meaning=row["Meaning"],
            )
        return vocab_dict

    def _load_state(self) -> DeckState:
        DATA_DIR.mkdir(exist_ok=True)
        if not STATE_FILE.exists():
            vocab = self._load_csv_with_polars()
            return DeckState(vocab_db=vocab)

        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return DeckState.model_validate(data)
        except Exception:
            return DeckState()

    def _save_state(self) -> None:
        temp_file = STATE_FILE.with_suffix(".json.tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(self.state.model_dump_json(indent=2))
            temp_file.replace(STATE_FILE)
        except Exception:
            if temp_file.exists():
                temp_file.unlink()

    def check_daily_reset(self):
        today = date.today()
        if self.state.last_study_date != today:
            self.state.last_study_date = today
            self.state.new_words_studied_today = 0
            self._save_state()

    def get_status(self) -> dict:
        self.check_daily_reset()
        today = date.today()
        due_count = sum(
            1
            for item in self.state.vocab_db.values()
            if item.metrics.next_review <= today
            and (item.metrics.repetition > 0 or item.metrics.interval > 0)
        )
        new_count = sum(
            1
            for item in self.state.vocab_db.values()
            if item.metrics.repetition == 0 and item.metrics.interval == 0
        )

        allowance = max(0, 5 - self.state.new_words_studied_today)
        return {
            "due_reviews": due_count,
            "new_words_available": min(new_count, allowance),
            "total_new_allowance": allowance,
        }

    def start_session(self):
        self.check_daily_reset()
        today = date.today()
        due_reviews = []
        new_words = []

        for key, item in self.state.vocab_db.items():
            if item.metrics.repetition == 0 and item.metrics.interval == 0:
                new_words.append(key)
            elif item.metrics.next_review <= today:
                due_reviews.append(key)

        allowance = max(0, 5 - self.state.new_words_studied_today)
        session_new_words = new_words[:allowance]

        self.session_queue = due_reviews + session_new_words
        random.shuffle(self.session_queue)
        self.successful_reviews = []

    def get_next_card(self) -> Optional[dict]:
        if not self.session_queue:
            return None

        key = self.session_queue[0]
        word = self.state.vocab_db[key]
        return {
            "key": key,
            "meaning": word.meaning,
            "kanji": word.kanji,
            "furigana": word.furigana,
            "romaji": word.romaji,
            "is_new": word.metrics.interval == 0,
            "remaining": len(self.session_queue),
        }

    def grade_card(self, key: str, grade: int):
        if not self.session_queue or self.session_queue[0] != key:
            return False

        word = self.state.vocab_db[key]
        is_new = word.metrics.interval == 0

        if is_new:
            self.state.new_words_studied_today += 1

        word.metrics = SM2Engine.calculate_next_interval(word.metrics, grade)
        if grade >= 3:
            self.successful_reviews.append(word)

        self._save_state()
        self.session_queue.pop(0)  # Remove from queue
        return True


# ---------------------------------------------------------
# FLASK APPLICATION & HTML TEMPLATE
# ---------------------------------------------------------
app = Flask(__name__)
manager = JLPTAppManager()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JLPT N5 SRS Deck</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; }
        .hide { display: none !important; }
        .glass-panel { background: rgba(255, 255, 255, 0.95); backdrop-filter: blur(10px); }
    </style>
</head>
<body class="bg-slate-50 min-h-screen text-slate-800 flex items-center justify-center p-4">

    <div id="main-container" class="glass-panel w-full max-w-lg rounded-3xl shadow-xl overflow-hidden border border-slate-200">

        <!-- Header -->
        <div class="bg-indigo-600 p-6 text-white text-center">
            <h1 class="text-2xl font-bold tracking-tight">JLPT N5 Review</h1>
            <p id="remaining-counter" class="text-indigo-200 text-sm mt-1 hide">Remaining: <span>0</span></p>
        </div>

        <div class="p-8">
            <!-- 1. Dashboard View -->
            <div id="view-dashboard" class="text-center space-y-6">
                <div id="status-loading" class="animate-pulse text-slate-400">Loading data...</div>
                <div id="status-content" class="hide space-y-4">
                    <div class="grid grid-cols-2 gap-4">
                        <div class="bg-slate-100 rounded-2xl p-4 border border-slate-200">
                            <p class="text-3xl font-bold text-slate-700" id="stat-due">0</p>
                            <p class="text-sm font-medium text-slate-500 uppercase tracking-wide mt-1">Reviews Due</p>
                        </div>
                        <div class="bg-slate-100 rounded-2xl p-4 border border-slate-200">
                            <p class="text-3xl font-bold text-slate-700" id="stat-new">0</p>
                            <p class="text-sm font-medium text-slate-500 uppercase tracking-wide mt-1">New Words</p>
                        </div>
                    </div>
                    <button id="btn-start" onclick="startSession()" class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-semibold py-4 rounded-xl transition-colors shadow-sm text-lg mt-4 disabled:opacity-50">
                        Start Session
                    </button>
                    <p id="all-done-msg" class="text-emerald-600 font-medium hide">Daily requirement met. Go manage the bar!</p>
                </div>
            </div>

            <!-- 2. Card View -->
            <div id="view-card" class="hide flex flex-col items-center">
                <div id="badge-new" class="hide bg-amber-100 text-amber-700 text-xs font-bold px-3 py-1 rounded-full uppercase tracking-widest mb-4 border border-amber-200">New Word</div>

                <p class="text-slate-500 font-medium text-sm mb-1 uppercase tracking-wider">Meaning</p>
                <h2 id="card-meaning" class="text-3xl font-bold text-slate-800 text-center mb-8"></h2>

                <!-- Reveal Button -->
                <button id="btn-reveal" onclick="revealAnswer()" class="w-full bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium py-4 rounded-xl transition-colors border border-slate-300">
                    Show Answer
                </button>

                <!-- Answer Area -->
                <div id="answer-area" class="w-full hide flex flex-col items-center space-y-6">
                    <div class="text-center w-full bg-slate-50 p-6 rounded-2xl border border-slate-200">
                        <h3 id="card-kanji" class="text-5xl font-bold text-indigo-600 mb-4"></h3>
                        <div class="flex justify-center space-x-4 text-slate-600">
                            <div><span class="text-xs uppercase tracking-wider text-slate-400 block">Furigana</span><span id="card-furigana" class="font-medium text-lg"></span></div>
                            <div class="w-px bg-slate-300"></div>
                            <div><span class="text-xs uppercase tracking-wider text-slate-400 block">Romaji</span><span id="card-romaji" class="font-medium text-lg"></span></div>
                        </div>
                    </div>

                    <div class="w-full space-y-2">
                        <p class="text-center text-sm font-medium text-slate-500 mb-3">Grade your recall</p>
                        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
                            <button onclick="submitGrade(1)" class="py-3 px-2 rounded-lg font-semibold text-sm bg-red-50 text-red-700 hover:bg-red-100 border border-red-200 transition">1: Blackout</button>
                            <button onclick="submitGrade(2)" class="py-3 px-2 rounded-lg font-semibold text-sm bg-orange-50 text-orange-700 hover:bg-orange-100 border border-orange-200 transition">2: Hard</button>
                            <button onclick="submitGrade(3)" class="py-3 px-2 rounded-lg font-semibold text-sm bg-emerald-50 text-emerald-700 hover:bg-emerald-100 border border-emerald-200 transition">3: Good</button>
                            <button onclick="submitGrade(4)" class="py-3 px-2 rounded-lg font-semibold text-sm bg-blue-50 text-blue-700 hover:bg-blue-100 border border-blue-200 transition">4: Perfect</button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 3. Summary View -->
            <div id="view-summary" class="hide text-center space-y-6">
                <div class="w-16 h-16 bg-emerald-100 text-emerald-600 rounded-full flex items-center justify-center mx-auto mb-4">
                    <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                </div>
                <h2 class="text-2xl font-bold text-slate-800">Session Complete!</h2>

                <div id="mission-area" class="text-left bg-amber-50 p-6 rounded-2xl border border-amber-200 mt-6 hide">
                    <h3 class="font-bold text-amber-800 flex items-center gap-2 mb-3">
                        <span>🎯</span> Daily Contextual Mission
                    </h3>
                    <p class="text-sm text-amber-900 mb-1"><strong class="font-semibold text-amber-800">Word:</strong> <span id="mission-word"></span></p>
                    <p class="text-sm text-amber-900 mb-3"><strong class="font-semibold text-amber-800">Environment:</strong> <span id="mission-env"></span></p>
                    <div class="bg-amber-100/50 p-4 rounded-xl text-amber-900 text-sm italic border border-amber-200/50" id="mission-text"></div>
                </div>

                <button onclick="location.reload()" class="w-full bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium py-3 rounded-xl transition-colors mt-6">
                    Return to Dashboard
                </button>
            </div>

            <!-- Error Banner -->
            <div id="error-banner" class="hide mt-4 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl text-sm text-center font-medium"></div>

        </div>
    </div>

    <script>
        let currentCardKey = null;

        // UI Helpers
        const show = (id) => document.getElementById(id).classList.remove('hide');
        const hide = (id) => document.getElementById(id).classList.add('hide');
        const setText = (id, text) => document.getElementById(id).innerText = text;
        const showError = (msg) => { setText('error-banner', msg); show('error-banner'); };

        async function init() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                if (data.error) {
                    showError(data.error);
                    hide('status-loading');
                    return;
                }

                setText('stat-due', data.due_reviews);
                setText('stat-new', data.new_words_available);
                hide('status-loading');
                show('status-content');

                if (data.due_reviews === 0 && data.new_words_available === 0) {
                    document.getElementById('btn-start').disabled = true;
                    show('all-done-msg');
                }
            } catch (err) {
                showError("Could not connect to the backend.");
            }
        }

        async function startSession() {
            await fetch('/api/start', { method: 'POST' });
            hide('view-dashboard');
            show('view-card');
            show('remaining-counter');
            loadNextCard();
        }

        async function loadNextCard() {
            hide('answer-area');
            show('btn-reveal');
            hide('badge-new');

            const res = await fetch('/api/card');
            const card = await res.json();

            if (card.status === 'complete') {
                showSummary();
                return;
            }

            currentCardKey = card.key;
            setText('card-meaning', card.meaning);
            setText('card-kanji', card.kanji);
            setText('card-furigana', card.furigana);
            setText('card-romaji', card.romaji);
            document.querySelector('#remaining-counter span').innerText = card.remaining;

            if (card.is_new) show('badge-new');
        }

        function revealAnswer() {
            hide('btn-reveal');
            show('answer-area');
        }

        async function submitGrade(grade) {
            await fetch('/api/grade', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: currentCardKey, grade: grade })
            });
            loadNextCard();
        }

        async function showSummary() {
            hide('view-card');
            hide('remaining-counter');
            show('view-summary');

            const res = await fetch('/api/mission');
            const data = await res.json();

            if (data.has_mission) {
                setText('mission-word', `${data.kanji} (${data.furigana}) - ${data.meaning}`);
                setText('mission-env', data.environment);
                setText('mission-text', data.mission);
                show('mission-area');
            }
        }

        // Boot
        window.onload = init;
    </script>
</body>
</html>
"""

# --- Flask Routes ---


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/status")
def status():
    if not manager.is_ready:
        return jsonify(
            {
                "error": f"CSV file not found at {CSV_FILE}. Please ensure JLPT_N5_Vocab.csv is in the same directory as this script."
            }
        )
    return jsonify(manager.get_status())


@app.route("/api/start", methods=["POST"])
def start():
    manager.start_session()
    return jsonify({"status": "started"})


@app.route("/api/card")
def get_card():
    card = manager.get_next_card()
    if not card:
        return jsonify({"status": "complete"})
    return jsonify(card)


@app.route("/api/grade", methods=["POST"])
def grade_card():
    data = request.json
    success = manager.grade_card(data.get("key"), data.get("grade"))
    return jsonify({"success": success})


@app.route("/api/mission")
def get_mission():
    if not manager.successful_reviews:
        return jsonify({"has_mission": False})

    target_word = random.choice(manager.successful_reviews)
    mission_data = ContextualMissionGenerator.generate(target_word)
    mission_data["has_mission"] = True
    return jsonify(mission_data)


if __name__ == "__main__":
    # Warn in console just in case, similar to original CLI
    if not CSV_FILE.exists():
        print(f"Setup Error: Ensure {CSV_FILE.name} is placed in {BASE_DIR}")

    print("\n🚀 JLPT App running! Open http://127.0.0.1:5000 in your browser.\n")
    app.run(debug=True, port=5000)
