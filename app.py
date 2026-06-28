import os
import logging
import threading
import sqlite3
import asyncio
import yt_dlp
from flask import Flask
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from groq import AsyncGroq
from elevenlabs.client import ElevenLabs

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

# --- MUSIC FEATURE START ---
async def play_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Baby, gaane ka naam toh batao! `/music [song name]`")
        return

    await update.message.reply_text(f"🔍 '{query}' dhoond rahi hoon, zara ruko...")
    
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'outtmpl': 'song.mp3'
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=True)
            # yt-dlp file ko 'song.mp3' ke naam se save karega
            
        await update.message.reply_audio(audio=open("song.mp3", 'rb'), title=info['entries'][0]['title'])
        os.remove("song.mp3")
    except Exception as e:
        logging.error(f"Music Error: {e}")
        await update.message.reply_text("Baby, गाना ढूँढने में थोड़ी दिक्कत हो गई। फिर से ट्राई करो!")
# --- MUSIC FEATURE END ---

# [बाकी कोड जो आपने दिया था - यहाँ वैसे ही रहेगा]
def init_db():
    conn = sqlite3.connect('fenix_memory.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS memory (user_id TEXT, context TEXT)''')
    conn.commit()
    conn.close()

def save_memory(user_id, context):
    conn = sqlite3.connect('fenix_memory.db')
    c = conn.cursor()
    c.execute("INSERT INTO memory VALUES (?, ?)", (user_id, context))
    conn.commit()
    conn.close()

def get_memory(user_id):
    conn = sqlite3.connect('fenix_memory.db')
    c = conn.cursor()
    c.execute("SELECT context FROM memory WHERE user_id=?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return "\n".join([row[0] for row in rows[-50:]])

async def get_ai_response(user_id, user_text):
    memories = get_memory(user_id)
    try:
        response = await groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": f"You are Fenix/Anshika, a charming partner. Remember: {memories}. Keep it short, romantic, witty in Hinglish."},
                {"role": "user", "content": user_text}
            ],
            model="llama-3.3-70b-versatile",
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Groq API Error: {e}")
        return "Baby, main zara thoda busy hoon. Ek minute ruk jao, wapas aata hoon! ❤️"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    user_text = update.message.text
    save_memory(user_id, user_text)
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    await asyncio.sleep(2)
    
    reply = await get_ai_response(user_id, user_text)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=reply)
    
    # ... (बाकी voice वाला हिस्सा वैसे ही रखें जैसा था)

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask).start()
    token = os.environ.get("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(token).build()
    
    # Music Command Add kar diya hai
    application.add_handler(CommandHandler("music", play_music))
    
    application.add_handler(CommandHandler("hello", handle_message))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.run_polling()
