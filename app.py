import os, logging, sqlite3, asyncio, requests, yt_dlp, threading, traceback
from flask import Flask
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
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

# 📡 आपका रेंडर यूट्यूब सर्वर URL
RENDER_SERVER_URL = "https://my-youtube-api-1uf5.onrender.com"

# --- MEMORY ENGINE ---
def init_db():
    conn = sqlite3.connect('/tmp/fenix.db')
    c = conn.cursor()
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

# --- AUTOMATIC COMMANDS MENU ---
async def set_bot_menu(application):
    """टेलीग्राम के चैट बॉक्स मेनू में कमांड्स सेट करने के लिए"""
    commands = [
        BotCommand("search", "यूट्यूब से टॉप 10 न्यू वीडियो खोजें 🔍"),
        BotCommand("music", "SoundCloud से गाने खोजें 🎵"),
        BotCommand("voice", "Fenix की आवाज में जवाब सुनें 🎙️")
    ]
    await application.bot.set_my_commands(commands)

# --- ERROR HANDLER ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Error occurred: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("Baby, connection mein thodi dikkat aayi, main abhi theek ho raha hoon! ❤️")

# --- 🔍 NEW YOUTUBE SEARCH FEATURE ---
async def search_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Baby, kis gane ya video ko dhoondna hai? `/search [naam]`")
        return
        
    msg = await update.message.reply_text("🔍 YouTube par sabse naye results dhoond raha hoon, thoda wait karo baby... ❤️")
    
    try:
        # आपके रेंडर सर्वर से टॉप 10 न्यू वीडियोज़ की लिस्ट मंगाना
        response = requests.get(f"{RENDER_SERVER_URL}/search?query={query}", timeout=25)
        if response.status_code != 200:
            await msg.edit_text("Baby, server respond nahi kar raha. Phir se try karo! 💔")
            return
            
        data = response.json()
        if data.get("status") != "success" or not data.get("results"):
            await msg.edit_text("Baby, YouTube par is naam se kuch nahi mila! 💔")
            return
            
        text = f"🚀 *YouTube Search Results (Latest First):*\n`{query}`\n\n"
        keyboard = []
        
        # टॉप 10 रिज़ल्ट्स को प्रोसेस करना
        for index, video in enumerate(data["results"][:10], start=1):
            title = video.get("title", "Unknown Title")
            duration_sec = video.get("duration", 0)
            duration = f"{duration_sec // 60}:{duration_sec % 60:02d}" if duration_sec else "0:00"
            video_id = video.get("video_id")
            
            text += f"{index}. *{title[:50]}* [{duration}]\n\n"
            # बटन के callback_data में 'yt_' प्रिफिक्स लगाया है ताकी डाउनलोडर पहचान सके
            keyboard.append([InlineKeyboardButton(f"🎬 {index}. Audio/Video Download", callback_data=f"yt_{video_id}")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.edit_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logging.error(f"YouTube Search Endpoint Error: {e}")
        await msg.edit_text("Baby, YouTube search mein dikkat aayi, thodi der baad try karo! 💔")

# --- SOUNDCLOUD FEATURES ---
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

# --- SMART CALLBACK BUTTON HANDLER ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # 🎬 यूट्यूब डाउनलोडर लॉजिक (रेंडर के /fetch एंडपॉइंट से)
    if data.startswith("yt_"):
        video_id = data.split("_")[1]
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        
        try:
            await query.message.edit_text("📥 Baby, aapki link process ho rahi hai... Just a moment! 🥰")
        except: pass
            
        try:
            # आपके रेंडर सर्वर के /fetch एंडपॉइंट को कॉल करके डायरेक्ट लिंक मंगाना
            response = requests.get(f"{RENDER_SERVER_URL}/fetch?url={video_url}", timeout=30)
            if response.status_code == 200:
                fetch_data = response.json()
                if fetch_data.get("status") == "success" and fetch_data.get("download_url"):
                    d_url = fetch_data.get("download_url")
                    title = fetch_data.get("title", "Video")
                    
                    # यूजर को डायरेक्ट डाउनलोड लिंक वाला एक सुंदर बटन देना
                    dl_keyboard = [[InlineKeyboardButton("🚀 Click Here to Download", url=d_url)]]
                    markup = InlineKeyboardMarkup(dl_keyboard)
                    
                    await query.message.edit_text(
                        f"✅ *Baby, aapka download link taiyar hai!*\n\n🎵 *Title:* {title}\n\nNeeche diye gaye button par click karke direct download karlo! 👇",
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    return
            await query.message.edit_text("Baby, link fetch karne mein dikkat aayi! Phir se try karo. 💔")
        except Exception as e:
            logging.error(f"YT Button Click Error: {e}")
            await query.message.edit_text("Baby, download link nikalne mein thodi dikkat hui! 💔")

    # 🎵 साउंडक्लाउड डाउनलोडर लॉजिक (पुराना कोड)
    elif data.startswith("sc_"):
        track_id = data.split("_")[1]
        try:
            await query.message.edit_text("📥 Baby, SoundCloud se gaana download ho raha hai... Just a moment! 🥰")
        except: pass
            
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
    
    # ⚙️ टेलीग्राम मेनू को सेट करना (Asynchronous तरीके से लूप में चलाना)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(set_bot_menu(app_bot))
    
    # Handlers
    app_bot.add_handler(CommandHandler("search", search_youtube)) # नया यूट्यूब सर्च हैंडलर
    app_bot.add_handler(CommandHandler("music", play_music))
    app_bot.add_handler(CommandHandler("voice", voice_command))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # CallbackQueryHandler for Inline Buttons (SoundCloud + YouTube)
    app_bot.add_handler(CallbackQueryHandler(button_callback))
    
    # Error Handler
    app_bot.add_error_handler(error_handler)
    
    print("Fenix is running with YouTube Engine!")
    app_bot.run_polling()
