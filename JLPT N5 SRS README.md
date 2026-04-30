# **🎌 JLPT N5 SRS: Web App & Contextual Mission Generator**

A highly optimized, strictly constrained Spaced Repetition System (SRS) designed for the disciplined memorization of JLPT N5 vocabulary. This isn't a passive flashcard app—it is a mission-oriented tool engineered for retention through technical precision, beautifully wrapped in a single-file full-stack web application.

## **🚀 The Philosophy: "No Magic. No Passive Consumption."**

Most language apps fail by overwhelming the user with "infinite" reviews. This system enforces **Strict Session Guardrails**:

* 🛑 **5 New Words Per Day:** A hard limit to prevent cognitive fatigue.  
* 🔒 **Daily Lockout:** Once your quota is met, the queue is locked until the next calendar date.  
* 🎯 **Contextual Missions:** Bridge the gap between rote memory and reality with localized tasks generated at the end of successful sessions.

## **🛠 Tech Stack & Architecture**

This project prioritizes a streamlined footprint, combining high-performance Python data pipelines with a clean frontend, all housed within a single file.

### **⚡ Performance Data Pipeline (Backend)**

* **Polars:** Utilized for out-of-core, vectorized data ingestion. We bypass the overhead of row-by-row iteration with O(1) columnar filtering to clean noisy CSV datasets.  
* **Pydantic V2:** Leverages pydantic-core (Rust) for rigorous schema validation and high-speed state serialization.  
* **Flask:** A lightweight WSGI web application framework serving the API and user interface.

### **🎨 Frontend Interface**

* **Tailwind CSS:** Utility-first CSS framework embedded via CDN for a modern, responsive, and polished interface without external stylesheets.  
* **Vanilla JS:** Handles seamless, asynchronous API calls to the Flask backend without requiring a heavy frontend build step (No Node/NPM required).

### **🛡 Zero-Trust Security Posture**

* **Atomic State Writes:** To prevent JSON corruption during hardware failure or SIGINT, the system utilizes a .tmp swap strategy for state persistence.  
* **Absolute Path Anchoring:** All file operations are strictly resolved via pathlib.Path(\_\_file\_\_) to eliminate Path Traversal vulnerabilities.

### **🧠 Algorithmic Core**

* **Modified SM-2:** A 4-point qualitative assessment (Blackout, Hard, Good, Perfect) dynamically adjusts the Ease Factor (EF).  
* **Failure Penalty:** Recall failures reset the interval but maintain a penalized EF to ensure difficult items reappear with appropriate frequency.

## **📦 Installation**

Because the application is entirely self-contained, installation is incredibly fast.

\# Clone the repository  
git clone \[https://github.com/Grimwald79/jlpt-n5-srs.git\](https://github.com/Grimwald79/jlpt-n5-srs.git)  
cd jlpt-n5-srs

\# Install the required backend dependencies  
pip install flask polars pydantic

## **🎮 Usage**

### **Start the Server**

Simply run the application file. It will automatically validate your CSV data and generate your persistent state on the first run.

python app.py

Once running, open your browser and navigate to: **http://127.0.0.1:5000**

### **Contextual Missions**

Upon completing your daily review, the system isolates a successfully recalled word and generates a localized mission on your dashboard summary.

**Example:** You recalled **ビール (Biiru)**.

**Mission:** *Find a way to naturally use or identify 'ビール' while managing the bar tonight. Alternatively, write it on a coaster.*

## **📊 Directory Structure**

The power of this architecture lies in its minimal footprint:

.    
├── data/    
│   └── srs\_state.json       \# Atomic-write persistence layer (Auto-generated)  
├── app.py                   \# The complete full-stack application  
├── JLPT\_N5\_Vocab.csv        \# Source data (Must be placed alongside app.py)  
└── README.md

## **⚖️ License**

Distributed under the MIT License. See LICENSE for more information.

**Engineered for strict environments. Designed for Japanese fluency.**