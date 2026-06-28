import os, logging, sqlite3, asyncio, threading
from flask import Flask
from dotenv import load_dotenv
from pyrogram import Client, filters
from groq import AsyncGroq
from elevenlabs.client import ElevenLabs

# --- CONFIG ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
@app.route('/')
def home(): return "Fenix is Alive!"
def run_flask(): app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# Clients
bot = Client("fenix", api_id=os.environ["API_ID"], api_hash=os.environ["API_HASH"], bot_token=os.environ["TELEGRAM_TOKEN"])
groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
eleven_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
VOICE_ID = os.environ.get("ELEVEN_LABS_VOICE_ID")

# --- DATABASE & AI ---
def init_db():
    conn = sqlite3.connect('/tmp/fenix.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS memory (user_id TEXT PRIMARY KEY, count INTEGER, context TEXT)''')
    conn.commit(); conn.close()

def get_ai_response(user_id, user_text):
    # (वही तुम्हारा पुराना लॉजिक)
    return "Fenix response..." # यहाँ तुम्हारा पुराना AI logic डालना 

# --- HANDLERS ---
@bot.on_message(filters.command("music"))
async def play_music(client, message):
    query = " ".join(message.command[1:])
    if not query: return await message.reply("Baby, gaane ka naam batao! `/music [name]`")
    
    msg = await message.reply("🔎 Dhoond raha hoon baby...")
    await client.send_message("allsaverbot", query)
    await asyncio.sleep(8)
    
    async for m in client.get_chat_history("allsaverbot", limit=1):
        if m.audio or m.video:
            await client.copy_message(message.chat.id, "allsaverbot", m.id)
            await msg.delete()
        else: await msg.edit("Baby, gaana nahi mila! ❤️")

@bot.on_message(filters.command("voice"))
async def voice_handler(client, message):
    # (यहाँ तुम्हारा पुराना Voice logic लगाओ)
    await message.reply("Voice feature active!")

@bot.on_message(filters.text & ~filters.command(["music", "voice"]))
async def chat_handler(client, message):
    # (यहाँ तुम्हारा पुराना handle_message logic लगाओ)
    await message.reply("Fenix is thinking...")

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask).start()
    bot.run()
