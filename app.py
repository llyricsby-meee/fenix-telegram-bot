import os
import logging
import threading
import sqlite3
import asyncio
import requests
import yt_dlp
from flask import Flask
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from groq import AsyncGroq
from elevenlabs.client import ElevenLabs

# --- CONFIG ---
GENERATOR_URL = "https://link-generator-af3a.onrender.com"

# Flask Web Server
app = Flask(__name__)
@app.route('/')
def home(): return "Fenix is Alive!"
def run_flask(): app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# API Setup
load_dotenv()
logging.basicConfig(level=logging.INFO)
groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
eleven_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
VOICE_ID = os.environ.get("ELEVEN_LABS_VOICE_ID")

# Database setup
def init_db():
    conn = sqlite3.connect('/tmp/fenix_memory.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS memory (user_id TEXT, context TEXT)''')
    conn.commit()
    conn.close()

def save_memory(user_id, context):
    conn = sqlite3.connect('/tmp/fenix_memory.db')
    c = conn.cursor()
    c.execute("INSERT INTO memory VALUES (?, ?)", (user_id, context))
    conn.commit()
    conn.close()

def get_memory(user_id):
    conn = sqlite3.connect('/tmp/fenix_memory.db')
    c = conn.cursor()
    c.execute("SELECT context FROM memory WHERE user_id=?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return "\n".join([row[0] for row in rows[-50:]])

# Music Feature (NEW: Linked to your Generator)
async def play_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Baby, gaane ka naam toh batao! `/music [song name]`")
        return

    status_msg = await update.message.reply_text("🔗 Link generate ho raha hai...")
    
    try:
        # 1. Generator से लिंक मांगो
        resp = requests.get(f"{GENERATOR_URL}/generate", params={'q': query}).json()
        youtube_url = resp['link']
        
        status_msg.edit_text("📥 Download ho raha hai...")
        
        # 2. Link को डाउनलोड करो
        ydl_opts = {'format': 'bestaudio/best', 'outtmpl': '/tmp/song.mp3', 'noplaylist': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
        
        await update.message.reply_audio(audio=open("/tmp/song.mp3", 'rb'), title=query)
        if os.path.exists("/tmp/song.mp3"): os.remove("/tmp/song.mp3")
        await status_msg.delete()
        
    except Exception as e:
        logging.error(f"Music Error: {e}")
        await update.message.reply_text("Baby, gaana nahi mila ya service busy hai!")
        if 'status_msg' in locals(): await status_msg.delete()

# AI Response (Same as before)
async def get_ai_response(user_id, user_text):
    memories = get_memory(user_id)
    try:
        response = await groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": f"You are Fenix, a charming boyfriend. Remember: {memories}. Keep it short, romantic, witty in Hinglish."},
                {"role": "user", "content": user_text}
            ],
            model="llama-3.3-70b-versatile",
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Groq API Error: {e}")
        return "Baby, main zara thoda busy hoon. Ek minute ruk jao! ❤️"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # (बाकी का कोड सेम है, इसे न बदलें)
    user_id = str(update.effective_chat.id)
    user_text = update.message.text
    save_memory(user_id, user_text)
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    await asyncio.sleep(2)
    reply = await get_ai_response(user_id, user_text)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=reply)
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='record_voice')
    try:
        audio_stream = eleven_client.text_to_speech.convert(
            text=reply, voice_id=VOICE_ID, model_id="eleven_multilingual_v2"
        )
        with open("/tmp/reply.mp3", "wb") as f:
            for chunk in audio_stream:
                f.write(chunk)
        await asyncio.sleep(2)
        await context.bot.send_voice(chat_id=update.effective_chat.id, voice=open("/tmp/reply.mp3", "rb"))
    except Exception as e:
        logging.error(f"Voice Error: {e}")

async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("hello", "Start conversation"),
        BotCommand("music", "Play music"),
        BotCommand("voice", "Get voice reply")
    ])

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask).start()
    token = os.environ.get("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(token).post_init(post_init).build()
    
    application.add_handler(CommandHandler("music", play_music))
    application.add_handler(CommandHandler("hello", handle_message))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    application.run_polling()
