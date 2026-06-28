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

# --- DATABASE & MEMORY ---
def init_db():
    conn = sqlite3.connect('/tmp/fenix_memory.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS memory (user_id TEXT, message_count INTEGER, context TEXT)''')
    conn.commit()
    conn.close()

def get_user_data(user_id):
    conn = sqlite3.connect('/tmp/fenix_memory.db')
    c = conn.cursor()
    c.execute("SELECT message_count, context FROM memory WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row if row else (0, "")

def update_memory(user_id, text):
    count, context = get_user_data(user_id)
    new_count = count + 1
    new_context = f"{context} {text}"[-2000:] # Keep last 2000 chars
    conn = sqlite3.connect('/tmp/fenix_memory.db')
    c = conn.cursor()
    c.execute("REPLACE INTO memory VALUES (?, ?, ?)", (user_id, new_count, new_context))
    conn.commit()
    conn.close()
    return new_count

# --- MUSIC FEATURE ---
async def play_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Baby, gaane ka naam toh batao! `/music [song name]`")
        return

    status_msg = await update.message.reply_text("🔍 Dhoond rahi hoon...")
    try:
        resp = requests.get(f"{GENERATOR_URL}/generate", params={'q': query}).json()
        youtube_url = resp['link']
        status_msg.edit_text("📥 Download ho raha hai...")
        
        ydl_opts = {'format': 'bestaudio/best', 'outtmpl': '/tmp/song.mp3', 'noplaylist': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([youtube_url])
        
        await update.message.reply_audio(audio=open("/tmp/song.mp3", 'rb'), title=query)
        if os.path.exists("/tmp/song.mp3"): os.remove("/tmp/song.mp3")
        await status_msg.delete()
    except Exception as e:
        await update.message.reply_text("Baby, gaana nahi mila ya service busy hai!")

# --- AI RESPONSE (WITH EMOTIONAL PROGRESSION) ---
async def get_ai_response(user_id, user_text):
    count, memories = get_user_data(user_id)
    
    # Emotional Progression logic
    if count < 50: mode = "normal and friendly"
    elif count < 150: mode = "charming and sweet"
    else: mode = "flirty, playful and romantic"
    
    try:
        response = await groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": f"You are Fenix/Anshika. Be {mode}. Context: {memories}"},
                {"role": "user", "content": user_text}
            ],
            model="llama-3.3-70b-versatile",
        )
        return response.choices[0].message.content
    except:
        return "Baby, main zara thoda busy hoon. Ek minute ruk jao! ❤️"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    new_count = update_memory(user_id, update.message.text)
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    await asyncio.sleep(1.5) # Natural delay
    reply = await get_ai_response(user_id, update.message.text)
    await update.message.reply_text(reply)
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='record_voice')
    try:
        audio_stream = eleven_client.text_to_speech.convert(text=reply, voice_id=VOICE_ID, model_id="eleven_multilingual_v2")
        with open("/tmp/reply.mp3", "wb") as f:
            for chunk in audio_stream: f.write(chunk)
        await context.bot.send_voice(chat_id=update.effective_chat.id, voice=open("/tmp/reply.mp3", "rb"))
    except: pass

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask).start()
    token = os.environ.get("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(token).build()
    
    application.add_handler(CommandHandler("music", play_music))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.run_polling()
