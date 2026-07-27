import os, logging, sqlite3, asyncio, requests, threading, subprocess, re, time, random
from flask import Flask, request
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, CallbackQueryHandler, filters
from groq import AsyncGroq
from elevenlabs.client import ElevenLabs

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- CONFIG ---
app = Flask(__name__)
@app.route('/')
def home(): return "Fenix is Alive!"

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
    
    # Typing indicator
    send_typing_indicator(recipient_id, "typing_on")
    
    # Natural delay
    delay = min(max(len(message_text) * 0.05, 1), 3)
    time.sleep(delay)
    
    url = f"https://graph.facebook.com/v25.0/me/messages?access_token={page_token}"
    
    # अगर यह ग्रुप मैसेज है, तो 'message_type' को 'RESPONSE' पर सेट करना पड़ सकता है
    # हालाँकि, Facebook Graph API में recipient.id आमतौर पर ग्रुप थ्रेड ID को भी सपोर्ट करता है।
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
        
    # Typing indicator off
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
        
    data = request.json
    try:
        if data.get("object") == "instagram":
            for entry in data.get("entry", []):
                for messaging in entry.get("messaging", []):
                    # Sender ID और Message Text प्राप्त करें
                    sender_id = messaging.get("sender", {}).get("id")
                    message_text = messaging.get("message", {}).get("text")
                    
                    # यह चेक करने के लिए कि क्या यह ग्रुप चैट से आया है या कोई mention है
                    # (webhook payload में कभी-कभी 'tags' या 'mentions' की जानकारी भी होती है, 
                    # लेकिन सबसे आसान तरीका है मैसेज टेक्स्ट में अपना @username ढूँढना)
                    
                    # अपना Instagram Username यहाँ डालें (बिना @ के)
                    # आप इसे .env से भी ले सकते हैं, जैसे: os.environ.get("INSTAGRAM_USERNAME")
                    bot_username = os.environ.get("INSTAGRAM_USERNAME", "really_innocent_.nawab").lower()
                    
                    if sender_id and message_text and not messaging.get("message", {}).get("is_echo"):
                        
                        # चेक करें कि क्या यह ग्रुप चैट का मैसेज है (अगर मैसेज में @username है)
                        is_mention = f"@{bot_username}" in message_text.lower()
                        
                        # अगर मैसेज में @username है, तो उसे हटा दें ताकि AI कन्फ्यूज़ न हो
                        if is_mention:
                             message_text = re.sub(rf'@{bot_username}', '', message_text, flags=re.IGNORECASE).strip()
                        
                        # Mark Seen
                        mark_message_seen(str(sender_id))
                        time.sleep(0.5)
                        
                        update_memory(str(sender_id), message_text)
                        
                        async def fetch_and_reply():
                            raw_ai_reply = await get_ai_response(str(sender_id), message_text)
                            cleaned = clean_text_for_speech(raw_ai_reply)
                            ai_reply = humanize_text(cleaned)
                            
                            if "voice" in message_text.lower() or "audio" in message_text.lower():
                                try:
                                    audio = eleven_client.text_to_speech.convert(
                                        text=ai_reply, 
                                        voice_id=VOICE_ID, 
                                        model_id="eleven_multilingual_v2"
                                    )
                                    mp3_path = "/tmp/r_insta.mp3"
                                    m4a_path = "/tmp/r_insta.m4a"
                                    with open(mp3_path, "wb") as f:
                                        for chunk in audio: f.write(chunk)
                                    subprocess.run(["ffmpeg", "-y", "-i", mp3_path, "-c:a", "aac", m4a_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                    send_instagram_voice(sender_id, m4a_path)
                                    return
                                except Exception as ex:
                                    logging.error(f"Insta Voice Gen Error: {ex}")
                                    
                            # ग्रुप चैट के लिए रिप्लाई (API अपने आप sender_id के आधार पर थ्रेड को पहचान लेती है)
                            send_instagram_reply(sender_id, ai_reply, is_group=is_mention)
                        
                        threading.Thread(target=lambda: asyncio.run(fetch_and_reply()), daemon=True).start()
    except Exception as e:
        logging.error(f"Error processing webhook event: {e}")
        
    return "EVENT_RECEIVED", 200

def run_flask(): 
    try: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
    except Exception as e: logging.error(f"Flask Server Error: {e}")

load_dotenv()
groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
eleven_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
VOICE_ID = os.environ.get("ELEVEN_LABS_VOICE_ID")
RENDER_SERVER_URL = "https://my-youtube-api-1uf5.onrender.com"

# --- MEMORY ENGINE ---
def init_db():
    conn = sqlite3.connect('/tmp/fenix.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS memory (user_id TEXT PRIMARY KEY, count INTEGER, context TEXT)''')
    conn.commit(); conn.close()

def get_data(user_id):
    try:
        conn = sqlite3.connect('/tmp/fenix.db')
        c = conn.cursor()
        c.execute("SELECT count, context FROM memory WHERE user_id=?", (user_id,))
        row = c.fetchone()
        conn.close()
        return row if row else (0, "")
    except: return (0, "")

def update_memory(user_id, text):
    try:
        count, context = get_data(user_id)
        new_count = count + 1
        new_context = f"{context} {text}"[-2000:] 
        conn = sqlite3.connect('/tmp/fenix.db')
        c = conn.cursor()
        c.execute("REPLACE INTO memory VALUES (?, ?, ?)", (user_id, new_count, new_context))
        conn.commit(); conn.close()
        return new_count
    except: return 0

# --- AUTOMATIC COMMANDS MENU ---
async def post_init(application):
    commands = [BotCommand("search", "यूट्यूब से गाने और वीडियो खोजें 🔍"), BotCommand("voice", "Fenix की आवाज में जवाब सुनें 🎙️")]
    try: await application.bot.set_my_commands(commands)
    except: pass

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: await update.effective_message.reply_text("Baby, connection mein dikkat aayi! ❤️")
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
    except:
        await msg.edit_text("Baby, search mein dikkat aayi! 💔")

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
    except:
        await query.message.edit_text("Baby, link fetch karne mein error aayi! 💔")

async def voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        with open("/tmp/r.mp3", "wb") as f:
            for chunk in audio: f.write(chunk)
        with open("/tmp/r.mp3", "rb") as voice_file:
            await update.message.reply_voice(voice=voice_file)
    except Exception as e:
        await update.message.reply_text("Voice generate nahi ho payi, sorry baby!")

async def get_ai_response(user_id, user_text):
    count, memories = get_data(user_id)
    if count < 50: mode = "Normal, friendly and caring boyfriend"
    elif count < 150: mode = "Charming, sweet and romantic boyfriend"
    else: mode = "Very flirty, playful, romantic and possessive boyfriend"
    
    system_prompt = (
        f"You are Fenix, a human boyfriend chatting on Instagram/WhatsApp. {mode}. Memory: {memories}\n\n"
        "CRITICAL RULES FOR TEXTING:\n"
        "1. Write EXTREMELY short replies like real humans text on chat. Keep it strictly 1 to 2 lines max, or sometimes just 1-2 words (e.g. 'Haan', 'Sahi hai', 'Batao na', 'Okk', 'Pata hai').\n"
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
    time.sleep(delay)
    raw_reply = await get_ai_response(user_id, update.message.text)
    cleaned = clean_text_for_speech(raw_reply)
    reply = humanize_text(cleaned)
    await update.message.reply_text(reply)

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    app_bot = ApplicationBuilder().token(os.environ.get("TELEGRAM_TOKEN")).post_init(post_init).build()
    app_bot.add_handler(CommandHandler("search", search_youtube)) 
    app_bot.add_handler(CommandHandler("voice", voice_command))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app_bot.add_handler(CallbackQueryHandler(button_callback))
    app_bot.add_error_handler(error_handler)
    print("Fenix is running smoothly with Group Chat Mention Support!")
    app_bot.run_polling()
                       
