import os, logging, sqlite3, asyncio, requests, yt_dlp, threading, traceback
from flask import Flask
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, CallbackQueryHandler, filters
from groq import AsyncGroq
from elevenlabs.client import ElevenLabs

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- CONFIG ---
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
    # FIX: Added PRIMARY KEY to user_id so REPLACE INTO works properly without duplicating
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

# --- ERROR HANDLER ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Error occurred: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("Baby, connection mein thodi dikkat aayi, main abhi theek ho raha hoon! ❤️")

# --- MUSIC FEATURES (SOUNDCLOUD + INLINE BUTTONS) ---
async def play_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Baby, gaane ka naam toh batao! `/music [song name]`")
        return
        
    msg = await update.message.reply_text("🔎 SoundCloud par gaane dhoond raha hoon, thoda wait karo baby... ❤️")
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'default_search': 'scsearch5',
        'quiet': True,
        'nocheckcertificate': True
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            
        if 'entries' not in info or not info['entries']:
            await msg.edit_text("Baby, SoundCloud par ye gaana nahi mila! 💔")
            return
            
        text = f"🎵 *Hasil pencarian untuk:*\n`{query}`\n\n"
        keyboard = []
        
        for index, entry in enumerate(info['entries'][:5], start=1):
            if not entry: continue
            title = entry.get('title', 'Unknown Title')
            duration_sec = entry.get('duration', 0)
            duration = f"{duration_sec // 60}:{duration_sec % 60:02d}" if duration_sec else "0:00"
            uploader = entry.get('uploader', 'SoundCloud Artist')
            track_id = entry.get('id')
            
            text += f"{index}. *{title[:50]}*\n└ 👤 {uploader} [{duration}]\n\n"
            keyboard.append([InlineKeyboardButton(f"🔢 {index}. Download", callback_data=f"sc_{track_id}")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.edit_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logging.error(f"SoundCloud Search Error: {e}")
        await msg.edit_text("Baby, search karne mein thodi dikkat hui, phir se try karo! 💔")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Loading animation stop karne ke liye
    
    data = query.data
    if data.startswith("sc_"):
        track_id = data.split("_")[1]
        
        try:
            await query.message.edit_text("📥 Baby, SoundCloud se gaana download ho raha hai... Just a moment! 🥰")
        except:
            pass
            
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'/tmp/{track_id}.%(ext)s',
            'quiet': True,
            'nocheckcertificate': True
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"scsearch1:id:{track_id}" if not track_id.isdigit() else f"https://api.soundcloud.com/tracks/{track_id}", download=True)
                if 'entries' in info: info = info['entries'][0]
                actual_file = ydl.prepare_filename(info)
                
            with open(actual_file, 'rb') as audio_file:
                await context.bot.send_audio(
                    chat_id=query.message.chat_id,
                    audio=audio_file,
                    title=info.get('title', 'Unknown Title'),
                    performer=info.get('uploader', 'SoundCloud')
                )
                
            await query.message.delete()
            if os.path.exists(actual_file): os.remove(actual_file)
            
        except Exception as e:
            logging.error(f"Download Error: {e}")
            try:
                # Backup Download
                await query.message.edit_text("Baby, gaana direct download nahi hua, backup try kar raha hoon... 🛠️")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f"scsearch1:{track_id}", download=True)
                    if 'entries' in info: info = info['entries'][0]
                    actual_file = ydl.prepare_filename(info)

                with open(actual_file, 'rb') as audio_file:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=audio_file,
                        title=info.get('title', 'Unknown Title'),
                        performer=info.get('uploader', 'SoundCloud')
                    )
                await query.message.delete()
                if os.path.exists(actual_file): os.remove(actual_file)
            except Exception as err:
                logging.error(f"Backup Error: {err}")
                await query.message.edit_text("Baby, download fail ho gaya! Koi dusra option try karo! 💔")

# --- AI AND VOICE FEATURES ---
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
        with open("/tmp/r.mp3", "rb") as voice_file:
            await update.message.reply_voice(voice=voice_file)
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
    app_bot = ApplicationBuilder().token(os.environ.get("TELEGRAM_TOKEN")).build()
    
    # Handlers
    app_bot.add_handler(CommandHandler("music", play_music))
    app_bot.add_handler(CommandHandler("voice", voice_command))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # Added CallbackQueryHandler for the Inline Buttons
    app_bot.add_handler(CallbackQueryHandler(button_callback))
    
    # Error Handler
    app_bot.add_error_handler(error_handler)
    
    print("Fenix is running!")
    app_bot.run_polling()
