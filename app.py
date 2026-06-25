import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# लॉगिंग सेट करना ताकि रेंडर के 'Logs' में आप देख सकें कि बोट क्या कर रहा है
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# टोकन एनवायरमेंट वेरिएबल से आएगा
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hey! Fenix is here. 😉")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    # एंटी-ब्रदरज़ोन लॉजिक
    if any(word in user_text.lower() for word in ['bhai', 'bro', 'bhaiya']):
        reply = "Hey! 😠 'Bhai' mat bolo... Fenix bolo!"
    else:
        reply = "I am listening..."
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=reply)

if __name__ == '__main__':
    if not TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found!")
    else:
        application = ApplicationBuilder().token(TOKEN).build()
        
        start_handler = CommandHandler('start', start)
        msg_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
        
        application.add_handler(start_handler)
        application.add_handler(msg_handler)
        
        # रेंडर पर पोलिंग मोड में बोट चलाना
        application.run_polling()
