import os
import logging
import random
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import AsyncGroq
from gtts import gTTS

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

client = AsyncGroq(api_key=GROQ_API_KEY)

async def get_ai_response(user_text):
    try:
        chat_completion = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are Fenix, a cool Gen-Z human on WhatsApp. Use Hinglish, keep it casual, lowercase, no spelling mistakes. If someone calls you 'Bhai' or 'Bro', act playfully offended. You can send text or, if asked, send a voice message."},
                {"role": "user", "content": user_text}
            ],
            model="llama-3.3-70b-versatile", 
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return "Oops! Mera dimag thoda ghoom gaya... Ek baar aur bologe? 😅"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    # 1. टाइपिंग इंडिकेटर (5 सेकंड का लॉन्ग फील)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    await asyncio.sleep(3) # थोड़ा और रियलिस्टिक बनाने के लिए
    
    # 2. रिप्लाई लॉजिक
    if any(word in user_text.lower() for word in ['bhai', 'bro', 'bhaiya']):
        reply = "Hey! 😠 'Bhai' mat bolo... Fenix bolo! Main yahan boyfriend banne aaya hoon, tumhara bhai nahi."
    else:
        reply = await get_ai_response(user_text)
    
    # 3. टेक्स्ट सेंड करना
    await context.bot.send_message(chat_id=update.effective_chat.id, text=reply)
    
    # 4. वॉयस डिमांड चेक करना
    if "voice" in user_text.lower() or "audio" in user_text.lower():
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='record_voice')
        tts = gTTS(text=reply, lang='hi')
        tts.save("reply.mp3")
        await context.bot.send_voice(chat_id=update.effective_chat.id, voice=open("reply.mp3", 'rb'))
        os.remove("reply.mp3")

if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', lambda u, c: u.message.reply_text("Hey! Send me a message or ask for 'voice'! 😉")))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.run_polling()



