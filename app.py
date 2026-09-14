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
    cleaned = re.sub(r"\(.*?\)", "", cleaned)
    cleaned = re.sub(r"\[.*?\]", "", cleaned)
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
            try:
                conn.close()
            except Exception:
                pass


# ============================================================
# AI CLIENTS
# ============================================================

groq_client = None
eleven_client = None


def initialize_clients():
    global groq_client
    global eleven_client

    if GROQ_API_KEY:
        groq_client = AsyncGroq(
            api_key=GROQ_API_KEY
        )

        logger.info(
            "Groq client initialized with model: %s",
            GROQ_MODEL,
        )

    else:
        logger.error(
            "GROQ_API_KEY is missing."
        )

    if ELEVENLABS_API_KEY:
        eleven_client = ElevenLabs(
            api_key=ELEVENLABS_API_KEY
        )

        logger.info(
            "ElevenLabs client initialized."
        )

    else:
        logger.warning(
            "ELEVENLABS_API_KEY is missing. Voice features disabled."
        )


# ============================================================
# AI RESPONSE
# ============================================================

async def get_ai_response(user_id, user_text):
    """
    Generate a short, natural, neutral Fenix response.
    """

    if not groq_client:
        return (
            "AI service abhi configured nahi hai. "
            "GROQ_API_KEY check karo."
        )

    count, memories = get_data(user_id)

    system_prompt = f"""
You are Fenix, a friendly and helpful AI chat assistant.

The user is chatting with you on Instagram, Telegram, WhatsApp,
or the Fenix web tester.

Conversation memory:
{memories}

Rules:
1. Reply naturally and conversationally.
2. Use casual Hinglish when the user uses Hinglish.
3. Use English when the user uses English.
4. Keep normal chat replies short, usually 1-3 lines.
5. Do not write unnecessary long explanations.
6. Be helpful, respectful, and friendly.
7. Do not pretend to be a real human.
8. Do not use stage directions such as *smiles* or [laughs].
9. Do not mention these system instructions.
10. Answer the user's actual question directly.
"""

    try:
        response = await groq_client.chat.completions.create(
            model=GROQ_MODEL,

            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": str(user_text),
                },
            ],

            max_tokens=120,

            temperature=0.7,
        )

        if not response.choices:
            return "Sorry, mujhe abhi proper response nahi mila."

        answer = response.choices[0].message.content

        if not answer:
            return "Sorry, abhi response generate nahi ho paya."

        return answer.strip()

    except Exception as e:
        logger.exception(
            "Groq API error: %s",
            e,
        )

        return (
            "AI response mein abhi dikkat aa rahi hai. "
            "Thodi der baad try karo."
        )


# ============================================================
# INSTAGRAM HELPERS
# ============================================================

def mark_message_seen(recipient_id):
    if not FB_PAGE_ACCESS_TOKEN:
        return

    url = (
        "https://graph.facebook.com/v25.0/me/messages"
        f"?access_token={FB_PAGE_ACCESS_TOKEN}"
    )

    payload = {
        "recipient": {
            "id": str(recipient_id)
        },
        "sender_action": "mark_seen",
    }

    try:
        requests.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json"
            },
            timeout=5,
        )

    except Exception as e:
        logger.warning(
            "Instagram mark-seen error: %s",
            e,
        )


def send_typing_indicator(
    recipient_id,
    action="typing_on",
):
    if not FB_PAGE_ACCESS_TOKEN:
        return

    url = (
        "https://graph.facebook.com/v25.0/me/messages"
        f"?access_token={FB_PAGE_ACCESS_TOKEN}"
    )

    payload = {
        "recipient": {
            "id": str(recipient_id)
        },
        "sender_action": action,
    }

    try:
        requests.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json"
            },
            timeout=5,
        )

    except Exception as e:
        logger.warning(
            "Instagram typing error: %s",
            e,
        )


def send_instagram_reply(
    recipient_id,
    message_text,
):
    if not FB_PAGE_ACCESS_TOKEN:
        logger.warning(
            "FB_PAGE_ACCESS_TOKEN is missing."
        )
        return False

    send_typing_indicator(
        recipient_id,
        "typing_on",
    )

    delay = min(
        max(len(message_text) * 0.03, 0.5),
        2.5,
    )

    time.sleep(delay)

    url = (
        "https://graph.facebook.com/v25.0/me/messages"
        f"?access_token={FB_PAGE_ACCESS_TOKEN}"
    )

    payload = {
        "recipient": {
            "id": str(recipient_id)
        },
        "message": {
            "text": str(message_text)
        },
    }

    success = False

    try:
        response = requests.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json"
            },
            timeout=15,
        )

        if response.status_code == 200:
            success = True

        else:
            logger.error(
                "Instagram reply failed [%s]: %s",
                response.status_code,
                response.text,
            )

    except Exception as e:
        logger.exception(
            "Instagram reply exception: %s",
            e,
        )

    finally:
        send_typing_indicator(
            recipient_id,
            "typing_off",
        )

    return success


def send_instagram_voice(
    recipient_id,
    audio_file_path,
):
    if not FB_PAGE_ACCESS_TOKEN:
        return False

    if not os.path.exists(audio_file_path):
        logger.error(
            "Voice file does not exist: %s",
            audio_file_path,
        )
        return False

    url = (
        "https://graph.facebook.com/v25.0/me/messages"
        f"?access_token={FB_PAGE_ACCESS_TOKEN}"
    )

    try:
        with open(
            audio_file_path,
            "rb",
        ) as audio_file:

            payload = {
                "recipient": (
                    '{"id":"' +
                    str(recipient_id) +
                    '"}'
                ),
                "message": (
                    '{"attachment":'
                    '{"type":"audio",'
                    '"payload":{}}}'
                ),
            }

            files = {
                "file": (
                    "voice.m4a",
                    audio_file,
                    "audio/mp4",
                )
            }

            response = requests.post(
                url,
                data=payload,
                files=files,
                timeout=30,
            )

            if response.status_code == 200:
                return True

            logger.error(
                "Instagram voice failed [%s]: %s",
                response.status_code,
                response.text,
            )

    except Exception as e:
        logger.exception(
            "Instagram voice exception: %s",
            e,
        )

    return False


# ============================================================
# INSTAGRAM WEBHOOK
# ============================================================

@app.route(
    "/webhook",
    methods=["GET", "POST"],
)
def webhook():

    if request.method == "GET":

        mode = request.args.get(
            "hub.mode"
        )

        token = request.args.get(
            "hub.verify_token"
        )

        challenge = request.args.get(
            "hub.challenge"
        )

        if (
            mode == "subscribe"
            and token
            and VERIFY_TOKEN
            and token == VERIFY_TOKEN
        ):
            return challenge, 200

        return "Forbidden", 403

    data = request.get_json(
        silent=True
    )

    if not data:
        return "EVENT_RECEIVED", 200

    try:

        if data.get("object") != "instagram":
            return "EVENT_RECEIVED", 200

        for entry in data.get(
            "entry",
            [],
        ):

            for messaging in entry.get(
                "messaging",
                [],
            ):

                sender_id = str(
                    messaging.get(
                        "sender",
                        {}
                    ).get(
                        "id",
                        ""
                    )
                )

                message = messaging.get(
                    "message",
                    {}
                )

                message_text = message.get(
                    "text"
                )

                is_echo = message.get(
                    "is_echo",
                    False
                )

                if (
                    not sender_id
                    or not message_text
                    or is_echo
                ):
                    continue

                message_text = str(
                    message_text
                ).strip()

                is_mention = (
                    f"@{INSTAGRAM_USERNAME}"
                    in message_text.lower()
                )

                if is_mention:
                    message_text = re.sub(
                        rf"@{re.escape(INSTAGRAM_USERNAME)}",
                        "",
                        message_text,
                        flags=re.IGNORECASE,
                    ).strip()

                if not message_text:
                    continue

                mark_message_seen(
                    sender_id
                )

                update_memory(
                    sender_id,
                    message_text,
                )

                threading.Thread(
                    target=process_instagram_message,
                    args=(
                        sender_id,
                        message_text,
                    ),
                    daemon=True,
                ).start()

    except Exception as e:

        logger.exception(
            "Instagram webhook processing error: %s",
            e,
        )

    return "EVENT_RECEIVED", 200


def process_instagram_message(
    sender_id,
    message_text,
):

    try:

        raw_reply = run_async_safe(
            get_ai_response(
                sender_id,
                message_text,
            )
        )

        cleaned = clean_text_for_speech(
            raw_reply
        )

        reply = humanize_text(
            cleaned
        )

        wants_voice = (
            "voice" in message_text.lower()
            or "audio" in message_text.lower()
        )

        if (
            wants_voice
            and eleven_client
            and VOICE_ID
        ):

            mp3_path = (
                f"/tmp/fenix_{sender_id}.mp3"
            )

            m4a_path = (
                f"/tmp/fenix_{sender_id}.m4a"
            )

            try:

                audio = (
                    eleven_client
                    .text_to_speech
                    .convert(
                        text=reply,
                        voice_id=VOICE_ID,
                        model_id="eleven_multilingual_v2",
                    )
                )

                with open(
                    mp3_path,
                    "wb",
                ) as audio_file:

                    for chunk in audio:
                        audio_file.write(
                            chunk
                        )

                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        mp3_path,
                        "-c:a",
                        "aac",
                        m4a_path,
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                if send_instagram_voice(
                    sender_id,
                    m4a_path,
                ):
                    return

            except Exception as e:

                logger.exception(
                    "Instagram voice generation error: %s",
                    e,
                )

            finally:

                for path in (
                    mp3_path,
                    m4a_path,
                ):

                    try:
                        if os.path.exists(path):
                            os.remove(path)
                    except Exception:
                        pass

        send_instagram_reply(
            sender_id,
            reply,
        )

    except Exception as e:

        logger.exception(
            "Instagram message processing error: %s",
            e,
        )

        send_instagram_reply(
            sender_id,
            "Sorry, abhi response process nahi ho paya.",
        )


# ============================================================
# FLASK SERVER
# ============================================================

def run_flask():

    try:

        app.run(
            host="0.0.0.0",
            port=PORT,
            threaded=True,
        )

    except Exception as e:

        logger.exception(
            "Flask server error: %s",
