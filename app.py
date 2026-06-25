import os
import logging
import random
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import AsyncGroq
from gtts import gTTS

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

client = AsyncGroq(api_key=GROQ_API_KEY)

async def get_ai_response(user_text):
    try:
        # Prompt ko aur clear kar diya hai taaki woh confusion na ho
        chat_completion = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are Fenix, a charming and witty 'Rental Boyfriend'. Your personality is flirtatious, romantic, and cool. IMPORTANT: Only react if the user explicitly calls you 'bhai', 'bro', or 'bhaiya'. Otherwise, stay in character as a boyfriend. Talk in casual Hinglish, use lowercase, and be natural."},
                {"role": "user", "content": user_text}
            ],
            model="llama-3.3-70b-versatile", 
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return "Oops! Mera dimag thoda ghoom gaya... Ek baar aur bologe? 😅"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    # 5 seconds ka lamba typing indicator
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    await asyncio.sleep(5) 
    
    # Check if user actually said the forbidden words
    if any(word in user_text.lower().split() for word in ['bhai', 'bro', 'bhaiya']):
        reply = "Hey! 😠 'Bhai' mat bolo... Fenix bolo! Main yahan boyfriend banne aaya hoon, tumhara bhai nahi."
    else:
        reply = await get_ai_response(user_text)
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=reply)
    
    # Voice logic
    if "voice" in user_text.lower() or "audio" in user_text.lower():
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='record_voice')
        # tld='com.mx' try karte hain, shayad awaaz thodi mardana aaye
        tts = gTTS(text=reply, lang='hi', tld='com.mx') 
        tts.save("reply.mp3")
        await context.bot.send_voice(chat_id=update.effective_chat.id, voice=open("reply.mp3", 'rb'))
        os.remove("reply.mp3")

if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.run_polling()




