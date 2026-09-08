import telebot
from telebot import types
import urllib.parse
import time
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Web Service Port Handler (Render Free Tier Ke Liye)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Vynora Bot is Live!")

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# Telegram Bot Config
BOT_TOKEN = "8967146778:AAFAGfl7jaejeRfpWA8Mykl0FxK8zax_rkc"
ADMIN_GROUP_ID = -1004325621712
UPI_ID = "vynoralive@slc"
PAYEE_NAME = "Rajnish Kumar"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")
user_balances = {}

@bot.message_handler(commands=['start'])
def start_cmd(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton("Book Host Session")
    btn2 = types.KeyboardButton("Buy Minutes / Payment")
    btn3 = types.KeyboardButton("My Balance & Referral")
    btn4 = types.KeyboardButton("Register / Update Profile")
    btn5 = types.KeyboardButton("Help / Support")
    markup.add(btn1, btn2, btn3, btn4, btn5)
    
    bot.send_message(
        message.chat.id, 
        f"Namaste {message.from_user.first_name}! Vynora Live Bot mein aapka swagat hai.", 
        reply_markup=markup
    )

@bot.message_handler(func=lambda msg: msg.text == "Buy Minutes / Payment")
def buy_minutes(message):
    upi_url = f"upi://pay?pa={UPI_ID}&pn={urllib.parse.quote(PAYEE_NAME)}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={urllib.parse.quote(upi_url)}"
    
    caption = (
        "💳 *VYNORA LIVE - PAYMENT DETAILS*\n\n"
        "• Rs.100 = 5 Minutes\n"
        "• Rs.200 = 10 Minutes\n"
        "• Rs.400 = 20 Minutes\n"
        "• Rs.500 = 30 Minutes\n"
        "• Rs.1000 = 90 Minutes\n\n"
        f"👤 *Account Holder:* {PAYEE_NAME}\n"
        f"📍 *UPI ID:* `{UPI_ID}`\n\n"
        "📸 *Note:* Upar diye QR par pay karke screenshot isi chat mein bhejein."
    )
    bot.send_photo(message.chat.id, qr_url, caption=caption)

@bot.message_handler(content_types=['photo'])
def handle_screenshot(message):
    if message.chat.type == 'private':
        photo_id = message.photo[-1].file_id
        user_id = message.chat.id
        txn_id = f"TXN{int(time.time())}"
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn1 = types.InlineKeyboardButton("5 Min (Rs.100)", callback_data=f"app_{user_id}_5")
        btn2 = types.InlineKeyboardButton("10 Min (Rs.200)", callback_data=f"app_{user_id}_10")
        btn3 = types.InlineKeyboardButton("20 Min (Rs.400)", callback_data=f"app_{user_id}_20")
        btn4 = types.InlineKeyboardButton("30 Min (Rs.500)", callback_data=f"app_{user_id}_30")
        btn5 = types.InlineKeyboardButton("90 Min (Rs.1000)", callback_data=f"app_{user_id}_90")
        btn_rej = types.InlineKeyboardButton("Reject", callback_data=f"rej_{user_id}")
        markup.add(btn1, btn2, btn3, btn4, btn5, btn_rej)
        
        admin_msg = f"📸 *New Payment Screenshot*\n\nUser ID: `{user_id}`\nTxn ID: `{txn_id}`"
        bot.send_photo(ADMIN_GROUP_ID, photo_id, caption=admin_msg, reply_markup=markup)
        bot.send_message(user_id, "⏳ Aapka screenshot verification ke liye admin ko bhej diya gaya hai.")

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    data = call.data
    if data.startswith("app_"):
        parts = data.split("_")
        user_id = int(parts[1])
        mins = int(parts[2])
        
        user_balances[user_id] = user_balances.get(user_id, 0) + mins
        
        bot.send_message(user_id, f"✅ *Payment Approved!*\nAapke account mein *{mins} Minutes* add kar diye gaye hain.\nTotal Balance: {user_balances[user_id]} Minutes.")
        bot.answer_callback_query(call.id, "Approved!")
        bot.edit_message_caption(f"✅ APPROVED: {mins} Mins credited to User ID `{user_id}`", ADMIN_GROUP_ID, call.message.message_id)
    elif data.startswith("rej_"):
        parts = data.split("_")
        user_id = int(parts[1])
        bot.send_message(user_id, "❌ Aapka payment screenshot reject ho gaya hai. Admin se sampark karein.")
        bot.answer_callback_query(call.id, "Rejected!")
        bot.edit_message_caption(f"❌ REJECTED for User ID `{user_id}`", ADMIN_GROUP_ID, call.message.message_id)

@bot.message_handler(func=lambda msg: msg.text == "My Balance & Referral")
def show_balance(message):
    user_id = message.chat.id
    bal = user_balances.get(user_id, 0)
    bot.send_message(message.chat.id, f"💰 *Aapka Account Balance*\n\nRemaining Balance: *{bal} Minutes*")

if __name__ == '__main__':
    print("Vynora Bot Active & Running...")
    bot.remove_webhook(drop_pending_updates=True)
    bot.infinity_polling()

