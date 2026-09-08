import os
import time
import urllib.parse
import threading
import telebot
from telebot import types
from http.server import HTTPServer, BaseHTTPRequestHandler

# 1. Web Service Port Binding (Render Free Tier)
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

# 2. Telegram Bot Config
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8967146778:AAG6NJSZiLGiJrMHaKdIO9eSBiZ7uz_72VU")
ADMIN_GROUP_ID = int(os.environ.get("ADMIN_GROUP_ID", "-1004325621712"))
UPI_ID = "vynoralive@slc"
PAYEE_NAME = "Rajnish Kumar"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# Database Storage
user_balances = {}
user_profiles = {}

# Main Reply Keyboard
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton("🔥 Book Host Session")
    btn2 = types.KeyboardButton("💳 Buy Minutes / Payment")
    btn3 = types.KeyboardButton("💰 My Balance & Referral")
    btn4 = types.KeyboardButton("📝 Register / Profile")
    btn5 = types.KeyboardButton("🆘 Help / Support")
    markup.add(btn1, btn2, btn3, btn4, btn5)
    return markup

# --- 1. START COMMAND ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.send_message(
        message.chat.id, 
        f"✨ *Welcome to Vynora Live!*\n\nNamaste *{message.from_user.first_name}*, niche diye gaye menu se service chunein:", 
        reply_markup=get_main_keyboard()
    )

# --- 2. EASY 1-TOUCH BOOKING (NO COMMAND TYPING) ---
@bot.message_handler(func=lambda msg: msg.text in ["Book Host Session", "🔥 Book Host Session"])
def book_host(message):
    user_id = message.chat.id
    bal = user_balances.get(user_id, 0)
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn1 = types.InlineKeyboardButton("💃 Host Priya (10 Mins) - 📱 Online", callback_data="book_Priya_10")
    btn2 = types.InlineKeyboardButton("🔥 Host Ananya (20 Mins) - 📱 Online", callback_data="book_Ananya_20")
    btn3 = types.InlineKeyboardButton("✨ Host Simran (30 Mins) - 📱 Online", callback_data="book_Simran_30")
    markup.add(btn1, btn2, btn3)
    
    text = (
        "✨ *VYNORA LIVE - INSTANT BOOKING*\n\n"
        f"💰 *Aapka Available Balance:* `{bal} Minutes`\n\n"
        "👇 *Session start karne ke liye Host ke naam par click karein:*"
    )
    bot.send_message(message.chat.id, text, reply_markup=markup)

# Host Booking Click Callback Handler
@bot.callback_query_handler(func=lambda call: call.data.startswith("book_"))
def process_booking_click(call):
    user_id = call.from_user.id
    _, host_name, mins = call.data.split("_")
    mins = int(mins)
    bal = user_balances.get(user_id, 0)
    
    if bal < mins:
        bot.answer_callback_query(call.id, f"❌ Balance Kam Hai! Is session ke liye {mins} Mins chahiye.", show_alert=True)
        return
        
    # Balance Deduct
    user_balances[user_id] = bal - mins
    bot.answer_callback_query(call.id, "✅ Session Book Ho Gaya!")
    
    # Send Private Session Card
    text = (
        "🎉 *SESSION BOOKING SUCCESSFUL!*\n\n"
        f"👤 *Host:* {host_name}\n"
        f"⏱️ *Duration:* {mins} Minutes\n"
        f"💰 *Remaining Balance:* `{user_balances[user_id]} Mins`\n\n"
        "👇 *Niche button par click karke private group join karein:*"
    )
    
    link_markup = types.InlineKeyboardMarkup()
    link_markup.add(types.InlineKeyboardButton("🔗 Join Private Session Now", url="https://t.me/+SamplePrivateLink123"))
    
    bot.send_message(user_id, text, reply_markup=link_markup)

# --- 3. EASY 1-CLICK REGISTRATION (NATIVE CONTACT SHARE) ---
@bot.message_handler(func=lambda msg: msg.text in ["Register / Update Profile", "📝 Register / Profile"])
def register_profile(message):
    user_id = message.chat.id
    profile = user_profiles.get(user_id, None)
    
    if profile:
        text = (
            "👤 *YOUR PROFILE DETAILS*\n\n"
            f"• *Name:* `{profile['name']}`\n"
            f"• *Phone:* `{profile['phone']}`\n"
            "• *Status:* ✅ Verified User"
        )
        bot.send_message(message.chat.id, text)
    else:
        # Request Contact Button
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        btn_contact = types.KeyboardButton("📱 Share Phone Number (1-Click)", request_contact=True)
        markup.add(btn_contact)
        
        bot.send_message(
            message.chat.id, 
            "📝 *EASY REGISTRATION*\n\nAccount verify karne ke liye niche **'Share Phone Number'** button par click karein:", 
            reply_markup=markup
        )

# Auto Contact Receiver
@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    if message.contact:
        user_id = message.chat.id
        phone = message.contact.phone_number
        name = message.from_user.first_name
        
        user_profiles[user_id] = {"name": name, "phone": phone}
        
        bot.send_message(
            user_id, 
            f"🎉 *Registration Complete!*\n\n👤 *Name:* {name}\n📱 *Phone:* `{phone}`\n\nAapka profile setup successfully ho gaya hai.",
            reply_markup=get_main_keyboard()
        )

# 1. Buy Minutes - Shows Plans First
@bot.message_handler(func=lambda msg: msg.text in ["Buy Minutes / Payment", "💳 Buy Minutes / Payment"])
def buy_minutes(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn1 = types.InlineKeyboardButton("⭐ ₹100 — 5 Minutes", callback_data="payplan_100_5")
    btn2 = types.InlineKeyboardButton("🔥 ₹200 — 10 Minutes", callback_data="payplan_200_10")
    btn3 = types.InlineKeyboardButton("🚀 ₹400 — 20 Minutes", callback_data="payplan_400_20")
    btn4 = types.InlineKeyboardButton("💎 ₹500 — 30 Minutes", callback_data="payplan_500_30")
    btn5 = types.InlineKeyboardButton("👑 ₹1000 — 90 Minutes", callback_data="payplan_1000_90")
    markup.add(btn1, btn2, btn3, btn4, btn5)
    
    bot.send_message(
        message.chat.id, 
        "💳 *SELECT YOUR RECHARGE PLAN*\n\nNiche diye gaye plans me se apna plan select karein:", 
        reply_markup=markup
    )

# 2. Plan Select karne par QR Code Dikhana
@bot.callback_query_handler(func=lambda call: call.data.startswith("payplan_"))
def show_plan_qr(call):
    _, amount, mins = call.data.split("_")
    
    # UPI URL with Exact Amount
    upi_url = f"upi://pay?pa={UPI_ID}&pn={urllib.parse.quote(PAYEE_NAME)}&am={amount}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={urllib.parse.quote(upi_url)}"
    
    caption = (
        f"🎯 *SELECTED PLAN: ₹{amount} ({mins} Minutes)*\n\n"
        f"👤 *Account Holder:* {PAYEE_NAME}\n"
        f"📍 *UPI ID:* `{UPI_ID}`\n"
        f"💰 *Amount to Pay:* `₹{amount}`\n\n"
        "📲 *QR Code scan karke pay karein aur Payment ka Screenshot isi chat me bhejein.*"
    )
    bot.send_photo(call.message.chat.id, qr_url, caption=caption)
    bot.answer_callback_query(call.id)


# --- 5. BALANCE & REFERRAL ---
@bot.message_handler(func=lambda msg: msg.text in ["My Balance & Referral", "💰 My Balance & Referral"])
def show_balance(message):
    user_id = message.chat.id
    bal = user_balances.get(user_id, 0)
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start={user_id}"
    
    text = (
        "💰 *Aapka Account Balance*\n\n"
        f"• Remaining Balance: *{bal} Minutes*\n\n"
        "🔗 *Aapka Referral Link:*\n"
        f"`{ref_link}`\n\n"
        "🎁 *Reward:* Link share karne par har friend join par +1 Minute credit hoga."
    )
    bot.send_message(message.chat.id, text)

# --- 6. HELP & SUPPORT ---
@bot.message_handler(func=lambda msg: msg.text in ["Help / Support", "🆘 Help / Support"])
def help_support(message):
    text = (
        "🆘 *VYNORA LIVE - HELP & SUPPORT*\n\n"
        "Kisi bhi madad ke liye admin se sampark karein:\n\n"
        "• *Admin Handle:* @VynoraSupport\n"
        "• *Timing:* 24x7 Support Available"
    )
    bot.send_message(message.chat.id, text)

# --- 7. SCREENSHOT & ADMIN APPROVAL HANDLERS ---
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
        btn_rej = types.InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user_id}")
        markup.add(btn1, btn2, btn3, btn4, btn5, btn_rej)

        admin_msg = f"📸 *New Payment Screenshot*\n\nUser ID: `{user_id}`\nTxn ID: `{txn_id}`"
        bot.send_photo(ADMIN_GROUP_ID, photo_id, caption=admin_msg, reply_markup=markup)
        bot.send_message(user_id, "⏳ Aapka screenshot verification ke liye Admin ko bhej diya gaya hai.")

# Admin Callbacks
@bot.callback_query_handler(func=lambda call: call.data.startswith(("app_", "rej_")))
def process_admin_callbacks(call):
    data = call.data
    if data.startswith("app_"):
        _, user_id, mins = data.split("_")
        user_id, mins = int(user_id), int(mins)

        user_balances[user_id] = user_balances.get(user_id, 0) + mins

        bot.send_message(user_id, f"✅ *Payment Approved!*\nAapke account mein *{mins} Minutes* add kar diye gaye hain.")
        bot.answer_callback_query(call.id, "Approved!")
        bot.edit_message_caption(f"✅ APPROVED: {mins} Mins credited to User ID `{user_id}`", ADMIN_GROUP_ID, call.message.message_id)
        
    elif data.startswith("rej_"):
        _, user_id = data.split("_")
        user_id = int(user_id)
        
        bot.send_message(user_id, "❌ Aapka payment screenshot reject ho gaya hai. Admin se sampark karein.")
        bot.answer_callback_query(call.id, "Rejected!")
        bot.edit_message_caption(f"❌ REJECTED for User ID `{user_id}`", ADMIN_GROUP_ID, call.message.message_id)

if __name__ == '__main__':
    print("Vynora Bot Active & Running...")
    try:
        bot.remove_webhook()
    except Exception as e:
        print(f"Webhook note: {e}")
        
    bot.infinity_polling(skip_pending=True)
