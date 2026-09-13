import os, logging, asyncio, requests, threading, subprocess, re, time, random, uuid
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.ext import Application, ContextTypes, MessageHandler, CommandHandler, CallbackQueryHandler, filters
from groq import AsyncGroq
from elevenlabs.client import ElevenLabs
import libsql_client

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

load_dotenv()
app = Flask(__name__)

# --- SAFE ASYNC RUNNER (Fixes "No running event loop" & Loop Errors) ---
def run_async_safe(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

# --- TURSO DATABASE CONFIG & AUTO-FIX ---
TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")

def get_turso_client():
    url = TURSO_DATABASE_URL or ""
    # Auto-fix wss:// to libsql:// to prevent Error 400
    if url.startswith("wss://"):
        url = url.replace("wss://", "libsql://", 1)
    return libsql_client.create_client(url=url, auth_token=TURSO_AUTH_TOKEN)

# --- MEMORY ENGINE (Turso Cloud Database) ---
async def init_db_async():
    try:
        if not TURSO_DATABASE_URL: return
        client = get_turso_client()
        await client.execute('''CREATE TABLE IF NOT EXISTS memory (user_id TEXT PRIMARY KEY, count INTEGER, context TEXT)''')
        await client.close()
    except Exception as e:
        logging.error(f"Init DB async error: {e}")

def init_db():
    try:
        run_async_safe(init_db_async())
    except Exception as e:
        logging.error(f"Init DB error: {e}")

async def get_data_async(user_id):
    try:
        if not TURSO_DATABASE_URL: return 0, ""
        client = get_turso_client()
        rs = await client.execute("SELECT count, context FROM memory WHERE user_id = ?", [user_id])
        await client.close()
        if rs.rows:
            return rs.rows[0][0], rs.rows[0][1]
        return 0, ""
    except Exception as e:
        logging.error(f"Get data error: {e}")
        return 0, ""

def get_data(user_id):
    try:
        return run_async_safe(get_data_async(user_id))
    except Exception as e:
        logging.error(f"Get data sync error: {e}")
        return 0, ""

async def update_memory_async(user_id, text):
    try:
        if not TURSO_DATABASE_URL: return 0
        count, context = await get_data_async(user_id)
        new_count = count + 1
        new_context = f"{context} {text}"[-2000:] 
        client = get_turso_client()
        await client.execute(
            "INSERT INTO memory (user_id, count, context) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET count=excluded.count, context=excluded.context",
            [user_id, new_count, new_context]
        )
        await client.close()
        return new_count
    except Exception as e:
        logging.error(f"Update memory error: {e}")
        return 0

def update_memory(user_id, text):
    try:
        return run_async_safe(update_memory_async(user_id, text))
    except Exception as e:
        logging.error(f"Update memory sync error: {e}")
        return 0

# --- WEB UI & TESTING ROUTE ---
@app.route('/')
def home():
    return '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Fenix AI Web Tester</title>
        <style>
            * { box-sizing: border-box; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 0; margin: 0; background: #0f172a; color: #f8fafc; display: flex; justify-content: center; align-items: center; height: 100vh; }
            .chat-container { width: 100%; max-width: 500px; height: 90vh; background: #1e293b; border-radius: 16px; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
            .header { padding: 15px 20px; background: #0f172a; border-bottom: 1px solid #334155; text-align: center; }
            .header h2 { margin: 0; font-size: 1.2rem; color: #38bdf8; }
            .header p { margin: 3px 0 0 0; font-size: 0.8rem; color: #94a3b8; }
            #chatbox { flex: 1; padding: 15px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
            .msg { padding: 10px 14px; border-radius: 12px; max-width: 80%; word-wrap: break-word; font-size: 0.95rem; line-height: 1.4; }
            .user { background: #0284c7; color: white; align-self: flex-end; border-bottom-right-radius: 2px; }
            .bot { background: #334155; color: #f1f5f9; align-self: flex-start; border-bottom-left-radius: 2px; }
            .input-area { padding: 12px; background: #0f172a; display: flex; gap: 8px; border-top: 1px solid #334155; }
            input { flex: 1; padding: 12px 15px; border-radius: 25px; border: 1px solid #334155; outline: none; background: #1e293b; color: white; font-size: 0.95rem; }
            button { padding: 12px 20px; border-radius: 25px; border: none; background: #38bdf8; color: #0f172a; font-weight: bold; cursor: pointer; transition: 0.2s; }
            button:hover { background: #0284c7; color: white; }
        </style>
    </head>
    <body>
        <div class="chat-container">
            <div class="header">
                <h2>Fenix AI Web Tester 🤖</h2>
                <p>Status: Live & Multi-Platform Active</p>
            </div>
            <div id="chatbox">
                <div class="msg bot">Hey baby! Main yahan hoon, bolo kya baat karni hai? ❤️</div>
            </div>
            <div class="input-area">
                <input type="text" id="userInput" placeholder="Type a message..." onkeypress="if(event.key === 'Enter') sendMessage()">
                <button onclick="sendMessage()">Send</button>
            </div>
        </div>

        <script>
            async function sendMessage() {
                let inputField = document.getElementById("userInput");
                let text = inputField.value.trim();
                if (!text) return;
                
                let chatbox = document.getElementById("chatbox");
                chatbox.innerHTML += `<div class="msg user">${text}</div>`;
                inputField.value = "";
                chatbox.scrollTop = chatbox.scrollHeight;

                let loadingId = "load_" + Date.now();
                chatbox.innerHTML += `<div class="msg bot" id="${loadingId}">typing...</div>`;
                chatbox.scrollTop = chatbox.scrollHeight;

                try {
                    let response = await fetch("/web_api?text=" + encodeURIComponent(text));
                    let data = await response.json();
                    document.getElementById(loadingId).remove();
                    chatbox.innerHTML += `<div class="msg bot"><b>Fenix:</b> ${data.reply}</div>`;
                } catch(e) {
                    document.getElementById(loadingId).remove();
                    chatbox.innerHTML += `<div class="msg bot" style="color:#ef4444;">Error fetching reply!</div>`;
                }
                chatbox.scrollTop = chatbox.scrollHeight;
            }
        </script>
    </body>
    </html>
    '''

@app.route('/web_api', methods=['GET', 'POST'])
def web_api():
    user_text = request.args.get('text') if request.method == 'GET' else (request.get_json(silent=True) or {}).get('text')
    if not user_text:
        return jsonify({"reply": "Kuch toh type karo baby! ❤️"})
    
    try:
        sender_id = "web_test_user"
        update_memory(sender_id, user_text)
        raw_reply = run_async_safe(get_ai_response(sender_id, user_text))
        cleaned = clean_text_for_speech(raw_reply)
        reply = humanize_text(cleaned)
        return jsonify({"reply": reply})
    except Exception as e:
        logging.error(f"Web API Error: {e}")
        return jsonify({"reply": f"System Error: {e}"}), 500

# --- TEXT CLEANER & HUMANIZER ---
def clean_text_for_speech(text):
    if not text: return ""
    cleaned = re.sub(r'\*.*?\*', '', text)
    cleaned = re.sub(r'\(.*?\)', '', cleaned)
    cleaned = re.sub(r'\[.*?\]', '', cleaned)
    cleaned = re.sub(r'\{.*?\}', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def humanize_text(text):
    if not text: return text
    slangs = ["kyaa", "acha", "bta", "sachii", "umm...", "hehe", "haan", "na"]
    if random.random() > 0.6 and not text.endswith("..."):
        text = text + " ..."
    if random.random() > 0.7 and not any(text.lower().startswith(s) for s in slangs):
        text = random.choice(slangs).capitalize() + ", " + text.lower()
    return text

# --- INSTAGRAM INTEGRATION ---
def mark_message_seen(recipient_id):
    page_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
    if not page_token: return
    url = f"https://graph.facebook.com/v25.0/me/messages?access_token={page_token}"
    payload = {"recipient": {"id": recipient_id}, "sender_action": "mark_seen"}
    try: requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=5)
    except: pass

def send_typing_indicator(recipient_id, action="typing_on"):
    page_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
    if not page_token: return
    url = f"https://graph.facebook.com/v25.0/me/messages?access_token={page_token}"
    payload = {"recipient": {"id": recipient_id}, "sender_action": action}
    try: requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=5)
    except: pass

def send_instagram_reply(recipient_id, message_text, is_group=False):
    page_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
    if not page_token: return
    
    send_typing_indicator(recipient_id, "typing_on")
    delay = min(max(len(message_text) * 0.05, 1), 3)
    time.sleep(delay)
    
    url = f"https://graph.facebook.com/v25.0/me/messages?access_token={page_token}"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": message_text}}
    try: 
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        if response.status_code != 200:
             logging.error(f"Instagram Reply Error: {response.text}")
    except Exception as e:
        logging.error(f"Instagram Reply Exception: {e}")
        
    send_typing_indicator(recipient_id, "typing_off")

def send_instagram_voice(recipient_id, audio_file_path):
    page_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
    if not page_token: return
    url = f"https://graph.facebook.com/v25.0/me/messages?access_token={page_token}"
    try:
        with open(audio_file_path, 'rb') as audio_file:
            payload = {'recipient': f'{{"id":"{recipient_id}"}}', 'message': '{"attachment":{"type":"audio", "payload":{}}}'}
            files = {'file': ('voice.m4a', audio_file, 'audio/mp4')}
            response = requests.post(url, data=payload, files=files, timeout=30)
            if response.status_code != 200:
                logging.error(f"Failed to send Instagram voice: {response.text}")
    except Exception as e:
        logging.error(f"Instagram Voice Error: {e}")

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        if mode and token and mode == 'subscribe' and token == os.environ.get("VERIFY_TOKEN"):
            return challenge, 200
        return "Forbidden", 403
        
    data = request.get_json(silent=True)
    if not data: return "OK", 200

    try:
        if data.get("object") == "instagram":
            for entry in data.get("entry", []):
                for messaging in entry.get("messaging", []):
                    sender_id = str(messaging.get("sender", {}).get("id"))
                    message_text = messaging.get("message", {}).get("text")
                    bot_username = os.environ.get("INSTAGRAM_USERNAME", "really_innocent_.nawab").lower()
                    
                    if sender_id and message_text and not messaging.get("message", {}).get("is_echo"):
                        is_mention = f"@{bot_username}" in message_text.lower()
                        if is_mention:
                             message_text = re.sub(rf'@{bot_username}', '', message_text, flags=re.IGNORECASE).strip()
                        
                        mark_message_seen(sender_id)
                        time.sleep(0.5)
                        update_memory(sender_id, message_text)
                        
                        def fetch_and_reply():
                            raw_ai_reply = run_async_safe(get_ai_response(sender_id, message_text))
                            cleaned = clean_text_for_speech(raw_ai_reply)
                            ai_reply = humanize_text(cleaned)
                            
                            if "voice" in message_text.lower() or "audio" in message_text.lower():
                                unique_id = uuid.uuid4().hex
                                mp3_path = f"/tmp/r_insta_{unique_id}.mp3"
                                m4a_path = f"/tmp/r_insta_{unique_id}.m4a"
                                try:
                                    audio = eleven_client.text_to_speech.convert(
                                        text=ai_reply, 
                                        voice_id=VOICE_ID, 
                                        model_id="eleven_multilingual_v2"
                                    )
                                    with open(mp3_path, "wb") as f:
                                        for chunk in audio: f.write(chunk)
                                    subprocess.run(["ffmpeg", "-y", "-i", mp3_path, "-c:a", "aac", m4a_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                    send_instagram_voice(sender_id, m4a_path)
                                    return
                                except Exception as ex:
                                    logging.error(f"Insta Voice Gen Error: {ex}")
                                finally:
                                    for p in [mp3_path, m4a_path]:
                                        if os.path.exists(p):
                                            try: os.remove(p)
                                            except: pass
                                    
                            send_instagram_reply(sender_id, ai_reply, is_group=is_mention)
                        
                        threading.Thread(target=fetch_and_reply, daemon=True).start()
    except Exception as e:
        logging.error(f"Error processing webhook event: {e}")
        
    return "EVENT_RECEIVED", 200

# --- AI & APIS INITIALIZATION ---
groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
eleven_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
VOICE_ID = os.environ.get("ELEVEN_LABS_VOICE_ID")
RENDER_SERVER_URL = "https://my-youtube-api-1uf5.onrender.com"

# --- TELEGRAM BOT INTEGRATION ---
telegram_app = None

async def post_init(application):
    commands = [BotCommand("search", "यूट्यूब से गाने और वीडियो खोजें 🔍"), BotCommand("voice", "Fenix की आवाज में जवाब सुनें 🎙️")]
    try: await application.bot.set_my_commands(commands)
    except: pass
    
    render_domain = os.environ.get("RENDER_EXTERNAL_URL")
    if render_domain:
        webhook_url = f"{render_domain}/telegram_webhook"
        await application.bot.set_webhook(webhook_url)
        logging.info(f"Telegram Webhook set to: {webhook_url}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    err_msg = str(context.error)
    logging.error(f"Telegram Error: {err_msg}")
    if update and update.effective_message:
        try: await update.effective_message.reply_text(f"⚠️ **Real Error Debug:**\n`{err_msg}`", parse_mode='Markdown')
        except: pass

async def search_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Baby, kis gane ya video ko dhoondna hai? `/search [naam]`")
        return
    msg = await update.message.reply_text("🔍 YouTube par dhoond raha hoon, thoda wait karo baby... ❤️")
    try:
        response = requests.get(f"{RENDER_SERVER_URL}/search?query={query}", timeout=45)
        data = response.json()
        if data.get("status") != "success" or not data.get("results"):
            await msg.edit_text("Baby, YouTube par is naam se kuch nahi mila! 💔")
            return
        text = f"🚀 *YouTube Search Results:*\n`{query}`\n\n"
        keyboard = []
        for index, video in enumerate(data["results"][:10], start=1):
            title, duration_sec, video_id = video.get("title", "Unknown"), video.get("duration", 0), video.get("video_id")
            if not video_id: continue
            duration = f"{int(duration_sec) // 60}:{int(duration_sec) % 60:02d}" if duration_sec else "0:00"
            text += f"{index}. *{title[:50]}* [{duration}]\n\n"
            keyboard.append([InlineKeyboardButton(f"🎬 {index}. Download Link", callback_data=f"yt_{video_id[:40]}")])
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        await msg.edit_text(f"Baby, search error: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try: await query.answer()
    except: pass
    data = query.data
    if not data or not data.startswith("yt_"): return
    video_id = data.split("_")[1]
    try: await query.message.edit_text("📥 Baby, aapki link process ho rahi hai... Wait karo! 🥰")
    except: pass
    try:
        response = requests.get(f"{RENDER_SERVER_URL}/fetch?url=https://www.youtube.com/watch?v={video_id}", timeout=120)
        fetch_data = response.json()
        if fetch_data.get("status") == "success" and fetch_data.get("download_url"):
            dl_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Click Here to Download", url=fetch_data.get("download_url"))]])
            await query.message.edit_text(f"✅ *Link Taiyar Hai!*\n\n🎵 *Title:* {fetch_data.get('title', 'Video')}\n👇", reply_markup=dl_markup, parse_mode='Markdown')
            return
        await query.message.edit_text("Baby, download fail ho gaya! 💔")
    except Exception as e:
        await query.message.edit_text(f"Baby, error: {e}")

async def voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    unique_id = uuid.uuid4().hex
    mp3_path = f"/tmp/r_{unique_id}.mp3"
    try:
        user_text = " ".join(context.args)
        if not user_text:
            await update.message.reply_text("Baby, kuch toh bolo! `/voice [tumhara sawal]`")
            return
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='record_voice')
        raw_reply = await get_ai_response(str(update.effective_chat.id), user_text)
        cleaned = clean_text_for_speech(raw_reply)
        reply = humanize_text(cleaned)
        audio = eleven_client.text_to_speech.convert(text=reply, voice_id=VOICE_ID, model_id="eleven_multilingual_v2")
        with open(mp3_path, "wb") as f:
            for chunk in audio: f.write(chunk)
        with open(mp3_path, "rb") as voice_file:
            await update.message.reply_voice(voice=voice_file)
    except Exception as e:
        logging.error(f"Voice Command Error: {e}")
        await update.message.reply_text(f"Voice error: {e}")
    finally:
        if os.path.exists(mp3_path):
  
