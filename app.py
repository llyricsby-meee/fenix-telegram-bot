import os
import logging
import random
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import AsyncGroq

# लॉगिंग सेट करना
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

client = AsyncGroq(api_key=GROQ_API_KEY)

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
        # यहाँ AI को जेंडर और बर्ताव का लॉजिक सिखाया गया है
        chat_completion = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are Fenix, a Hinglish-speaking 'Rental Boyfriend'. Detect the user's gender/vibe from the conversation. If it's a guy, keep it cool, witty, and bro-like if they use slang, but flirtatious and charming if they are talking to a lady. If someone calls you 'Bhai' or 'Bro', get playfully offended. Keep messages short and conversational."},
                {"role": "user", "content": user_text}
            ],
            model="llama-3.3-70b-versatile", 
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        logging.error(f"Groq API Error: {e}")
        return random.choice(ERROR_MESSAGES)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    # Anti-Brotherzone लॉजिक अब और एडवांस है
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
        print("Bot is running with Advanced Fenix AI!")
        application.run_polling()


