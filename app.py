#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI-Powered Local Governance Assistant - Flask Backend (Hackathon Ready)
---------------------------------------------------------------------
- Serves as the backend API for your HTML/CSS frontend (to be added later).
- Chatbot answers via Google Gemini.
- Multilingual translation via OpenRouter (Gemma-3) using your provided OpenRouterTranslate class.
- SQLite database for tickets, applications, and chat history.
- Voice: speech-to-text (SpeechRecognition) and text-to-speech (gTTS).
- Safe CORS enabled for easy local dev (front-end can be on any port).

Project structure suggestion:
.
├── app.py
├── OpentRouterTanslate.py        # your file (typo kept intentionally as per your paste)
├── .env
├── requirements.txt
├── templates/                     # (optional) put index.html here when you receive it
└── static/                        # your CSS/JS assets (optional)

Run locally:
    python app.py

Test endpoints quickly (after running app):
    curl -X POST http://127.0.0.1:5000/api/chat -H "Content-Type: application/json" \
         -d '{"message": "How to apply for birth certificate?", "target_language": "en"}'

IMPORTANT:
- Add these to your requirements.txt if missing:
    google-generativeai==0.7.2
    Flask-Cors==4.0.0
"""

import os
import uuid
import json
import traceback
import sqlite3
from datetime import datetime
from typing import Optional, Dict

from flask import Flask, request, jsonify, send_from_directory, send_file, render_template
from flask_cors import CORS
from dotenv import load_dotenv

# -------- Optional: Google Gemini (install google-generativeai) --------
GEMINI_AVAILABLE = True
try:
    import google.generativeai as genai
except Exception as e:
    GEMINI_AVAILABLE = False

# -------- Voice packages --------
try:
    import speech_recognition as sr  # For speech-to-text (WAV/AIFF/FLAC recommended)
except Exception:
    sr = None

try:
    from gtts import gTTS  # For text-to-speech
except Exception:
    gTTS = None

# -------- Translation via OpenRouter (your provided class) --------
# Your pasted filename has a typo: "OpentRouterTanslate.py". We try both names to avoid import errors.
OpenRouterTranslate = None
try:
    from OpentRouterTanslate import OpenRouterTranslate as ORT  # as pasted
    OpenRouterTranslate = ORT
except Exception:
    try:
        from OpenRouterTranslate import OpenRouterTranslate as ORT  # corrected name
        OpenRouterTranslate = ORT
    except Exception:
        OpenRouterTranslate = None  # graceful fallback; we'll still run in English-only mode

# -------------------- Flask App Setup --------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
TTS_DIR = os.path.join(BASE_DIR, "tts")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(TTS_DIR, exist_ok=True)

load_dotenv()  # Load .env (GEMINI_API_KEY, OPENROUTER_API_KEY, etc.)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-secret")
app.config["JSON_AS_ASCII"] = False  # allow unicode in JSON

# Enable CORS for local development
CORS(app, resources={r"/api/*": {"origins": "*"}})

# -------------------- DB Helpers --------------------
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    # Chat history
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            user_message TEXT,
            bot_message TEXT,
            source_lang TEXT,
            target_lang TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Complaints / tickets
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            contact TEXT,
            issue TEXT,
            status TEXT DEFAULT 'open',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Applications (birth, death, income, water bill, etc.)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            applicant_name TEXT,
            application_type TEXT,
            details TEXT,  -- JSON string with arbitrary fields
            status TEXT DEFAULT 'submitted',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

init_db()

# -------------------- Gemini Setup --------------------
gemini_model = None

def init_gemini():
    global gemini_model
    if not GEMINI_AVAILABLE:
        print("[WARN] google-generativeai not installed. Add `google-generativeai` to requirements.txt")
        return

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[WARN] GEMINI_API_KEY not found in environment. Put it in your .env file.")
        return

    try:
        genai.configure(api_key=api_key)
        # Choose a fast, capable model. You can switch to 'gemini-1.5-pro' if needed.
        gemini_model = genai.GenerativeModel("gemini-1.5-flash")
        print("[OK] Gemini initialized (gemini-1.5-flash).")
    except Exception as e:
        print(f"[ERROR] Gemini init failed: {e}")

init_gemini()

# -------------------- Translator Setup --------------------
translator = None
if OpenRouterTranslate is not None:
    try:
        translator = OpenRouterTranslate()
        print("[OK] OpenRouterTranslate initialized.")
    except Exception as e:
        print(f"[WARN] OpenRouterTranslate could not initialize: {e}")
else:
    print("[WARN] OpenRouterTranslate class not found. Translation endpoints will still work in mock/English-only mode.")

# -------------------- Utilities --------------------
LANG_CODE_VOICE_MAP: Dict[str, str] = {
    # Map ISO 639-1 (2-letter) to Google Speech Recognition locale codes
    "en": "en-IN",
    "hi": "hi-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "kn": "kn-IN",
    "bn": "bn-IN",
    "mr": "mr-IN",
    "gu": "gu-IN",
    "ml": "ml-IN",
    "pa": "pa-IN",
}

GTTs_LANGUAGE_CODES = {
    # gTTS expects 2-letter language codes (and supports many of these)
    "en": "en",
    "hi": "hi",
    "ta": "ta",
    "te": "te",
    "kn": "kn",
    "bn": "bn",
    "mr": "mr",
    "gu": "gu",
    "ml": "ml",
    "pa": "pa",
}

def generate_session_id() -> str:
    return uuid.uuid4().hex

def ask_gemini(prompt: str) -> str:
    """Send a prompt to Gemini and return the text response."""
    if gemini_model is None:
        return "Gemini is not configured. Please set GEMINI_API_KEY and install google-generativeai."
    try:
        resp = gemini_model.generate_content(prompt)
        # Some versions return a 'text' property; others need joining candidates.
        if hasattr(resp, "text") and resp.text:
            return resp.text.strip()
        elif hasattr(resp, "candidates") and resp.candidates:
            # Fallback: concatenate the first candidate's text parts
            parts = []
            for part in resp.candidates[0].content.parts:
                parts.append(getattr(part, "text", ""))
            return "\n".join([p for p in parts if p]).strip() or "[Empty response]"
        else:
            return "[No text returned by Gemini]"
    except Exception as e:
        return f"[Gemini error] {e}"

def translate_text(text: str, source_language: Optional[str], target_language: Optional[str]) -> str:
    """Translate text via OpenRouterTranslate if available; otherwise minimal mock."""
    if not target_language or (source_language and source_language.lower() == target_language.lower()):
        return text  # no translation needed

    if translator:
        try:
            return translator.translate(text, source_language or "auto", target_language)
        except Exception as e:
            return f"[Translation error] {e}\n{text}"
    else:
        # Fallback: pretend translation if translator unavailable
        return f"[{target_language} translation unavailable] {text}"

def detect_language(text: str) -> str:
    if translator:
        try:
            return translator.detect_language(text)
        except Exception:
            return "en"
    return "en"

def save_chat(session_id: str, user_message: str, bot_message: str, source_lang: str, target_lang: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_history (session_id, user_message, bot_message, source_lang, target_lang) VALUES (?, ?, ?, ?, ?)",
        (session_id, user_message, bot_message, source_lang, target_lang),
    )
    conn.commit()
    conn.close()

# -------------------- Routes --------------------

# Frontend placeholder (will render templates/index.html if present)
@app.route("/")
def home():
    try:
        return render_template("index1.html")
    except Exception:
        return (
            "<h2>AI-Powered Local Governance Assistant (Backend Running)</h2>"
            "<p>Frontend not added yet. Place your HTML files in <code>templates/</code> and static assets in <code>static/</code>.</p>"
        )

# ---- Chatbot endpoint ----
@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "message is required"}), 400

    session_id = data.get("session_id") or generate_session_id()
    # Language preferences
    source_language = (data.get("source_language") or "").strip().lower() or detect_language(message)
    target_language = (data.get("target_language") or source_language or "en").strip().lower()

    # 1) Translate to English for LLM if needed
    text_for_llm = message
    if source_language != "en":
        text_for_llm = translate_text(message, source_language, "en")

    # 2) Ask Gemini
    bot_reply_en = ask_gemini(text_for_llm)

    # 3) Translate back to target_language
    final_reply = bot_reply_en
    if target_language and target_language != "en":
        final_reply = translate_text(bot_reply_en, "en", target_language)

    # Save history
    try:
        save_chat(session_id, message, final_reply, source_language, target_language)
    except Exception as e:
        print(f"[WARN] Failed to save chat history: {e}")

    return jsonify({
        "ok": True,
        "session_id": session_id,
        "source_language": source_language,
        "target_language": target_language,
        "bot_reply": final_reply
    }), 200

# ---- Translate endpoint ----
@app.route("/api/translate", methods=["POST"])
def api_translate():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "text is required"}), 400

    source_language = (data.get("source_language") or "").strip().lower() or "en"
    target_language = (data.get("target_language") or "").strip().lower() or "en"

    translated = translate_text(text, source_language, target_language)
    return jsonify({"ok": True, "translated_text": translated, "source_language": source_language, "target_language": target_language})

# ---- Chat history ----
@app.route("/api/history", methods=["GET"])
def api_history():
    session_id = request.args.get("session_id", "").strip()
    if not session_id:
        return jsonify({"ok": False, "error": "session_id is required"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM chat_history WHERE session_id = ? ORDER BY id ASC", (session_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return jsonify({"ok": True, "session_id": session_id, "history": rows})

# ---- Complaints CRUD ----
@app.route("/api/complaints", methods=["POST"])
def create_complaint():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    contact = (data.get("contact") or "").strip()
    issue = (data.get("issue") or "").strip()

    if not issue:
        return jsonify({"ok": False, "error": "issue is required"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO complaints (name, contact, issue) VALUES (?, ?, ?)", (name, contact, issue))
    comp_id = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "id": comp_id, "status": "open"})

@app.route("/api/complaints", methods=["GET"])
def list_complaints():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM complaints ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"ok": True, "complaints": rows})

@app.route("/api/complaints/<int:comp_id>", methods=["GET"])
def get_complaint(comp_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM complaints WHERE id = ?", (comp_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "complaint": dict(row)})

@app.route("/api/complaints/<int:comp_id>", methods=["PATCH"])
def update_complaint(comp_id):
    data = request.get_json(silent=True) or {}
    status = (data.get("status") or "").strip()  # e.g., open, in_progress, resolved, closed
    if not status:
        return jsonify({"ok": False, "error": "status is required"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE complaints SET status = ? WHERE id = ?", (status, comp_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": comp_id, "status": status})

# ---- Applications CRUD (generic) ----
@app.route("/api/applications", methods=["POST"])
def create_application():
    data = request.get_json(silent=True) or {}
    applicant_name = (data.get("applicant_name") or "").strip()
    application_type = (data.get("application_type") or "").strip().lower()  # 'birth', 'death', 'income', 'water', etc.
    details = data.get("details") or {}

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO applications (applicant_name, application_type, details) VALUES (?, ?, ?)",
        (applicant_name, application_type, json.dumps(details, ensure_ascii=False)),
    )
    app_id = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "id": app_id, "status": "submitted"})

@app.route("/api/applications", methods=["GET"])
def list_applications():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM applications ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    # Parse details JSON
    for r in rows:
        try:
            r["details"] = json.loads(r.get("details") or "{}")
        except Exception:
            pass
    conn.close()
    return jsonify({"ok": True, "applications": rows})

@app.route("/api/applications/<int:app_id>", methods=["GET"])
def get_application(app_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({"ok": False, "error": "not found"}), 404
    row = dict(row)
    try:
        row["details"] = json.loads(row.get("details") or "{}")
    except Exception:
        pass
    return jsonify({"ok": True, "application": row})

@app.route("/api/applications/<int:app_id>", methods=["PATCH"])
def update_application(app_id):
    data = request.get_json(silent=True) or {}
    status = (data.get("status") or "").strip()  # e.g., submitted, in_review, approved, rejected
    if not status:
        return jsonify({"ok": False, "error": "status is required"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE applications SET status = ? WHERE id = ?", (status, app_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": app_id, "status": status})

# ---- Voice: Speech-to-Text ----
@app.route("/api/voice-to-text", methods=["POST"])
def voice_to_text():
    """
    Upload an audio file with form-data key 'audio'. Recommended formats: WAV/FLAC/AIFF.
    Optional form-data field 'language' can be one of: en, hi, ta, te, kn, bn, mr, gu, ml, pa.
    """
    if sr is None:
        return jsonify({"ok": False, "error": "SpeechRecognition not installed"}), 500

    if "audio" not in request.files:
        return jsonify({"ok": False, "error": "No audio file uploaded with key 'audio'"}), 400

    file = request.files["audio"]
    filename = file.filename or f"audio_{uuid.uuid4().hex}.wav"
    # Force .wav if no extension
    if "." not in filename:
        filename += ".wav"

    # Save file
    save_path = os.path.join(UPLOAD_DIR, filename)
    file.save(save_path)

    # Language handling
    lang = (request.form.get("language") or "en").lower()
    sr_lang_code = LANG_CODE_VOICE_MAP.get(lang, "en-IN")

    # Recognize speech
    recog = sr.Recognizer()
    try:
        with sr.AudioFile(save_path) as source:
            audio = recog.record(source)
        text = recog.recognize_google(audio, language=sr_lang_code)
        return jsonify({"ok": True, "text": text, "language": lang})
    except sr.UnknownValueError:
        return jsonify({"ok": False, "error": "Could not understand audio"}), 400
    except sr.RequestError as e:
        return jsonify({"ok": False, "error": f"Speech recognition API error: {e}"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": f"Processing error: {e}"}), 500

# ---- Voice: Text-to-Speech ----
@app.route("/api/text-to-speech", methods=["POST"])
def text_to_speech():
    """
    JSON body: { "text": "Hello", "language": "en" }
    Returns: URL to the generated MP3 file.
    """
    if gTTS is None:
        return jsonify({"ok": False, "error": "gTTS not installed"}), 500

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "text is required"}), 400

    lang = (data.get("language") or "en").lower()
    gtts_lang = GTTs_LANGUAGE_CODES.get(lang, "en")

    try:
        tts = gTTS(text=text, lang=gtts_lang)
        filename = f"tts_{uuid.uuid4().hex}.mp3"
        path = os.path.join(TTS_DIR, filename)
        tts.save(path)
        return jsonify({"ok": True, "audio_url": f"/tts/{filename}", "filename": filename})
    except Exception as e:
        return jsonify({"ok": False, "error": f"TTS error: {e}"}), 500

@app.route("/tts/<path:filename>", methods=["GET"])
def serve_tts(filename):
    return send_from_directory(TTS_DIR, filename, as_attachment=False)

# -------------------- Error Handler --------------------
@app.errorhandler(500)
def server_error(e):
    return jsonify({"ok": False, "error": "Internal server error", "detail": str(e)}), 500

# -------------------- Main --------------------
if __name__ == "__main__":
    # Helpful startup logs
    print("=== Backend starting ===")
    print(f"DB Path: {DB_PATH}")
    print(f"Uploads: {UPLOAD_DIR}")
    print(f"TTS Dir: {TTS_DIR}")
    print(f"GEMINI available: {GEMINI_AVAILABLE}")
    print(f"Translator available: {translator is not None}")
    app.run(host="0.0.0.0", port=5000, debug=True)
