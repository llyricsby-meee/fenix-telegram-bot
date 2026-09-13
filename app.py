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

# --- CONFIG ---
app = Flask(__name__)
@app.route('/')
def home(): return "Fenix is Alive & Webhook Connected!"

# --- TURSO DATABASE CONFIG ---
TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

def get_turso_client():
    return libsql_client.create_client(url=TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)

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

# --- INSTAGRAM SEEN, TYPING & ONLINE SIMULATION ---
def mark_message_seen(recipient_id):
    page_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
    if not page_token: return
    url = f"https://graph.facebook.com/v25.0/me/messages?access_token={page_token}"
    payload = {"recipient": {"id": recipient_id}, "sender_action": "mark_seen"}
    headers = {"Content-Type": "application/json"}
    try: requests.post(url, json=payload, headers=headers, timeout=5)
    except: pass

def send_typing_indicator(recipient_id, action="typing_on"):
    page_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
    if not page_token: return
    url = f"https://graph.facebook.com/v25.0/me/messages?access_token={page_token}"
    payload = {"recipient": {"id": recipient_id}, "sender_action": action}
    headers = {"Content-Type": "application/json"}
    try: requests.post(url, json=payload, headers=headers, timeout=5)
    except: pass

def send_instagram_reply(recipient_id, message_text, is_group=False):
    page_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
    if not page_token: return
    
    send_typing_indicator(recipient_id, "typing_on")
    delay = min(max(len(message_text) * 0.05, 1), 3)
    time.sleep(delay)
    
    url = f"https://graph.facebook.com/v25.0/me/messages?access_token={page_token}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text}
    }
    headers = {"Content-Type": "application/json"}
    
    try: 
        response = requests.post(url, json=payload, headers=headers, timeout=10)
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

# --- INSTAGRAM WEBHOOK ---
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
    if not data:
        return "OK", 200

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
                        
                        async def fetch_and_reply():
                            raw_ai_reply = await get_ai_response(sender_id, message_text)
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
                        
                        threading.Thread(target=lambda: asyncio.run(fetch_and_reply()), daemon=True).start()
    except Exception as e:
        logging.error(f"Error processing webhook event: {e}")
        
    return "EVENT_RECEIVED", 200

load_dotenv()
groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
eleven_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
VOICE_ID = os.environ.get("ELEVEN_LABS_VOICE_ID")
RENDER_SERVER_URL = "https://my-youtube-api-1uf5.onrender.com"

# --- MEMORY ENGINE (Turso Cloud Database) ---
def init_db():
    try:
        client = get_turso_client()
        client.execute('''CREATE TABLE IF NOT EXISTS memory (user_id TEXT PRIMARY KEY, count INTEGER, context TEXT)''')
        client.close()
    except Exception as e:
        logging.error(f"Init DB error: {e}")

def get_data(user_id):
    try:
        client = get_turso_client()
        rs = client.execute("SELECT count, context FROM memory WHERE user_id = ?", [user_id])
        client.close()
        if rs.rows:
            return rs.rows[0][0], rs.rows[0]
        return 0, ""
    except Exception as e:
        logging.error(f"Get data error: {e}")
        return 0, ""

def update_memory(user_id, text):
    try:
        count, context = get_data(user_id)
        new_count = count + 1
        new_context = f"{context} {text}"[-2000:] 
        client = get_turso_client()
        client.execute(
            "INSERT INTO memory (user_id, count, context) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET count=excluded.count, context=excluded.context",
            [user_id, new_count, new_context]
        )
        client.close()
        return new_count
    except Exception as e:
        logging.error(f"Update memory error: {e}")
        return 0

# --- TELEGRAM BOT LOGIC ---
telegram_app = None

async def post_init(application):
    commands = [BotCommand("search", "यूट्यूब से गाने और वीडियो खोजें 🔍"), BotCommand("voice", "Fenix की आवाज में जवाब सुनें 🎙️")]
    try: 
        await application.bot.set_my_commands(commands)
    except: 
        pass
    
    # Webhook set karne ka sahi tarika (event loop ke andar)
    render_domain = os.environ.get("RENDER_EXTERNAL_URL")
    if render_domain:
        webhook_url = f"{render_domain}/telegram_webhook"
        await application.bot.set_webhook(webhook_url)
        logging.info(f"Telegram Webhook set to: {webhook_url}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    err_msg = str(context.error)
    logging.error(f"Telegram Error: {err_msg}")
    if update and update.effective_message:
        try: 
            await update.effective_message.reply_text(f"⚠️ **Real Error Debug:**\n`{err_msg}`", parse_mode='Markdown')
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
    video_id = data.split("_")
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
            try: os.remove(mp3_path)
            except: pass

async def get_ai_response(user_id, user_text):
    count, memories = get_data(user_id)
    if count < 50: mode = "Normal, friendly and caring boyfriend"
    elif count < 150: mode = "Charming, sweet and romantic boyfriend"
    else: mode = "Very flirty, playful, romantic and possessive boyfriend"
    
    system_prompt = (
        f"You are Fenix, a human boyfriend chatting on Instagram/WhatsApp. {mode}. Memory: {memories}\n\n"
        "CRITICAL RULES FOR TEXTING:\n"
        "1. Write EXTREMELY short replies like real humans text on chat. Line max 1-2.\n"
        "2. Speak ONLY in casual, natural Hinglish (Roman Hindi script, lowercase style).\n"
        "3. NEVER write long paragraphs or robot-like explanations.\n"
        "4. NO stage directions, actions, or feelings in asterisks/brackets."
    )
    
    response = await groq_client.chat.completions.create(
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}],
        model="llama-3.3-70b-versatile",
        max_tokens=60
    )
    return response.choices[0].message.content

async def handle_message(update: Update, update_context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    update_memory(user_id, update.message.text)
    await update_context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    delay = min(max(len(update.message.text) * 0.05, 1), 3)
    await asyncio.sleep(delay)
    raw_reply = await get_ai_response(user_id, update.message.text)
    cleaned = clean_text_for_speech(raw_reply)
    reply = humanize_text(cleaned)
    await update.message.reply_text(reply)

# --- TELEGRAM WEBHOOK ROUTE IN FLASK ---
@app.route('/telegram_webhook', methods=['POST'])
def telegram_webhook():
    if telegram_app:
        async def process_update():
            update = Update.de_json(request.get_json(force=True), telegram_app.bot)
            await telegram_app.process_update(update)
        asyncio.run(process_update())
    return "OK", 200

def init_telegram_bot():
    global telegram_app
    telegram_app = Application.builder().token(os.environ.get("TELEGRAM_TOKEN")).post_init(post_init).build()
    telegram_app.add_handler(CommandHandler("search", search_youtube)) 
    telegram_app.add_handler(CommandHandler("voice", voice_command))
    telegram_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    telegram_app.add_handler(CallbackQueryHandler(button_callback))
    telegram_app.add_error_handler(error_handler)
    # Purana get_event_loop() wala code yahan se hata diya hai

if __name__ == '__main__':
    init_db()
    init_telegram_bot()
    print("Fenix Unified Webhook Server is running!")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
    
