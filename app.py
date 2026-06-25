import os
import logging
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from groq import AsyncGroq
import edge_tts

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

client = AsyncGroq(api_key=GROQ_API_KEY)

async def get_ai_response(user_text):
    chat_completion = await client.chat.completions.create(
        messages=[
            {"role": "system", "content": "You are Fenix, a charming 'Rental Boyfriend'. Speak cool Hinglish. React to 'bhai'/'bro' only if explicitly called that. Be romantic and witty."},
            {"role": "user", "content": user_text}
        ],
        model="llama-3.3-70b-versatile",
    )
    return chat_completion.choices[0].message.content

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    await asyncio.sleep(5) 
    
    if any(word in user_text.lower().split() for word in ['bhai', 'bro', 'bhaiya']):
        reply = "Hey! 😠 'Bhai' mat bolo... Fenix bolo! Main yahan boyfriend banne aaya hoon."
    else:
        reply = await get_ai_response(user_text)
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=reply)
    
    # Edge TTS से मेल वॉयस
    if "voice" in user_text.lower() or "audio" in user_text.lower():
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='record_voice')
        # 'hi-IN-PrabhatNeural' एक बहुत अच्छी मेल आवाज़ है
        communicate = edge_tts.Communicate(reply, "hi-IN-PrabhatNeural")
        await communicate.save("reply.mp3")
        await context.bot.send_voice(chat_id=update.effective_chat.id, voice=open("reply.mp3", 'rb'))
        os.remove("reply.mp3")

if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.run_polling()





