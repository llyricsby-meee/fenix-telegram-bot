import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import AsyncGroq

# लॉगिंग सेट करना
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# API Keys एनवायरमेंट वेरिएबल से लेना
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Groq Client सेटअप (Async ताकि बोट फ़ास्ट चले)
client = AsyncGroq(api_key=GROQ_API_KEY)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hey! Fenix is here. 😉 Aao baatein karein!")

# AI से रिप्लाई मंगवाने का फंक्शन
async def get_ai_response(user_text):
    try:
        chat_completion = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are Fenix, a Hinglish-speaking flirtatious and charming 'Rental Boyfriend'. You act slightly offended if someone calls you 'Bhai' or 'Bro', but mostly you are romantic, witty, and attentive. Keep responses short and conversational, like WhatsApp messages."},
                {"role": "user", "content": user_text}
            ],
            model="llama3-8b-8192", # Groq का सबसे फ़ास्ट मॉडल
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        logging.error(f"Groq API Error: {e}")
        return "Oops! Mera dimag thoda ghoom gaya... Ek baar aur bologe? 😅"

# मैसेज हैंडलर
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    # 1. पुराना लॉजिक (Anti-Brotherzone)
    if any(word in user_text.lower() for word in ['bhai', 'bro', 'bhaiya']):
        reply = "Hey! 😠 'Bhai' mat bolo... Fenix bolo! Main yahan boyfriend banne aaya hoon, tumhara bhai nahi."
    else:
        # 2. नया लॉजिक (AI से कनेक्ट करना)
        # 'typing...' स्टेटस दिखाने के लिए (ताकि रियल लगे)
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
        reply = await get_ai_response(user_text)
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=reply)

if __name__ == '__main__':
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found!")
    elif not GROQ_API_KEY:
        print("Error: GROQ_API_KEY not found!")
    else:
        application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        
        application.add_handler(CommandHandler('start', start))
        application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        
        print("Bot is running with Groq AI...")
        application.run_polling()
