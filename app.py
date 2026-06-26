import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from groq import AsyncGroq
from elevenlabs.client import ElevenLabs

# .env फाइल लोड करें
load_dotenv()

# Logging setup
logging.basicConfig(level=logging.INFO)

# API Setup
groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
eleven_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))

# एनवायरमेंट वेरिएबल से Voice ID उठाएं
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
    wants_voice = "voice" in user_text or "audio" in user_text
    
    # Typing indicator start
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    
    # 'Bhai/Bro' Filter
    if any(word in user_text.split() for word in ['bhai', 'bro', 'bhaiya']):
        reply = "Hey! 😠 Fenix bolo, bhai nahi. Main tumhara boyfriend hoon!"
    else:
        reply = await get_ai_response(update.message.text)
    
    if wants_voice:
        try:
            # Voice recording indicator
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='record_voice')
            
            # ElevenLabs: अब VOICE_ID वेरिएबल का इस्तेमाल होगा
            audio_stream = eleven_client.text_to_speech.convert(
                text=reply,
                voice_id=VOICE_ID, 
                model_id="eleven_multilingual_v2"
            )
            
            with open("reply.mp3", "wb") as f:
                for chunk in audio_stream:
                    f.write(chunk)
            
            await context.bot.send_voice(chat_id=update.effective_chat.id, voice=open("reply.mp3", 'rb'))
            if os.path.exists("reply.mp3"): os.remove("reply.mp3")
            
        except Exception as e:
            logging.error(f"Voice Error: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"{reply} \n(Voice mein chhota sa glitch aaya, par I love you! ❤️)")
    else:
        # Normal text reply
        await context.bot.send_message(chat_id=update.effective_chat.id, text=reply)

if __name__ == '__main__':
    # Token check
    token = os.environ.get("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(token).build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.run_polling()
