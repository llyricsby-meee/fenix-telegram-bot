import os, logging, sqlite3, asyncio, requests, yt_dlp, threading, traceback
from flask import Flask
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from groq import AsyncGroq
from elevenlabs.client import ElevenLabs

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- CONFIG ---
GENERATOR_URL = "https://link-generator-l5eg.vercel.app"
app = Flask(__name__)
@app.route('/')
def home(): return "Fenix is Alive!"
def run_flask(): app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))


load_dotenv()
groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
eleven_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
VOICE_ID = os.environ.get("ELEVEN_LABS_VOICE_ID")

# --- MEMORY ENGINE ---
def init_db():
    conn = sqlite3.connect('/tmp/fenix.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS memory 
                 (user_id TEXT PRIMARY KEY, count INTEGER, context TEXT, leaving_status INTEGER DEFAULT 0)''')
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
        c.execute("INSERT OR REPLACE INTO memory (user_id, count, context, leaving_status) VALUES (?, ?, ?, 0)", 
                  (user_id, new_count, new_context))
        conn.commit(); conn.close()
        return new_count
    except: return 0

# --- HANDLERS ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Error occurred: {context.error}")
    if update and update.effective_message:
        user_id = str(update.effective_chat.id)
        conn = sqlite3.connect('/tmp/fenix.db')
        c = conn.cursor()
        c.execute("UPDATE memory SET leaving_status = 1 WHERE user_id = ?", (user_id,))
        conn.commit(); conn.close()
        await update.effective_message.reply_text("Baby, connection mein thodi dikkat aayi, main abhi theek ho raha hoon! ❤️")

async def post_init(application: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('/tmp/fenix.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM memory WHERE leaving_status = 1")
    users = c.fetchall()
    for user in users:
        try:
            await application.bot.send_message(chat_id=user[0], text="✨ Fenix wapas aa gaya hai, main ab phir se aapke saath hoon! ❤️")
            c.execute("UPDATE memory SET leaving_status = 0 WHERE user_id = ?", (user[0],))
        except: continue
    conn.commit(); conn.close()

# --- FEATURES ---
async def play_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = " ".join(context.args)
        if not query:
            await update.message.reply_text("Baby, gaane ka naam toh batao! `/music [song name]`")
            return
        msg = await update.message.reply_text("🔍 Dhoond raha hoon...")
        resp = requests.get(f"{GENERATOR_URL}/generate", params={'q': query}, timeout=30).json()
        url = resp['link']
        msg.edit_text("📥 Download ho raha hai...")
        ydl_opts = {'format': 'bestaudio/best', 'outtmpl': '/tmp/song.mp3'}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([url])
        await update.message.reply_audio(audio=open("/tmp/song.mp3", 'rb'), title=query)
        await msg.delete()
    except Exception as e:
        logging.error(f"Music Error: {e}")
        await update.message.reply_text("Baby, gaana nahi mil raha, service busy hai!")

async def voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_text = " ".join(context.args)
        if not user_text:
            await update.message.reply_text("Baby, kuch toh bolo! `/voice [tumhara sawal]`")
            return
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='record_voice')
        reply = await get_ai_response(str(update.effective_chat.id), user_text)
        audio = eleven_client.text_to_speech.convert(text=reply, voice_id=VOICE_ID, model_id="eleven_multilingual_v2")
        with open("/tmp/r.mp3", "wb") as f:
            for chunk in audio: f.write(chunk)
        await update.message.reply_voice(voice=open("/tmp/r.mp3", "rb"))
    except Exception as e:
        logging.error(f"Voice Error: {e}")
        await update.message.reply_text("Voice generate nahi ho payi, sorry baby!")

async def get_ai_response(user_id, user_text):
    count, memories = get_data(user_id)
    if count < 50: mode = "Normal, friendly and caring male boyfriend"
    elif count < 150: mode = "Charming, sweet and romantic male boyfriend"
    else: mode = "Very flirty, playful, romantic and possessive male boyfriend"
    
    response = await groq_client.chat.completions.create(
        messages=[
            {"role": "system", "content": f"You are Fenix, a charming male boyfriend. {mode}. Memory: {memories}"},
            {"role": "user", "content": user_text}
        ],
        model="llama-3.3-70b-versatile",
    )
    return response.choices[0].message.content

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    update_memory(user_id, update.message.text)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    await asyncio.sleep(1.5)
    reply = await get_ai_response(user_id, update.message.text)
    await update.message.reply_text(reply)

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask).start()
    app_bot = ApplicationBuilder().token(os.environ.get("TELEGRAM_TOKEN")).post_init(post_init).build()
    
    app_bot.add_handler(CommandHandler("music", play_music))
    app_bot.add_handler(CommandHandler("voice", voice_command))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app_bot.add_error_handler(error_handler)
    
    app_bot.run_polling()
