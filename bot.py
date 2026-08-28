import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

# إعداد سرفر وهمي بـ Flask لإقناع منصة Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('أهلاً بك! البوت يعمل الآن بشكل دائم على سحابة Render 🚀')

def main():
    TOKEN = "8965186384:AAEadFB6hGmoazwbQsoTe8oTTaUFRSZfIro"
    
    application = ApplicationBuilder().token(TOKEN).read_timeout(30).write_timeout(30).connect_timeout(30).build()
    application.add_handler(CommandHandler("start", start))
    
    print("Bot is starting...")
    application.run_polling()

if __name__ == '__main__':
    t = threading.Thread(target=run_web)
    t.start()
    main()
