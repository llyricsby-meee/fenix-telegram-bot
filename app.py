import os
import logging
import threading
from flask import Flask
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from groq import AsyncGroq
from elevenlabs.client import ElevenLabs

# Flask Web Server (Alive रखने के लिए)
app = Flask(__name__)
@app.route('/')
def home():
    return "Fenix Bot is Alive!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# API Setup
load_dotenv()
logging.basicConfig(level=logging.INFO)
groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
eleven_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
VOICE_ID = os.environ.get("ELEVEN_LABS_VOICE_ID")

async def get_ai_response(user_text):
    try:
        response = await groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are Fenix, a charming boyfriend. Keep it short, romantic, and witty in Hinglish."},
                {"role": "user", "content": user_text}
            ],
            model="llama-3.3-70b-versatile",
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Groq Error: {e}")
        return "Main tumhare khayalon mein kho gaya tha, phir se bolo na? 🥰"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text.lower()
    
    # चेक करें कि क्या यूजर ने कमांड दी है या मैसेज लिखा है
    is_command = update.message.text.startswith('/')
    wants_voice = (user_text == "/voice") or ("voice" in user_text)
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    
    # अगर /hello कमांड है तो प्यारा सा स्वागत करें
    if user_text == "/hello":
        reply = "Hey there, beautiful! I'm Fenix. I’ve been waiting for you. Tell me, how was your day?"
    elif any(word in user_text.split() for word in ['bhai', 'bro', 'bhaiya']):
        reply = "Hey! 😠 Fenix bolo, bhai nahi. Main tumhara boyfriend hoon!"
    else:
        reply = await get_ai_response(user_text.replace('/voice', '').strip())
    
    if wants_voice:
        try:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='record_voice')
            audio_stream = eleven_client.text_to_speech.convert(text=reply, voice_id=VOICE_ID, model_id="eleven_multilingual_v2")
            
            with open("reply.mp3", "wb") as f:
                for chunk in audio_stream:
                    f.write(chunk)
            
            await context.bot.send_voice(chat_id=update.effective_chat.id, voice=open("reply.mp3", 'rb'))
            if os.path.exists("reply.mp3"): os.remove("reply.mp3")
        except Exception as e:
            logging.error(f"Voice Error: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"{reply} \n(Voice mein glitch aaya, par I love you! ❤️)")
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=reply)

if __name__ == '__main__':
    threading.Thread(target=run_flask).start()
    
    token = os.environ.get("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(token).build()
    
    # कमांड्स और मैसेज हैंडलर
    application.add_handler(CommandHandler("hello", handle_message))
    application.add_handler(CommandHandler("voice", handle_message))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    application.run_polling()
