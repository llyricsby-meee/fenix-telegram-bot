import os, logging, sqlite3, asyncio, threading
from flask import Flask
from dotenv import load_dotenv
from pyrogram import Client, filters, idle
from groq import AsyncGroq
from elevenlabs.client import ElevenLabs

# --- CONFIG ---
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
app = Flask(__name__)
@app.route('/')
def home(): return "Fenix is Alive!"
def run_flask(): app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

bot = Client("fenix", api_id=os.environ["API_ID"], api_hash=os.environ["API_HASH"], bot_token=os.environ["TELEGRAM_TOKEN"])
groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
eleven_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
VOICE_ID = os.environ.get("ELEVEN_LABS_VOICE_ID")

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect('/tmp/fenix.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS memory (user_id TEXT PRIMARY KEY, count INTEGER, context TEXT)''')
    conn.commit(); conn.close()

def get_data(user_id):
    conn = sqlite3.connect('/tmp/fenix.db')
    c = conn.cursor()
    c.execute("SELECT count, context FROM memory WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row if row else (0, "")

def update_memory(user_id, text):
    count, context = get_data(user_id)
    new_count = count + 1
    new_context = f"{context} {text}"[-2000:]
    conn = sqlite3.connect('/tmp/fenix.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO memory (user_id, count, context) VALUES (?, ?, ?)", (user_id, new_count, new_context))
    conn.commit(); conn.close()
    return new_count

# --- AI LOGIC ---
async def get_ai_response(user_id, user_text):
    count, memories = get_data(user_id)
    mode = "Normal boyfriend" if count < 50 else "Charming boyfriend"
    response = await groq_client.chat.completions.create(
        messages=[{"role": "system", "content": f"You are Fenix, a boyfriend. {mode}. Memory: {memories}"},
                  {"role": "user", "content": user_text}],
        model="llama-3.3-70b-versatile",
    )
    return response.choices[0].message.content

# --- HANDLERS ---
@bot.on_message(filters.command("music"))
async def play_music(client, message):
    query = " ".join(message.command[1:])
    if not query: return await message.reply("Baby, gaane ka naam batao! `/music [name]`")
    msg = await message.reply("🔎 Gaana dhoond raha hoon, thoda wait karo baby... ❤️")
    await client.send_message("allsaverbot", query)
    await asyncio.sleep(8)
    async for m in client.get_chat_history("allsaverbot", limit=1):
        if m.audio or m.video:
            await client.copy_message(message.chat.id, "allsaverbot", m.id)
            await msg.delete()
        else: await msg.edit("Baby, gaana nahi mila, phir se try karo! ❤️")

@bot.on_message(filters.command("voice"))
async def voice_handler(client, message):
    user_text = " ".join(message.command[1:])
    if not user_text: return await message.reply("Baby, kuch toh bolo! `/voice [sawal]`")
    await bot.send_chat_action(message.chat.id, "record_voice")
    reply = await get_ai_response(str(message.chat.id), user_text)
    audio = eleven_client.text_to_speech.convert(text=reply, voice_id=VOICE_ID, model_id="eleven_multilingual_v2")
    with open("/tmp/r.mp3", "wb") as f:
        for chunk in audio: f.write(chunk)
    await message.reply_voice(voice="/tmp/r.mp3")

@bot.on_message(filters.text & ~filters.command(["music", "voice"]))
async def chat_handler(client, message):
    update_memory(str(message.chat.id), message.text)
    await bot.send_chat_action(message.chat.id, "typing")
    reply = await get_ai_response(str(message.chat.id), message.text)
    await message.reply(reply)

# --- STARTUP ---
if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask).start()
    bot.start()
    print("Fenix is running!")
    idle()
