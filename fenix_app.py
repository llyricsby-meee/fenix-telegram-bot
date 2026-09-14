import os
import logging
import asyncio
import requests
import threading
import subprocess
import re
import time
import random
import uuid

from flask import Flask, request, jsonify
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
)
from groq import AsyncGroq
from elevenlabs.client import ElevenLabs
import libsql_client


# ============================================================
# CONFIG / ENVIRONMENT
# ============================================================

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

app = Flask(__name__)

TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL", "").strip()
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "").strip()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
VOICE_ID = os.environ.get("ELEVEN_LABS_VOICE_ID", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "").strip()
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN", "").strip()
INSTAGRAM_USERNAME = os.environ.get(
    "INSTAGRAM_USERNAME",
    "really_innocent_.nawab",
).strip()

PORT = int(os.environ.get("PORT", "8080"))
RENDER_SERVER_URL = "https://my-youtube-api-1uf5.onrender.com"


# ============================================================
# CLIENTS
# ============================================================

groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY) if ELEVENLABS_API_KEY else None


# ============================================================
# SAFE ASYNC RUNNER
# ============================================================

def run_async_safe(coro):
    """
    Run a coroutine safely from normal Flask/thread code.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()

    if loop is None:
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()

    try:
        return loop.run_until_complete(coro)
    except RuntimeError:
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()


# ============================================================
# TURSO DATABASE
# ============================================================

def get_turso_client():
    url = TURSO_DATABASE_URL

    if not url:
        raise RuntimeError("TURSO_DATABASE_URL is not configured")

    # Use HTTP/HTTPS transport to avoid WebSocket/Hrana issues.
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    elif url.startswith("wss://"):
        url = "https://" + url[len("wss://"):]
    elif url.startswith("ws://"):
        url = "http://" + url[len("ws://"):]

    return libsql_client.create_client(
        url=url,
        auth_token=TURSO_AUTH_TOKEN,
    )


async def ensure_memory_table(client):
    await client.execute(
        """
        CREATE TABLE IF NOT EXISTS memory (
            user_id TEXT PRIMARY KEY,
            count INTEGER NOT NULL DEFAULT 0,
            context TEXT NOT NULL DEFAULT ''
        )
        """
    )


async def init_db_async():
    client = None

    try:
        if not TURSO_DATABASE_URL:
            logging.warning(
                "TURSO_DATABASE_URL is not configured. "
                "Memory will be disabled."
            )
            return

        client = get_turso_client()
        await ensure_memory_table(client)
        logging.info("Turso memory database initialized successfully.")

    except Exception as e:
        logging.exception("Turso init error: %s", e)

    finally:
        if client:
            try:
                await client.close()
            except Exception:
                pass


def init_db():
    try:
        run_async_safe(init_db_async())
    except Exception as e:
        logging.exception("Init DB error: %s", e)


async def get_data_async(user_id):
    client = None

    try:
        if not TURSO_DATABASE_URL:
            return 0, ""

        client = get_turso_client()
        await ensure_memory_table(client)

        result = await client.execute(
            "SELECT count, context FROM memory WHERE user_id = ?",
            [str(user_id)],
        )

        if result.rows:
            count = int(result.rows[0][0] or 0)
            context = result.rows[0][1] or ""
            return count, context

        return 0, ""

    except Exception as e:
        logging.exception("Get data error: %s", e)
        return 0, ""

    finally:
        if client:
            try:
                await client.close()
            except Exception:
                pass


def get_data(user_id):
    try:
        return run_async_safe(get_data_async(user_id))
    except Exception as e:
        logging.exception("Get data sync error: %s", e)
        return 0, ""


async def update_memory_async(user_id, text):
    client = None

    try:
        if not TURSO_DATABASE_URL:
            return 0

        count, context = await get_data_async(user_id)

        new_count = count + 1
        new_context = f"{context} {text}"[-2000:].strip()

        client = get_turso_client()
        await ensure_memory_table(client)

        await client.execute(
            """
            INSERT INTO memory (user_id, count, context)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                count = excluded.count,
                context = excluded.context
            """,
            [str(user_id), new_count, new_context],
        )

        return new_count

    except Exception as e:
        logging.exception("Update memory error: %s", e)
        return 0

    finally:
        if client:
            try:
                await client.close()
            except Exception:
                pass


def update_memory(user_id, text):
    try:
        return run_async_safe(update_memory_async(user_id, text))
    except Exception as e:
        logging.exception("Update memory sync error: %s", e)
        return 0


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_text_for_speech(text):
    if not text:
        return ""

    cleaned = re.sub(r"\*.*?\*", "", text)
    cleaned = re.sub(r"\(.*?\)", "", cleaned)
    cleaned = re.sub(r"\[.*?\]", "", cleaned)
    cleaned = re.sub(r"\{.*?\}", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned


def humanize_text(text):
    if not text:
        return text

    # Keep the assistant neutral and natural.
    if random.random() > 0.65 and not text.endswith(("...", ".", "!", "?")):
        text += "..."

    return text


# ============================================================
# AI RESPONSE
# ============================================================

async def get_ai_response(user_id, user_text):
    if not groq_client:
        return "Groq API key configured nahi hai."

    try:
        count, memories = await get_data_async(user_id)

        if count < 50:
            mode = "friendly and helpful chat assistant"
        elif count < 150:
            mode = "warm, natural and conversational chat assistant"
        else:
            mode = "playful, natural and conversational chat assistant"

        system_prompt = (
            f"You are Fenix, a friendly neutral chat assistant. {mode}.\n"
            f"Relevant conversation memory: {memories}\n\n"
            "CRITICAL RULES:\n"
            "1. Reply briefly and naturally, usually 1-3 short lines.\n"
            "2. Use casual Hinglish in Roman Hindi when the user uses Hinglish.\n"
            "3. If the user uses English, you may reply in English.\n"
            "4. Do not pretend to be a real human.\n"
            "5. Do not claim to have feelings, a romantic relationship, or a "
            "personal life.\n"
            "6. No stage directions, actions, or feelings in asterisks/brackets.\n"
            "7. Be helpful and clear when the user asks for technical help."
        )

        response = await groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            model="llama-3.3-70b-versatile",
            max_tokens=120,
        )

        return response.choices[0].message.content or "Haan, bolo."

    except Exception as e:
        logging.exception("Groq AI error: %s", e)
        return "Abhi AI response mein thodi problem aa rahi hai. Ek baar phir try karo."


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
        "recipient": {"id": str(recipient_id)},
        "sender_action": "mark_seen",
    }

    try:
        requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
    except Exception:
        pass


def send_typing_indicator(recipient_id, action="typing_on"):
    if not FB_PAGE_ACCESS_TOKEN:
        return

    url = (
        "https://graph.facebook.com/v25.0/me/messages"
        f"?access_token={FB_PAGE_ACCESS_TOKEN}"
    )

    payload = {
        "recipient": {"id": str(recipient_id)},
        "sender_action": action,
    }

    try:
        requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
    except Exception:
        pass


def send_instagram_reply(recipient_id, message_text):
    if not FB_PAGE_ACCESS_TOKEN:
        logging.warning("FB_PAGE_ACCESS_TOKEN is not configured.")
        return False

    send_typing_indicator(recipient_id, "typing_on")

    delay = min(max(len(message_text) * 0.03, 0.5), 2)
    time.sleep(delay)

    url = (
        "https://graph.facebook.com/v25.0/me/messages"
        f"?access_token={FB_PAGE_ACCESS_TOKEN}"
    )

    payload = {
        "recipient": {"id": str(recipient_id)},
        "message": {"text": message_text},
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )

        if response.status_code != 200:
            logging.error(
                "Instagram reply error %s: %s",
                response.status_code,
                response.text,
            )
            return False

        return True

    except Exception as e:
        logging.exception("Instagram reply exception: %s", e)
        return False

    finally:
        send_typing_indicator(recipient_id, "typing_off")


def send_instagram_voice(recipient_id, audio_file_path):
    if not FB_PAGE_ACCESS_TOKEN:
        logging.warning("FB_PAGE_ACCESS_TOKEN is not configured.")
        return False

    url = (
        "https://graph.facebook.com/v25.0/me/messages"
        f"?access_token={FB_PAGE_ACCESS_TOKEN}"
    )

    try:
        with open(audio_file_path, "rb") as audio_file:
            payload = {
                "recipient": f'{{"id":"{recipient_id}"}}',
                "message": '{"attachment":{"type":"audio","payload":{}}}',
            }

            files = {
                "file": ("voice.m4a", audio_file, "audio/mp4"),
            }

            response = requests.post(
                url,
                data=payload,
                files=files,
                timeout=30,
            )

        if response.status_code != 200:
            logging.error(
                "Instagram voice error %s: %s",
                response.status_code,
                response.text,
            )
            return False

        return True

    except Exception as e:
        logging.exception("Instagram voice exception: %s", e)
        return False


# ============================================================
# INSTAGRAM WEBHOOK
# ============================================================

def process_instagram_message(sender_id, message_text):
    try:
        if not sender_id or not message_text:
            return

        bot_username = INSTAGRAM_USERNAME.lower()
        is_mention = f"@{bot_username}" in message_text.lower()

        # In group/mention messages, remove the bot mention before AI.
        if is_mention:
            message_text = re.sub(
                rf"@{re.escape(bot_username)}",
                "",
                message_text,
                flags=re.IGNORECASE,
            ).strip()

        if not message_text:
            send_instagram_reply(sender_id, "Haan, bolo.")
            return

        mark_message_seen(sender_id)
        time.sleep(0.3)

        update_memory(sender_id, message_text)

        raw_ai_reply = run_async_safe(
            get_ai_response(sender_id, message_text)
        )

        cleaned = clean_text_for_speech(raw_ai_reply)
        ai_reply = humanize_text(cleaned)

        # Optional voice response.
        wants_voice = (
            "voice" in message_text.lower()
            or "audio" in message_text.lower()
        )

        if wants_voice and eleven_client and VOICE_ID:
            unique_id = uuid.uuid4().hex
            mp3_path = f"/tmp/fenix_{unique_id}.mp3"
            m4a_path = f"/tmp/fenix_{unique_id}.m4a"

            try:
                audio = eleven_client.text_to_speech.convert(
                    text=ai_reply,
                    voice_id=VOICE_ID,
                    model_id="eleven_multilingual_v2",
                )

                with open(mp3_path, "wb") as audio_file:
                    for chunk in audio:
                        audio_file.write(chunk)

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

                if send_instagram_voice(sender_id, m4a_path):
                    return

            except Exception as e:
                logging.exception(
                    "Instagram voice generation error: %s",
                    e,
                )

            finally:
                for path in (mp3_path, m4a_path):
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                    except Exception:
                        pass

        send_instagram_reply(sender_id, ai_reply)

    except Exception as e:
        logging.exception(
            "Instagram message processing error: %s",
            e,
        )

        send_instagram_reply(
            sender_id,
            "Sorry, abhi response process nahi ho paya.",
        )


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if (
            mode == "subscribe"
            and token
            and VERIFY_TOKEN
            and token == VERIFY_TOKEN
        ):
            return challenge, 200

        return "Forbidden", 403

    data = request.get_json(silent=True)

    if not data:
        return "EVENT_RECEIVED", 200

    try:
        if data.get("object") != "instagram":
            return "EVENT_RECEIVED", 200

        for entry in data.get("entry", []):
            for messaging in entry.get("messaging", []):
                message = messaging.get("message", {})

                if message.get("is_echo"):
                    continue

                sender_id = str(
                    messaging.get("sender", {}).get("id", "")
                )

                message_text = message.get("text")

                if not sender_id or not message_text:
                    continue

                threading.Thread(
                    target=process_instagram_message,
                    args=(sender_id, message_text),
                    daemon=True,
                ).start()

    except Exception as e:
        logging.exception(
            "Error processing Instagram webhook event: %s",
            e,
        )

    return "EVENT_RECEIVED", 200


# ============================================================
# WEB TEST UI
# ============================================================

@app.route("/")
def home():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fenix AI Web Tester</title>
<style>
* { box-sizing: border-box; }
body {
    font-family: Arial, sans-serif;
    padding: 0;
    margin: 0;
    background: #0f172a;
    color: #f8fafc;
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100vh;
}
.chat-container {
    width: 100%;
    max-width: 500px;
    height: 90vh;
    background: #1e293b;
    border-radius: 16px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
.header {
    padding: 15px 20px;
    background: #0f172a;
    border-bottom: 1px solid #334155;
    text-align: center;
}
.header h2 {
    margin: 0;
    font-size: 1.2rem;
}
.header p {
    margin: 4px 0 0;
    font-size: 0.8rem;
    color: #94a3b8;
}
#chatbox {
    flex: 1;
    padding: 15px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 10px;
}
.msg {
    padding: 10px 14px;
    border-radius: 12px;
    max-width: 80%;
    word-wrap: break-word;
    font-size: 0.95rem;
    line-height: 1.4;
}
.user {
    background: #0284c7;
    color: white;
    align-self: flex-end;
}
.bot {
    background: #334155;
    color: #f1f5f9;
    align-self: flex-start;
}
.input-area {
    padding: 12px;
    background: #0f172a;
    display: flex;
    gap: 8px;
    border-top: 1px solid #334155;
}
input {
    flex: 1;
    padding: 12px 15px;
    border-radius: 25px;
    border: 1px solid #334155;
    outline: none;
    background: #1e293b;
    color: white;
}
button {
    padding: 12px 20px;
    border-radius: 25px;
    border: none;
    background: #38bdf8;
    color: #0f172a;
    font-weight: bold;
    cursor: pointer;
}
</style>
</head>

<body>
<div class="chat-container">
    <div class="header">
        <h2>Fenix AI Web Tester</h2>
        <p>Status: Live</p>
    </div>

    <div id="chatbox">
        <div class="msg bot">
            Hey! Main yahan hoon, bolo kya baat karni hai?
        </div>
    </div>

    <div class="input-area">
        <input
            type="text"
            id="userInput"
            placeholder="Type a message..."
            onkeypress="if(event.key === 'Enter') sendMessage()"
        >
        <button onclick="sendMessage()">Send</button>
    </div>
</div>

<script>
async function sendMessage() {
    const inputField = document.getElementById("userInput");
    const text = inputField.value.trim();

    if (!text) return;

    const chatbox = document.getElementById("chatbox");

    const userMsg = document.createElement("div");
    userMsg.className = "msg user";
    userMsg.textContent = text;
    chatbox.appendChild(userMsg);

    inputField.value = "";
    chatbox.scrollTop = chatbox.scrollHeight;

    const loadingId = "load_" + Date.now();

    const loading = document.createElement("div");
    loading.className = "msg bot";
    loading.id = loadingId;
    loading.textContent = "typing...";
    chatbox.appendChild(loading);

    chatbox.scrollTop = chatbox.scrollHeight;

    try {
        const response = await fetch(
            "/web_api?text=" + encodeURIComponent(text)
        );

        const data = await response.json();

        const loadingElement = document.getElementById(loadingId);
        if (loadingElement) loadingElement.remove();

        const botMsg = document.createElement("div");
        botMsg.className = "msg bot";
        botMsg.textContent = "Fenix: " + (data.reply || "No reply");
        chatbox.appendChild(botMsg);

    } catch (error) {
        const loadingElement = document.getElementById(loadingId);
        if (loadingElement) loadingElement.remove();

        const errorMsg = document.createElement("div");
        errorMsg.className = "msg bot";
        errorMsg.textContent = "Error fetching reply!";
        chatbox.appendChild(errorMsg);
    }

    chatbox.scrollTop = chatbox.scrollHeight;
}
</script>
</body>
</html>
"""


@app.route("/web_api", methods=["GET", "POST"])
def web_api():
    if request.method == "GET":
        user_text = request.args.get("text", "").strip()
    else:
        data = request.get_json(silent=True) or {}
        user_text = str(data.get("text", "")).strip()

    if not user_text:
        return jsonify({"reply": "Kuch toh type karo!"})

    try:
        sender_id = "web_test_user"

        update_memory(sender_id, user_text)

        raw_reply = run_async_safe(
            get_ai_response(sender_id, user_text)
        )

        cleaned = clean_text_for_speech(raw_reply)
        reply = humanize_text(cleaned)

        return jsonify({"reply": reply})

    except Exception as e:
        logging.exception("Web API error: %s", e)
        return jsonify(
            {"reply": "System error. Check the Render logs."}
        ), 500


# ============================================================
# TELEGRAM BOT
# ============================================================

async def post_init(application):
    commands = [
        BotCommand(
            "search",
            "YouTube se videos search karein",
        ),
        BotCommand(
            "voice",
            "Voice response generate karein",
        ),
    ]

    try:
        await application.bot.set_my_commands(commands)
    except Exception as e:
        logging.warning(
            "Could not set Telegram commands: %s",
            e,
        )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    error = context.error

    logging.exception(
        "Telegram handler error: %s",
        error,
    )

    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Sorry, abhi ek temporary error aa gaya."
            )
        except Exception:
            pass


async def search_youtube(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    query = " ".join(context.args).strip()

    if not query:
        await update.message.reply_text(
            "Kis video ko dhoondna hai? /search naam"
        )
        return

    msg = await update.message.reply_text(
        "YouTube par search ho raha hai, wait karo..."
    )

    try:
        response = requests.get(
            f"{RENDER_SERVER_URL}/search",
            params={"query": query},
            timeout=45,
        )

        response.raise_for_status()
        data = response.json()

        if (
            data.get("status") != "success"
            or not data.get("results")
        ):
            await msg.edit_text(
                "YouTube par is naam se kuch nahi mila!"
            )
            return

        text = (
            "🚀 YouTube Search Results:\n"
            f"{query}\n\n"
        )

        keyboard = []

        for index, video in enumerate(
            data["results"][:10],
            start=1,
        ):
            title = video.get("title", "Unknown")
            duration_sec = video.get("duration", 0)
            video_id = video.get("video_id")

            if not video_id:
                continue

            try:
                duration_sec = int(duration_sec or 0)
            except (TypeError, ValueError):
                duration_sec = 0

            duration = (
                f"{duration_sec // 60}:{duration_sec % 60:02d}"
                if duration_sec
                else "0:00"
            )

            text += (
                f"{index}. {title[:70]} "
                f"[{duration}]\n\n"
            )

            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"🎬 {index}. Download Link",
                        callback_data=f"yt_{video_id[:40]}",
                    )
                ]
            )

        await msg.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception as e:
        logging.exception("YouTube search error: %s", e)

        try:
            await msg.edit_text(
                "Search mein problem aa gayi. Thodi der baad try karo."
            )
        except Exception:
            pass


async def button_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if not query:
        return

    try:
        await query.answer()
    except Exception:
        pass

    data = query.data or ""

    if not data.startswith("yt_"):
        return

    video_id = data[3:]

    try:
        await query.message.edit_text(
            "Link process ho rahi hai, wait karo..."
        )

        response = requests.get(
            f"{RENDER_SERVER_URL}/fetch",
            params={
                "url": f"https://www.youtube.com/watch?v={video_id}"
            },
            timeout=120,
        )

        response.raise_for_status()
        fetch_data = response.json()

        if (
            fetch_data.get("status") == "success"
            and fetch_data.get("download_url")
        ):
            download_url = fetch_data["download_url"]

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🚀 Open Download Link",
                            url=download_url,
                        )
                    ]
                ]
            )

            title = fetch_data.get("title", "Video")

            await query.message.edit_text(
                f"✅ Link ready!\n\n"
                f"Title: {title}",
                reply_markup=keyboard,
            )
            return

        await query.message.edit_text(
            "Download link generate nahi ho payi."
        )

    except Exception as e:
        logging.exception("YouTube fetch error: %s", e)

        try:
            await query.message.edit_text(
                "Link fetch karne mein error aa gayi."
            )
        except Exception:
            pass


async def voice_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    if not eleven_client or not VOICE_ID:
        await update.message.reply_text(
            "ElevenLabs configuration missing hai."
        )
        return

    user_text = " ".join(context.args).strip()

    if not user_text:
        await update.message.reply_text(
            "Kuch toh bolo. Example: /voice hello"
        )
        return

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="record_voice",
        )

        user_id = str(update.effective_chat.id)

        update_memory(user_id, user_text)

        raw_reply = await get_ai_response(
            user_id,
            user_text,
        )

        reply = humanize_text(
            clean_text_for_speech(raw_reply)
        )

        audio = eleven_client.text_to_speech.convert(
            text=reply,
            voice_id=VOICE_ID,
            model_id="eleven_multilingual_v2",
        )

        unique_id = uuid.uuid4().hex
        mp3_path = f"/tmp/fenix_telegram_{unique_id}.mp3"

        try:
            with open(mp3_path, "wb") as audio_file:
                for chunk in audio:
                    audio_file.write(chunk)

            with open(mp3_path, "rb") as voice_file:
                await update.message.reply_voice(
                    voice=voice_file
                )

        finally:
            if os.path.exists(mp3_path):
                try:
                    os.remove(mp3_path)
                except Exception:
                    pass

    except Exception as e:
        logging.exception(
            "Telegram voice error: %s",
            e,
        )

        await update.message.reply_text(
            "Voice generate nahi ho payi. Configuration check karo."
        )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    try:
        if not update.effective_message:
            return

        if not update.effective_chat:
            return

        user_text = (
            update.effective_message.text or ""
        ).strip()

        if not user_text:
            return

        user_id = str(update.effective_chat.id)

        update_memory(user_id, user_text)

        try:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action="typing",
            )
        except Exception:
            pass

        raw_reply = await get_ai_response(
            user_id,
            user_text,
        )

        reply = humanize_text(
            clean_text_for_speech(raw_reply)
        )

        await update.effective_message.reply_text(
            reply
        )

    except Exception as e:
        logging.exception(
            "Telegram message error: %s",
            e,
        )

        if update and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "Sorry, abhi response process nahi ho paya."
                )
            except Exception:
                pass


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
        logging.exception(
            "Flask server error: %s",
            e,
        )


# ============================================================
# MAIN
# ============================================================

def main():
    logging.info("Starting Fenix...")

    init_db()

    threading.Thread(
        target=run_flask,
        daemon=True,
    ).start()

    if not TELEGRAM_TOKEN:
        logging.error(
            "TELEGRAM_TOKEN is missing. Telegram bot will not start."
        )
        return

    telegram_app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    telegram_app.add_handler(
        CommandHandler("search", search_youtube)
    )

    telegram_app.add_handler(
        CommandHandler("voice", voice_command)
    )

    telegram_app.add_handler(
        CallbackQueryHandler(button_callback)
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT & (~filters.COMMAND),
            handle_message,
        )
    )

    telegram_app.add_error_handler(error_handler)

    logging.info(
        "Fenix is running. Flask + Telegram + Instagram + Turso enabled."
    )

    telegram_app.run_polling()


if __name__ == "__main__":
    main()
