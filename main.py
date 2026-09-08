import os
import time
import sqlite3
import urllib.parse
import threading
import telebot
from telebot import types
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- 1. WEB SERVICE PORT BINDING (Render Free Tier) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Vynora Bot is Live with SQLite!")

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# --- 2. SQLITE DATABASE SETUP (100% FREE & PERMANENT) ---
DB_NAME = "vynora.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            phone TEXT,
            balance INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def get_user_data(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT name, phone, balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"name": row[0], "phone": row[1], "balance": row[2]}
    return {"name": None, "phone": None, "balance": 0}

def add_user_balance(user_id, mins):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, balance) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?
    ''', (user_id, mins, mins))
    conn.commit()
    conn.close()

def deduct_user_balance(user_id, mins):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (mins, user_id))
    conn.commit()
    conn.close()

def save_user_profile(user_id, name, phone):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, name, phone) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET name = ?, phone = ?
    ''', (user_id, name, phone, name, phone))
    conn.commit()
    conn.close()

def get_all_db_users():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name, phone, balance FROM users")
    rows = cursor.fetchall()
    conn.close()
    return rows

# Database Table Ensure Karein
init_db()

# --- 3. TELEGRAM BOT CONFIG ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8967146778:AAG6NJSZiLGiJrMHaKdIO9eSBiZ7uz_72VU")
ADMIN_GROUP_ID = int(os.environ.get("ADMIN_GROUP_ID", "-1004325621712"))
HOST_GROUP_ID = -1004312344325
UPI_ID = "vynoralive@slc"
PAYEE_NAME = "Rajnish Kumar"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton("🔥 Book Host Session")
    btn2 = types.KeyboardButton("💳 Buy Minutes / Payment")
    btn3 = types.KeyboardButton("💰 My Balance & Referral")
    btn4 = types.KeyboardButton("📝 Register / Profile")
    btn5 = types.KeyboardButton("🎥 Bot Tutorial")
    btn6 = types.KeyboardButton("👑 Register as Host")
    btn7 = types.KeyboardButton("🆘 Help / Support")
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)
    markup.add(btn5, btn6)
    markup.add(btn7)
    return markup

# --- 4. START COMMAND ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.send_message(
        message.chat.id, 
        f"✨ *Welcome to Vynora Live!*\n\nNamaste *{message.from_user.first_name}*, niche diye gaye menu se service chunein:", 
        reply_markup=get_main_keyboard()
    )

# --- 5. BOOK HOST SESSION ---
@bot.message_handler(func=lambda msg: msg.text in ["Book Host Session", "🔥 Book Host Session"])
def book_host(message):
    user_id = message.chat.id
    user_info = get_user_data(user_id)
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💃 Host Priya — 🟢 Online", callback_data="select_host_Priya"),
        types.InlineKeyboardButton("🔥 Host Ananya — 🟢 Online", callback_data="select_host_Ananya"),
        types.InlineKeyboardButton("✨ Host Simran — 🟢 Online", callback_data="select_host_Simran")
    )
    
    text = (
        "✨ *VYNORA LIVE - HOST SELECTION*\n\n"
        f"💰 *Aapka Available Balance:* `{user_info['balance']} Minutes`\n\n"
        "👇 *Session ke liye kisi ek Host ko chunein:*"
    )
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("select_host_"))
def show_host_durations(call):
    host_name = call.data.replace("select_host_", "")
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("⏱️ 5 Mins", callback_data=f"book_{host_name}_5"),
        types.InlineKeyboardButton("⏱️ 10 Mins", callback_data=f"book_{host_name}_10"),
        types.InlineKeyboardButton("⏱️ 20 Mins", callback_data=f"book_{host_name}_20"),
        types.InlineKeyboardButton("⏱️ 30 Mins", callback_data=f"book_{host_name}_30"),
        types.InlineKeyboardButton("⬅️ Back to Hosts", callback_data="back_to_hosts")
    )
    
    text = f"👤 *Selected Host: {host_name}*\n\n👇 *Kitne samay (Minutes) ke liye session book karna hai select karein:*"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_hosts")
def back_to_hosts(call):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💃 Host Priya — 🟢 Online", callback_data="select_host_Priya"),
        types.InlineKeyboardButton("🔥 Host Ananya — 🟢 Online", callback_data="select_host_Ananya"),
        types.InlineKeyboardButton("✨ Host Simran — 🟢 Online", callback_data="select_host_Simran")
    )
    bot.edit_message_text("✨ *VYNORA LIVE - HOST SELECTION*\n\n👇 *Session ke liye kisi ek Host ko chunein:*", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("book_"))
def process_booking_click(call):
    user_id = call.from_user.id
    _, host_name, mins = call.data.split("_")
    mins = int(mins)
    
    user_info = get_user_data(user_id)
    if user_info['balance'] < mins:
        bot.answer_callback_query(call.id, f"❌ Balance Kam Hai! Is session ke liye {mins} Mins chahiye.", show_alert=True)
        return
        
    # Balance Deduct in SQLite
    deduct_user_balance(user_id, mins)
    new_bal = user_info['balance'] - mins
    bot.answer_callback_query(call.id, "✅ Session Book Ho Gaya!")
    
    # 1-Time Group Invite Link Generation
    try:
        invite_link = bot.create_chat_invite_link(chat_id=HOST_GROUP_ID, member_limit=1).invite_link
    except Exception as e:
        print(f"Invite link error: {e}")
        invite_link = "https://t.me/+SamplePrivateLink123"
    
    text = (
        "🎉 *SESSION BOOKING SUCCESSFUL!*\n\n"
        f"👤 *Host:* {host_name}\n"
        f"⏱️ *Duration:* {mins} Minutes\n"
        f"💰 *Remaining Balance:* `{new_bal} Mins`\n\n"
        "👇 *Niche button par click karke private group join karein (1-Time Link):*"
    )
    
    link_markup = types.InlineKeyboardMarkup()
    link_markup.add(types.InlineKeyboardButton("🔗 Join Private Session Now", url=invite_link))
    
    bot.send_message(user_id, text, reply_markup=link_markup)

# --- 6. BUY MINUTES & PAYMENT ---
@bot.message_handler(func=lambda msg: msg.text in ["Buy Minutes / Payment", "💳 Buy Minutes / Payment"])
def buy_minutes(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("⭐ ₹100 — 5 Minutes", callback_data="payplan_100_5"),
        types.InlineKeyboardButton("🔥 ₹200 — 10 Minutes", callback_data="payplan_200_10"),
        types.InlineKeyboardButton("🚀 ₹400 — 20 Minutes", callback_data="payplan_400_20"),
        types.InlineKeyboardButton("💎 ₹500 — 30 Minutes", callback_data="payplan_500_30"),
        types.InlineKeyboardButton("👑 ₹1000 — 90 Minutes", callback_data="payplan_1000_90")
    )
    bot.send_message(message.chat.id, "💳 *SELECT YOUR RECHARGE PLAN*\n\nNiche diye gaye plans mein se select karein:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("payplan_"))
def show_plan_qr(call):
    _, amount, mins = call.data.split("_")
    upi_url = f"upi://pay?pa={UPI_ID}&pn={urllib.parse.quote(PAYEE_NAME)}&am={amount}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={urllib.parse.quote(upi_url)}"
    
    caption = (
        f"🎯 *SELECTED PLAN: ₹{amount} ({mins} Minutes)*\n\n"
        f"👤 *Account Holder:* {PAYEE_NAME}\n"
        f"📍 *UPI ID:* `{UPI_ID}`\n"
        f"💰 *Amount to Pay:* `₹{amount}`\n\n"
        "📲 *QR Code scan karke pay karein aur Payment ka Screenshot isi chat mein bhejein.*"
    )
    bot.send_photo(call.message.chat.id, qr_url, caption=caption)
    bot.answer_callback_query(call.id)

# --- 7. BALANCE & REFERRAL ---
@bot.message_handler(func=lambda msg: msg.text in ["My Balance & Referral", "💰 My Balance & Referral"])
def show_balance(message):
    user_id = message.chat.id
    user_info = get_user_data(user_id)
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start={user_id}"
    
    text = (
        "💰 *Aapka Account Balance*\n\n"
        f"• Remaining Balance: *{user_info['balance']} Minutes*\n\n"
        "🔗 *Aapka Referral Link:*\n"
        f"`{ref_link}`\n\n"
        "🎁 *Reward:* Link share karne par har friend join par +1 Minute credit hoga."
    )
    bot.send_message(message.chat.id, text)

# --- 8. REGISTER / PROFILE ---
@bot.message_handler(func=lambda msg: msg.text in ["Register / Update Profile", "📝 Register / Profile"])
def register_profile(message):
    user_id = message.chat.id
    user_info = get_user_data(user_id)
    
    if user_info['phone']:
        text = (
            "👤 *YOUR PROFILE DETAILS*\n\n"
            f"• *Name:* `{user_info['name']}`\n"
            f"• *Phone:* `{user_info['phone']}`\n"
            "• *Status:* ✅ Verified User"
        )
        bot.send_message(message.chat.id, text)
    else:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton("📱 Share Phone Number (1-Click)", request_contact=True))
        bot.send_message(message.chat.id, "📝 *EASY REGISTRATION*\n\nAccount verify karne ke liye **'Share Phone Number'** button par click karein:", reply_markup=markup)

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    if message.contact:
        user_id = message.chat.id
        phone = message.contact.phone_number
        name = message.from_user.first_name
        
        save_user_profile(user_id, name, phone)
        bot.send_message(user_id, f"🎉 *Registration Complete!*\n\n👤 *Name:* {name}\n📱 *Phone:* `{phone}`", reply_markup=get_main_keyboard())

# --- 9. ADMIN COMMANDS (DATA CHECK) ---
@bot.message_handler(commands=['stats'])
def check_stats(message):
    if message.chat.id == ADMIN_GROUP_ID or str(message.chat.id) in str(ADMIN_GROUP_ID):
        users = get_all_db_users()
        total_users = len(users)
        total_bal = sum([u[3] for u in users])
        text = f"📊 *VYNORA SYSTEM STATS*\n\n👤 *Total Users:* `{total_users}`\n⏱️ *Total Active Balance:* `{total_bal} Minutes`"
        bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['allusers'])
def list_users(message):
    if message.chat.id == ADMIN_GROUP_ID or str(message.chat.id) in str(ADMIN_GROUP_ID):
        users = get_all_db_users()
        if not users:
            bot.send_message(message.chat.id, "❌ Abhi koi registered user nahi hai.")
            return
        text = "📋 *REGISTERED USERS DATABASE*\n\n"
        for u in users:
            text += f"• *ID:* `{u[0]}` | *Name:* {u[1] or 'N/A'} | *Phone:* `{u[2] or 'N/A'}` | *Bal:* `{u[3]} Mins`\n"
        bot.send_message(message.chat.id, text)

# --- 10. TUTORIAL & HOST REGISTRATION ---
@bot.message_handler(func=lambda msg: msg.text in ["Bot Tutorial", "🎥 Bot Tutorial"])
def bot_tutorial(message):
    text = "🎥 *VYNORA LIVE - BOT TUTORIAL*\n\n1️⃣ 'Buy Minutes / Payment' se recharge karein.\n2️⃣ 'Book Host Session' se Host book karke instant live room join karein."
    bot.send_message(message.chat.id, text)

@bot.message_handler(func=lambda msg: msg.text in ["Register as Host", "👑 Register as Host"])
def register_host(message):
    bot.send_message(message.chat.id, "👑 *BECOME A VYNORA HOST*\n\nApni details (Name, Age, UPI ID) admin ko bhejein:\n📩 *Admin:* @VynoraSupport")

@bot.message_handler(func=lambda msg: msg.text in ["Help / Support", "🆘 Help / Support"])
def help_support(message):
    bot.send_message(message.chat.id, "🆘 *VYNORA SUPPORT*\n\n📩 *Admin Contact:* @VynoraSupport")

# --- 11. PAYMENT SCREENSHOT & APPROVALS ---
@bot.message_handler(content_types=['photo'])
def handle_screenshot(message):
    if message.chat.type == 'private':
        photo_id = message.photo[-1].file_id
        user_id = message.chat.id
        txn_id = f"TXN{int(time.time())}"
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("5 Min (Rs.100)", callback_data=f"app_{user_id}_5"),
            types.InlineKeyboardButton("10 Min (Rs.200)", callback_data=f"app_{user_id}_10"),
            types.InlineKeyboardButton("20 Min (Rs.400)", callback_data=f"app_{user_id}_20"),
            types.InlineKeyboardButton("30 Min (Rs.500)", callback_data=f"app_{user_id}_30"),
            types.InlineKeyboardButton("90 Min (Rs.1000)", callback_data=f"app_{user_id}_90"),
            types.InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user_id}")
        )
        bot.send_photo(ADMIN_GROUP_ID, photo_id, caption=f"📸 *Payment Screenshot*\nUser ID: `{user_id}`\nTxn ID: `{txn_id}`", reply_markup=markup)
        bot.send_message(user_id, "⏳ Aapka screenshot verification ke liye Admin ko bhej diya gaya hai.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(("app_", "rej_")))
def process_admin_callbacks(call):
    data = call.data
    if data.startswith("app_"):
        _, user_id, mins = data.split("_")
        user_id, mins = int(user_id), int(mins)

        # Update balance in SQLite
        add_user_balance(user_id, mins)

        bot.send_message(user_id, f"✅ *Payment Approved!*\nAapke account mein *{mins} Minutes* add kar diye gaye hain.")
        bot.answer_callback_query(call.id, "Approved!")
        bot.edit_message_caption(f"✅ APPROVED: {mins} Mins credited to User ID `{user_id}`", ADMIN_GROUP_ID, call.message.message_id)
        
    elif data.startswith("rej_"):
        _, user_id = data.split("_")
        user_id = int(user_id)
        bot.send_message(user_id, "❌ Aapka payment screenshot reject ho gaya hai.")
        bot.answer_callback_query(call.id, "Rejected!")
        bot.edit_message_caption(f"❌ REJECTED for User ID `{user_id}`", ADMIN_GROUP_ID, call.message.message_id)

if __name__ == '__main__':
    print("Vynora Bot Running with SQLite Database...")
    try:
        bot.remove_webhook()
    except Exception as e:
        print(f"Webhook note: {e}")
    bot.infinity_polling(skip_pending=True)
