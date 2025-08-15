#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI-Powered Local Governance Assistant - Fully Integrated Backend
"""

import os
import uuid
import json
import traceback
import sqlite3
import random
import string
import base64
import io
from datetime import datetime
from typing import Optional, Dict

from flask import Flask, request, jsonify, send_from_directory, send_file, render_template
from flask_cors import CORS
from dotenv import load_dotenv

# -------- Optional: Google Gemini --------
GEMINI_AVAILABLE = True
try:
    import google.generativeai as genai
except ImportError:
    GEMINI_AVAILABLE = False

# -------- Voice packages --------
try:
    import speech_recognition as sr
except ImportError:
    sr = None
try:
    from gtts import gTTS
except ImportError:
    gTTS = None

# -------- Translation via OpenRouter --------
OpenRouterTranslate = None
try:
    # Corrected the import to handle the typo in the filename
    from OpenRouterTranslate import OpenRouterTranslate as ORT
    OpenRouterTranslate = ORT
except ImportError:
    try:
        from OpentRouterTanslate import OpenRouterTranslate as ORT
        OpenRouterTranslate = ORT
    except ImportError:
        OpenRouterTranslate = None

# -------------------- Flask App Setup --------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
TTS_DIR = os.path.join(BASE_DIR, "tts")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(TTS_DIR, exist_ok=True)

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-secret")
app.config["JSON_AS_ASCII"] = False
CORS(app, resources={r"/api/*": {"origins": "*"}})

# -------------------- DB Helpers --------------------
def get_db():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """
    Initializes tables that are NOT created by the setup scripts.
    The 'applications' and 'services' tables are created by their
    own dedicated scripts to avoid conflicts.
    """
    conn = get_db()
    cur = conn.cursor()
    # Chat history
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            user_message TEXT,
            bot_message TEXT,
            source_lang TEXT,
            target_lang TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Complaints / tickets
    cur.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            contact TEXT,
            issue TEXT,
            status TEXT DEFAULT 'open',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

# Initialize the necessary tables on startup
init_db()

# -------------------- Gemini Setup --------------------
gemini_model = None
def init_gemini():
    """Initializes the Google Gemini model if the API key is available."""
    global gemini_model
    if not GEMINI_AVAILABLE:
        print("[WARN] google-generativeai not installed.")
        return
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[WARN] GEMINI_API_KEY not found in .env file.")
        return
    try:
        genai.configure(api_key=api_key)
        gemini_model = genai.GenerativeModel("gemini-1.5-flash")
        print("[OK] Gemini initialized.")
    except Exception as e:
        print(f"[ERROR] Gemini init failed: {e}")

init_gemini()

# -------------------- Translator Setup --------------------
translator = None
if OpenRouterTranslate:
    try:
        translator = OpenRouterTranslate()
        print("[OK] OpenRouterTranslate initialized.")
    except Exception as e:
        print(f"[ERROR] OpenRouterTranslate init failed: {e}")

# -------------------- Utility Functions --------------------
def generate_ticket(length=8):
    """Generates a random, unique alphanumeric ticket number."""
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for i in range(length))

def ask_gemini(question):
    """Interacts with the Gemini model to get a response."""
    if not gemini_model:
        return "Chatbot is currently unavailable. Please try again later."
    try:
        response = gemini_model.generate_content(question)
        return response.text
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return "I'm having trouble connecting to my knowledge base right now. Please try again later."

# -------------------- Routes --------------------

@app.route("/")
def index():
    return render_template("index1.html")

@app.route("/apply")
def apply():
    return render_template("apply.html")

@app.route("/api/services")
def api_services():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT service_id, title, details FROM services")
        services = cursor.fetchall()
        return jsonify([dict(row) for row in services])
    except sqlite3.Error as e:
        print(f"Database error on services query: {e}")
        return jsonify({"ok": False, "error": "Could not retrieve services"}), 500
    finally:
        conn.close()

@app.route("/api/apply", methods=["POST"])
def api_apply():
    # Use request.form for form data and request.files for files
    name = request.form.get("name")
    email = request.form.get("email")
    phone = request.form.get("phone")
    purpose = request.form.get("purpose")
    service_id = request.form.get("service_id")
    uploaded_file = request.files.get('document')

    if not all([service_id, name, email, purpose]):
        return jsonify({"ok": False, "error": "Missing required fields"}), 400

    conn = get_db()
    cursor = conn.cursor()

    # Check if service_id is valid
    cursor.execute("SELECT 1 FROM services WHERE service_id = ?", (service_id,))
    if cursor.fetchone() is None:
        conn.close()
        return jsonify({"ok": False, "error": f"Service ID '{service_id}' is invalid."}), 404

    file_name = uploaded_file.filename if uploaded_file else None
    file_data = uploaded_file.read() if uploaded_file else None

    ticket_number = generate_ticket()

    try:
        cursor.execute("""
            INSERT INTO applications (service_id, name, email, phone, purpose, ticket_number, file_name, file_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (service_id, name, email, phone, purpose, ticket_number, file_name, file_data))
        conn.commit()
    except sqlite3.Error as e:
        conn.close()
        print(f"Database error on application insert: {e}")
        return jsonify({"ok": False, "error": "A database error occurred. Please try again."}), 500
    finally:
        conn.close()

    return jsonify({"ok": True, "message": "Application submitted successfully!", "ticket_number": ticket_number})


@app.route("/api/saved_files")
def api_saved_files():
    """Return saved uploads. If ?email= is provided, filter by user email."""
    email = request.args.get('email', '').strip()
    conn = get_db()
    cursor = conn.cursor()
    try:
        if email:
            cursor.execute("""
                SELECT id, service_id, name, email, ticket_number, file_name, file_data, submission_date
                FROM applications
                WHERE file_data IS NOT NULL AND email = ?
                ORDER BY submission_date DESC
                LIMIT 200
            """, (email,))
        else:
            cursor.execute("""
                SELECT id, service_id, name, email, ticket_number, file_name, file_data, submission_date
                FROM applications
                WHERE file_data IS NOT NULL
                ORDER BY submission_date DESC
                LIMIT 200
            """)
        rows = cursor.fetchall()
        results = []
        for row in rows:
            results.append({
                'id': row['id'],
                'service_id': row['service_id'],
                'name': row['name'],
                'email': row['email'],
                'ticket_number': row['ticket_number'],
                'file_name': row['file_name'],
                'submitted_at': row['submission_date']
            })
        return jsonify({'ok': True, 'files': results})
    except sqlite3.Error as e:
        print(f"Database error on saved files query: {e}")
        return jsonify({"ok": False, "error": "Could not retrieve saved files"}), 500
    finally:
        conn.close()

# ---- Chatbot endpoint ----
@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "message is required"}), 400

    bot_reply = ask_gemini(message)
    return jsonify({"ok": True, "bot_reply": bot_reply})

# (All other existing API endpoints for complaints, history, voice, etc. should remain unchanged)



# ---- Download a saved file by database id ----
@app.route('/api/download/<int:file_id>')
def download_file(file_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT file_name, file_data
            FROM applications
            WHERE id = ?
        """, (file_id,))
        row = cursor.fetchone()
        if not row or not row['file_data']:
            return jsonify({'ok': False, 'error': 'File not found'}), 404
        
        filename = row['file_name'] or f'file_{file_id}'
        data = row['file_data']
        return send_file(
            io.BytesIO(data),
            as_attachment=True,
            download_name=filename,
            mimetype='application/octet-stream'
        )
    except sqlite3.Error as e:
        print(f"Database error on download: {e}")
        return jsonify({'ok': False, 'error': 'Could not download file'}), 500
    finally:
        conn.close()
if __name__ == "__main__":
    host = os.environ.get("FLASK_RUN_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_RUN_PORT", "5000"))
    app.run(host=host, port=port, debug=True)