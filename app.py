# सबसे पहले इवेंट लूप सेट करना जरूरी है (Pyrogram के लिए)
import asyncio
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

import os, logging, sqlite3, threading, requests
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
    
    try:
        # JioSaavn Public API से गाना सर्च करना
        search_url = f"https://saavn.dev/api/search/songs?query={query}"
        response = requests.get(search_url).json()
        
        if not response.get('success') or not response['data']['results']:
            return await msg.edit("Baby, gaana nahi mila, naam sahi likho! 💔")
            
        song_data = response['data']['results'][0]
        song_name = song_data['name']
        artist_name = song_data['artists']['primary'][0]['name'] if song_data['artists']['primary'] else "Fenix"
        
        # बेस्ट क्वालिटी ऑडियो URL निकालना (320kbps या 192kbps)
        download_url = song_data['downloadUrl'][-1]['url'] 
        
        file_path = f"/tmp/{song_data['id']}.mp3"
        
        # गाना डाउनलोड करना
        audio_data = requests.get(download_url).content
        with open(file_path, 'wb') as f:
            f.write(audio_data)
            
        # टेलीग्राम पर भेजना
        await client.send_audio(
            chat_id=message.chat.id, 
            audio=file_path, 
            title=song_name, 
            performer=artist_name
        )
        await msg.delete()
        if os.path.exists(file_path):
            os.remove(file_path)
            
    except Exception as e:
        print(f"Error: {e}")
        await msg.edit("Baby, gaana download karne mein thodi dikkat hui, phir se try karo! 💔")

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
