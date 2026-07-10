import os, logging, sqlite3, asyncio, requests, threading, traceback
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
def run_flask(): 
    try:
        app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
    except Exception as e:
        logging.error(f"Flask Server Error: {e}")

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
async def post_init(application):
    try:
        commands = [
            BotCommand("search", "यूट्यूब से गाने और वीडियो खोजें 🔍"),
            BotCommand("voice", "Fenix की आवाज में जवाब सुनें 🎙️")
        ]
        await application.bot.set_my_commands(commands)
    except Exception as e:
        logging.error(f"Failed to set bot commands menu: {e}")

# --- ERROR HANDLER ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Error occurred: {context.error}")
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text("Baby, connection mein thodi dikkat aayi, main abhi theek ho raha hoon! ❤️")
        except: pass

# --- 🔍 YOUTUBE SEARCH FEATURE ---
async def search_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Baby, kis gane ya video ko dhoondna hai? `/search [naam]`")
        return
        
    msg = await update.message.reply_text("🔍 YouTube par sabse naye results dhoond raha hoon, thoda wait karo baby... ❤️")
    
    try:
        response = requests.get(f"{RENDER_SERVER_URL}/search?query={query}", timeout=45)
        if response.status_code != 200:
            await msg.edit_text("Baby, server respond nahi kar raha. Phir se try karo! 💔")
            return
            
        try:
            data = response.json()
        except:
            await msg.edit_text("Baby, server se sahi response nahi mila. Dobara try karo! 💔")
            return

        if data.get("status") != "success" or not data.get("results"):
            await msg.edit_text("Baby, YouTube par is naam se kuch nahi mila! 💔")
            return
            
        text = f"🚀 *YouTube Search Results (Latest First):*\n`{query}`\n\n"
        keyboard = []
        
        for index, video in enumerate(data["results"][:10], start=1):
            title = video.get("title", "Unknown Title")
            duration_sec = video.get("duration", 0)
            
            if duration_sec:
                try: duration = f"{int(duration_sec) // 60}:{int(duration_sec) % 60:02d}"
                except: duration = "0:00"
            else: duration = "0:00"
                
            video_id = video.get("video_id")
            if not video_id: continue
            
            text += f"{index}. *{title[:50]}* [{duration}]\n\n"
            keyboard.append([InlineKeyboardButton(f"🎬 {index}. Download Link", callback_data=f"yt_{video_id[:40]}")])
            
        final_markup = InlineKeyboardMarkup(keyboard)
        await msg.edit_text(text, reply_markup=final_markup, parse_mode='Markdown')
        
    except Exception as e:
        logging.error(f"YouTube Search Endpoint Error: {e}")
        await msg.edit_text("Baby, YouTube search mein dikkat aayi, thodi der baad try karo! 💔")

# --- SMART CALLBACK BUTTON HANDLER ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except: pass
    
    data = query.data
    if not data: return
    
    if data.startswith("yt_"):
        video_id = data.split("_")[1]
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            await query.message.edit_text("📥 Baby, aapki link process ho rahi hai... Isme thoda samay lag sakta hai, please wait karo! 🥰")
        except: pass
            
        try:
            response = requests.get(f"{RENDER_SERVER_URL}/fetch?url={video_url}", timeout=120)
            
            # ✅ SUCCESS LOGIC
            if response.status_code == 200:
                try:
                    fetch_data = response.json()
                except:
                    await query.message.edit_text("Baby, link format mein dikkat aayi! 💔")
                    return

                if fetch_data.get("status") == "success" and fetch_data.get("download_url"):
                    d_url = fetch_data.get("download_url")
                    title = fetch_data.get("title", "Video")
                    dl_keyboard = [[InlineKeyboardButton("🚀 Click Here to Download", url=d_url)]]
                    dl_markup = InlineKeyboardMarkup(dl_keyboard)
                    
                    await query.message.edit_text(
                        f"✅ *Baby, aapka download link taiyar hai!*\n\n🎵 *Title:* {title}\n\nNeeche diye gaye button par click karke direct download karlo! 👇",
                        reply_markup=dl_markup,
                        parse_mode='Markdown'
                    )
                    return
            
            # 🚨 ERROR CATCHING LOGIC: असली एरर निकालने का नया तरीका
            try:
                err_details = response.json().get("error", "No specific error provided by server.")
            except:
                err_details = f"HTTP Error {response.status_code}"
                
            await query.message.edit_text(f"Baby, download fail ho gaya! 💔\n\n🛠 **Server ka Error:** `{err_details}`")
            
        except Exception as e:
            logging.error(f"YT Button Click Error: {e}")
            await query.message.edit_text("Baby, link fetch karne mein samay lag raha hai, thodi der baad phir se click karo! 💔")

# --- AI AND FEATURES ---
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

async def handle_message(update: Update, update_context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    update_memory(user_id, update.message.text)
    await update_context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    await asyncio.sleep(1.5)
    reply = await get_ai_response(user_id, update.message.text)
    await update.message.reply_text(reply)

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    
    app_bot = ApplicationBuilder().token(os.environ.get("TELEGRAM_TOKEN")).post_init(post_init).build()
    
    app_bot.add_handler(CommandHandler("search", search_youtube)) 
    app_bot.add_handler(CommandHandler("voice", voice_command))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    app_bot.add_handler(CallbackQueryHandler(button_callback))
    app_bot.add_error_handler(error_handler)
    
    print("Fenix is running flawlessly and cleanly!")
    app_bot.run_polling()
