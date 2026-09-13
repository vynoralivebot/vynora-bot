import os
import telebot
from dotenv import load_dotenv
from database import users_collection

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    print("CRITICAL ERROR: BOT_TOKEN is missing from environment variables!")
    exit(1)

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    name = message.from_user.first_name
    
    bot.reply_to(message, f"Welcome, {name}! Your setup is working successfully.")

if __name__ == "__main__":
    print("Bot is polling...")
    bot.infinity_polling()
