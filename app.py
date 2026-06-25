import os
import logging
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from groq import AsyncGroq
import edge_tts

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

client = AsyncGroq(api_key=GROQ_API_KEY)

async def get_ai_response(user_text):
    try:
        response = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are Fenix, a charming boyfriend. Be cool, use Hinglish. Only send voice if the user explicitly asks for it. Do not send voice automatically. If user says 'voice' or 'audio', then only generate and send voice."},
                {"role": "user", "content": user_text}
            ],
            model="llama-3.3-70b-versatile",
        )
        return response.choices[0].message.content
    except Exception:
        return "I am thinking about you, meri jaan! 🥰"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text.lower()
    
    # 1. Typo-proof trigger check
    wants_voice = "voice" in user_text or "audio" in user_text
    
    # 2. Status update
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    await asyncio.sleep(3)
    
    # 3. Response Generation
    if any(word in user_text.split() for word in ['bhai', 'bro', 'bhaiya']):
        reply = "Hey! 😠 Fenix bolo, bhai nahi. Main tumhara boyfriend hoon!"
    else:
        reply = await get_ai_response(update.message.text)
    
    # 4. Text Reply
    await context.bot.send_message(chat_id=update.effective_chat.id, text=reply)
    
    # 5. Voice Reply (Safe Mode)
    if wants_voice:
        try:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='record_voice')
            communicate = edge_tts.Communicate(reply, "hi-IN-PrabhatNeural")
            await communicate.save("reply.mp3")
            await context.bot.send_voice(chat_id=update.effective_chat.id, voice=open("reply.mp3", 'rb'))
            if os.path.exists("reply.mp3"): os.remove("reply.mp3")
        except Exception as e:
            logging.error(f"Voice Error: {e}")

if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.run_polling()
