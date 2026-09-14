import os
import logging
import sqlite3
import asyncio
import requests
import threading
import subprocess
import re
import time
import random
import html
from urllib.parse import quote_plus

from flask import Flask, request, jsonify
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
)

from groq import AsyncGroq
from elevenlabs.client import ElevenLabs


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("Fenix")


# ============================================================
# CONFIG
# ============================================================

PORT = int(os.environ.get("PORT", "8080"))

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
VOICE_ID = os.environ.get("ELEVEN_LABS_VOICE_ID", "").strip()

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "").strip()
FB_PAGE_ACCESS_TOKEN = os.environ.get(
    "FB_PAGE_ACCESS_TOKEN", ""
).strip()

INSTAGRAM_USERNAME = os.environ.get(
    "INSTAGRAM_USERNAME",
    "really_innocent_.nawab",
).strip().lower()

RENDER_SERVER_URL = os.environ.get(
    "RENDER_SERVER_URL",
    "https://my-youtube-api-1uf5.onrender.com",
).strip()

# Requested Groq model
GROQ_MODEL = "openai/gpt-oss-20b"

# Local SQLite database
DATABASE_PATH = "/tmp/fenix.db"


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Fenix is Alive!"


@app.route("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "Fenix",
            "model": GROQ_MODEL,
        }
    )


# ============================================================
# SAFE ASYNC RUNNER
# ============================================================

def run_async_safe(coro):
    """
    Safely execute an async coroutine from synchronous code.
    """

    try:
        return asyncio.run(coro)

    except RuntimeError:
        loop = asyncio.new_event_loop()

        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)

        finally:
            try:
                loop.close()
            except Exception:
                pass


# ============================================================
# TEXT CLEANER
# ============================================================

def clean_text_for_speech(text):
    if not text:
        return ""

    cleaned = str(text)

    cleaned = re.sub(r"\*.*?\*", "", cleaned)
    cleaned = re.sub(r".*?", "", cleaned)
    cleaned = re.sub(r".*?", "", cleaned)
    cleaned = re.sub(r"\{.*?\}", "", cleaned)

    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned


def humanize_text(text):
    """
    Keep replies natural without changing the meaning.
    """

    if not text:
        return ""

    text = str(text).strip()

    if not text:
        return ""

    # Small natural variation.
    if random.random() > 0.80 and not text.endswith(("...", ".", "!", "?")):
        text += "..."

    return text


# ============================================================
# DATABASE / MEMORY ENGINE
# ============================================================

def get_db_connection():
    conn = sqlite3.connect(
        DATABASE_PATH,
        timeout=10,
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory (
            user_id TEXT PRIMARY KEY,
            count INTEGER NOT NULL DEFAULT 0,
            context TEXT NOT NULL DEFAULT ''
        )
        """
    )

    conn.commit()

    return conn


def init_db():
    try:
        conn = get_db_connection()
        conn.close()

        logger.info("SQLite memory database initialized successfully.")

    except Exception as e:
        logger.exception(
            "Database initialization failed: %s",
            e,
        )


def get_data(user_id):
    conn = None

    try:
        conn = get_db_connection()

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT count, context
            FROM memory
            WHERE user_id = ?
            """,
            (str(user_id),),
        )

        row = cursor.fetchone()

        if row:
            count = int(row[0] or 0)
            context = row[1] or ""

            return count, context

        return 0, ""

    except Exception as e:
        logger.exception(
            "Get memory error: %s",
            e,
        )

        return 0, ""

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def update_memory(user_id, text):
    conn = None

    try:
        count, context = get_data(user_id)

        new_count = count + 1

        new_context = (
            f"{context} {text}"
            .strip()
        )[-2000:]

        conn = get_db_connection()

        conn.execute(
            """
            INSERT INTO memory (
                user_id,
                count,
                context
            )
            VALUES (?, ?, ?)

            ON CONFLICT(user_id)
            DO UPDATE SET
                count = excluded.count,
                context = excluded.context
            """,
            (
                str(user_id),
                new_count,
                new_context,
            ),
        )

        conn.commit()

        return new_count

    except Exception as e:
        logger.exception(
            "Update memory error: %s",
            e,
        )

        return 0

    finally:
        if conn:
           
