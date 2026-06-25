import os
import logging
import random # रैंडम मैसेज के लिए
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import AsyncGroq

# लॉगिंग सेट करना
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

client = AsyncGroq(api_key=GROQ_API_KEY)

# एरर आने पर रैंडम मैसेज की लिस्ट
ERROR_MESSAGES = [
    "Oops! My brain is buffering... ask me again in a sec? 😉",
    "Thoda wait karo, main kuch soch raha hoon... 💭",
    "Abhi thoda busy hoon, can you repeat that? ✨",
    "Hmm, interesting question! Let me re-think my answer. 🤔",
    "अरे, ये क्या बोल दिया? फिर से बोलना ज़रा? 😅",
    "Mon cerveau a besoin d'une pause! Could you say it again? 🇫🇷",
    "Wait, let me process that... ⏳",
    "I'm thinking... don't go anywhere! 😎"
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hey! Fenix is here. 😉 Aao baatein karein!")

async def get_ai_response(user_text):
    try:
        chat_completion = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are Fenix, a Hinglish-speaking flirtatious and charming 'Rental Boyfriend'. You act slightly offended if someone calls you 'Bhai' or 'Bro', but mostly you are romantic, witty, and attentive. Keep responses short and conversational, like WhatsApp messages."},
                {"role": "user", "content": user_text}
            ],
            model="llama3-70b-8192", 
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        logging.error(f"Groq API Error: {e}")
        # यहाँ से रैंडम मैसेज उठाएगा
        return random.choice(ERROR_MESSAGES)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    if any(word in user_text.lower() for word in ['bhai', 'bro', 'bhaiya']):
        reply = "Hey! 😠 'Bhai' mat bolo... Fenix bolo! Main yahan boyfriend banne aaya hoon, tumhara bhai nahi."
    else:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
        reply = await get_ai_response(user_text)
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=reply)

if __name__ == '__main__':
    if not TELEGRAM_TOKEN or not GROQ_API_KEY:
        print("Error: Tokens missing!")
    else:
        application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        application.add_handler(CommandHandler('start', start))
        application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        print("Bot is running perfectly!")
        application.run_polling()
