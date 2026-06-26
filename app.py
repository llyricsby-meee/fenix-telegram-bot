import os
import logging
import threading
import sqlite3
from flask import Flask
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from groq import AsyncGroq
from elevenlabs.client import ElevenLabs

# Flask Web Server
app = Flask(__name__)
@app.route('/')
def home(): return "Fenix Bot is Alive!"
def run_flask(): app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# API Setup
load_dotenv()
logging.basicConfig(level=logging.INFO)
groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
eleven_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
VOICE_ID = os.environ.get("ELEVEN_LABS_VOICE_ID")

# Database (Hard Drive) Functions
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
    return [row[0] for row in rows[-5:]]

async def get_ai_response(user_id, user_text):
    memories = "\n".join(get_memory(user_id))
    try:
        response = await groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": f"You are Fenix, a charming boyfriend. Remember these user facts: {memories}. Keep it short, romantic, and witty in Hinglish."},
                {"role": "user", "content": user_text}
            ],
            model="llama-3.3-70b-versatile",
        )
        return response.choices[0].message.content
    except: return "I love you too! ❤️"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    user_text = update.message.text
    
    save_memory(user_id, user_text) # यादें सेव करें
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    
    if user_text.lower() == "/hello":
        reply = "Hey there, beautiful! I'm Fenix. I’ve been waiting for you. Tell me, how was your day?"
    else:
        reply = await get_ai_response(user_id, user_text)
        
    await context.bot.send_message(chat_id=update.effective_chat.id, text=reply)

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask).start()
    token = os.environ.get("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(token).build()
    application.add_handler(CommandHandler("hello", handle_message))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.run_polling()
