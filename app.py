import os
import logging
import threading
import sqlite3
import asyncio
from flask import Flask
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from groq import AsyncGroq
from elevenlabs.client import ElevenLabs

# Flask Setup
app = Flask(__name__)
@app.route('/')
def home(): return "Fenix is online!"
def run_flask(): app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# API & Config
load_dotenv()
logging.basicConfig(level=logging.INFO)
groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
eleven_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
VOICE_ID = os.environ.get("ELEVEN_LABS_VOICE_ID")

# Memory (Hard Drive) Functions
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
    return "\n".join([row[0] for row in rows[-50:]]) # 50 बातों तक की गहरी मेमोरी

async def get_ai_response(user_id, user_text):
    memories = get_memory(user_id)
    try:
        response = await groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": f"You are Fenix, a charming boyfriend. Use these past memories: {memories}. Keep it short, romantic, and witty in Hinglish."},
                {"role": "user", "content": user_text}
            ],
            model="llama-3.3-70b-versatile",
        )
        return response.choices[0].message.content
    except: return "I'm always here for you, baby! ❤️"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    user_text = update.message.text
    save_memory(user_id, user_text)
    
    # 1. टेक्स्ट के लिए 5 सेकंड का असली टाइपिंग डिले
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    await asyncio.sleep(5)
    
    reply = await get_ai_response(user_id, user_text)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=reply)
    
    # 2. वॉयस के लिए अलग से रिकॉर्डिंग डिले (ताकि तुरंत वॉयस न आए)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='record_voice')
    try:
        audio = eleven_client.generate(text=reply, voice=VOICE_ID, model="eleven_multilingual_v2")
        with open("reply.mp3", "wb") as f:
            for chunk in audio: f.write(chunk)
        
        # वॉयस भेजने से पहले 4 सेकंड का पॉज़ (लगेगा कि सच में रिकॉर्ड हो रहा है)
        await asyncio.sleep(4)
        await context.bot.send_voice(chat_id=update.effective_chat.id, voice=open("reply.mp3", "rb"))
    except Exception as e:
        logging.error(f"Voice Error: {e}")

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask).start()
    token = os.environ.get("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(token).build()
    application.add_handler(CommandHandler("hello", handle_message))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.run_polling()
