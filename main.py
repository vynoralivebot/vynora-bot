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
        self.wfile.write(b"Vynora Live Bot is Online & Fully Functional!")

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# --- 2. PERMANENT SQLITE DATABASE SETUP ---
DB_NAME = "vynora.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            phone TEXT,
            balance INTEGER DEFAULT 0
        )
    ''')
    # Sessions History Table (For /data command)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            host_name TEXT,
            duration INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

def log_session(user_id, host_name, duration):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions (user_id, host_name, duration) VALUES (?, ?, ?)", (user_id, host_name, duration))
    conn.commit()
    conn.close()

def get_today_sessions(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT host_name, duration, strftime('%H:%M', created_at, 'localtime') 
        FROM sessions 
        WHERE user_id = ? AND date(created_at, 'localtime') = date('now', 'localtime')
        ORDER BY id DESC
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_all_db_users():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name, phone, balance FROM users")
    rows = cursor.fetchall()
    conn.close()
    return rows

init_db()

# Pending UTR Storage
pending_txns = {}

# --- 3. BOT CONFIGURATION ---
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
    btn7 = types.KeyboardButton("💸 Withdraw Earnings")
    btn8 = types.KeyboardButton("🆘 Help / Support")
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)
    markup.add(btn5, btn6)
    markup.add(btn7, btn8)
    return markup

# --- 4. START COMMAND ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.send_message(
        message.chat.id, 
        f"✨ *Welcome to Vynora Live Official Bot!*\n\nNamaste *{message.from_user.first_name}*, niche diye gaye menu se service chunein:", 
        reply_markup=get_main_keyboard()
    )

# --- 5. TUTORIAL SYSTEM ---
@bot.message_handler(commands=['tutorial'])
@bot.message_handler(func=lambda msg: msg.text in ["Bot Tutorial", "🎥 Bot Tutorial"])
def bot_tutorial(message):
    tutorial_text = (
        "📖 *VYNORA LIVE — COMPLETE USER GUIDE & TUTORIAL*\n\n"
        "Welcome! Vynora Live Bot ko use karke 1-on-1 private live call book karna behad aasan hai.\n\n"
        "🔹 *Step 1: Account Registration*\n"
        "• Main menu mein **'📝 Register / Profile'** par click karein.\n"
        "• Single click mein apna contact number share karke profile complete karein.\n\n"
        "🔹 *Step 2: Recharge Minutes*\n"
        "• **'💳 Buy Minutes / Payment'** button select karein.\n"
        "• Plan (Rs. 100 - 1000) chunein aur QR code scan karke UPI pay karein.\n"
        "• Payment Screenshot bhejein aur uske baad apna 12-digit **UTR Number** fill karein.\n\n"
        "🔹 *Step 3: Host Booking*\n"
        "• **'🔥 Book Host Session'** par click karein.\n"
        "• Apni favorite online host aur duration (5m se 90m) select karein.\n\n"
        "🔹 *Step 4: Join Private Session*\n"
        "• Instant bot aapko ek **1-Time Private Group Link** dega.\n"
        "• Link par click karke instant private live session join karein.\n\n"
        "📊 *Daily Data:* Host/User apna daily history `/data` likh kar dekh sakte hain.\n\n"
        "❓ *Help:* Kisi bhi samasya ke liye **'🆘 Help / Support'** option ka upyog karein."
    )
    bot.send_message(message.chat.id, tutorial_text)

# --- 6. DAILY DATA CHECK (/data) ---
@bot.message_handler(commands=['data'])
def show_daily_data(message):
    user_id = message.chat.id
    sessions = get_today_sessions(user_id)
    
    if not sessions:
        bot.send_message(
            user_id, 
            "📊 *DAILY SESSION DATA*\n\n"
            "❌ Aaj aapne koi bhi session book / complete nahi kiya hai.\n"
            "Naye sessions lene ke baad aapka history yahan update hoga."
        )
        return
        
    total_calls = len(sessions)
    total_mins = sum([s[1] for s in sessions])
    
    text = (
        "📊 *TODAY'S WORK & SESSION SUMMARY*\n\n"
        f"📞 *Total Calls Today:* `{total_calls}`\n"
        f"⏱️ *Total Duration:* `{total_mins} Minutes`\n\n"
        "📝 *Call Breakup Details:*\n"
    )
    for idx, s in enumerate(sessions, 1):
        text += f"{idx}. ⏰ `{s[2]}` — *Host:* {s[0]} | *Duration:* `{s[1]} Mins`\n"
        
    bot.send_message(user_id, text)

# --- 7. HELP & SUPPORT SYSTEM ---
@bot.message_handler(commands=['help'])
@bot.message_handler(func=lambda msg: msg.text in ["Help / Support", "🆘 Help / Support"])
def help_support(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("💳 Recharge Issue", callback_data="help_recharge"),
        types.InlineKeyboardButton("📅 Booking Issue", callback_data="help_booking"),
        types.InlineKeyboardButton("👑 Host & Earnings", callback_data="help_host"),
        types.InlineKeyboardButton("❓ Other Queries", callback_data="help_other")
    )
    text = "🆘 *VYNORA LIVE CUSTOMER SUPPORT CENTER*\n\nAapko kis vishay me help chahiye? Niche option chunein:"
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("help_"))
def process_help_options(call):
    topic = call.data
    if topic == "help_recharge":
        ans = "💳 *RECHARGE HELP*\n\n• Payment ke baad Screenshot aur UTR bhejha zaroori hai.\n• Verification me 2-10 min lag sakte hain."
    elif topic == "help_booking":
        ans = "📅 *BOOKING HELP*\n\n• Check karein paryaapt minutes balance hai.\n• Invite Link 1-Time single use hota hai."
    elif topic == "help_host":
        ans = "👑 *HOST HELP*\n\n• Policy check karne ke liye `/hostpolicy` likhein.\n• Daily min withdrawal 500 Mins & max 5000 Mins hai."
    else:
        ans = "❓ *GENERAL HELP*\n\n• Screen recording prohibited hai."
        
    ans += "\n\n📩 *Direct Support Telegram:* @VynoraSupport"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💬 Chat with Admin Support", url="https://t.me/VynoraSupport"))
    bot.edit_message_text(ans, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

# --- 8. HOST POLICY & VALIDATED WITHDRAWAL SYSTEM ---
@bot.message_handler(commands=['hostpolicy', 'host_policy'])
@bot.message_handler(func=lambda msg: msg.text in ["Host Policy", "📜 Host Policy"])
def show_host_policy(message):
    text = (
        "👑 *VYNORA LIVE — HOST PAYMENT & WORKING POLICY*\n\n"
        "📊 *1. Earning & Commission Split (70/30 Rule):*\n"
        "• Aapke work ka *70% direct aapke Host Wallet mein add hoga*.\n"
        "• *30% Platform Service Fee* deduct hoga.\n"
        "_(Example: ₹100 ke kaam par ₹70 aapke wallet mein add honge aur ₹30 platform fee)._\n\n"
        "💳 *2. Withdrawal Limits (Daily Payout):*\n"
        "• *Minimum Daily Withdrawal:* `500 Mins` / Equivalent ₹\n"
        "• *Maximum Daily Withdrawal:* `5,000 Mins` per day\n\n"
        "⏱️ *3. Payout Processing Time:*\n"
        "• Payout *12 se 24 Ghante (Hours)* ke andar aapke UPI par transfer hoga.\n\n"
        "📩 *Questions / Support:* @VynoraSupport"
    )
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['withdraw'])
@bot.message_handler(func=lambda msg: msg.text in ["Withdraw Earnings", "💸 Withdraw Earnings"])
def start_withdrawal(message):
    user_id = message.chat.id
    user_info = get_user_data(user_id)
    balance = user_info['balance']
    
    if balance < 500:
        bot.send_message(
            user_id, 
            f"❌ *Withdrawal Reject Ho Gaya!*\n\n💰 Aapka Current Balance: `{balance} Mins`\n⚠️ Minimum withdrawal 500 Mins hai."
        )
        return

    msg = bot.send_message(
        user_id,
        f"💳 *VYNORA HOST WITHDRAWAL*\n\n💰 *Current Balance:* `{balance} Mins`\n📌 Limits: Min `500` | Max `5000` Mins\n\n👇 Kitne Mins withdraw karne hain enter karein:"
    )
    bot.register_next_step_handler(msg, process_withdraw_amount, balance)

def process_withdraw_amount(message, total_balance):
    user_id = message.chat.id
    amount_text = message.text.strip() if message.text else ""
    
    if not amount_text.isdigit():
        msg = bot.send_message(user_id, "❌ Kripya sirf number type karein (e.g. 500, 1000). Phir se try karein:")
        bot.register_next_step_handler(msg, process_withdraw_amount, total_balance)
        return
        
    amount = int(amount_text)
    
    if amount < 500:
        msg = bot.send_message(user_id, "❌ Minimum withdrawal limit *500 Mins* hai. Phir se enter karein:")
        bot.register_next_step_handler(msg, process_withdraw_amount, total_balance)
        return
        
    if amount > 5000:
        msg = bot.send_message(user_id, "❌ Maximum daily withdrawal limit *5000 Mins* hai. Phir se enter karein:")
        bot.register_next_step_handler(msg, process_withdraw_amount, total_balance)
        return

    if amount > total_balance:
        msg = bot.send_message(user_id, f"❌ Balance (`{total_balance} Mins`) kam hai. Phir se enter karein:")
        bot.register_next_step_handler(msg, process_withdraw_amount, total_balance)
        return

    msg = bot.send_message(user_id, f"✅ *Amount Validated:* `{amount} Mins`\n\n📲 Apna **UPI ID** type karke bhejein:")
    bot.register_next_step_handler(msg, process_withdraw_upi, amount)

def process_withdraw_upi(message, amount):
    user_id = message.chat.id
    upi_id = message.text.strip()
    
    deduct_user_balance(user_id, amount)
    
    bot.send_message(
        user_id, 
        f"🎉 *WITHDRAWAL REQUEST SUBMITTED!*\n\n💵 *Amount:* `{amount} Mins`\n📍 *UPI:* `{upi_id}`\n⏱️ Processing Time: 12-24 Hours."
    )
    
    admin_alert = (
        f"💸 *NEW HOST WITHDRAWAL REQUEST*\n\n"
        f"👤 *Host ID:* `{user_id}`\n👤 *Name:* {message.from_user.first_name}\n"
        f"💰 *Mins:* `{amount} Mins`\n📲 *UPI ID:* `{upi_id}`"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Mark Paid & Complete", callback_data=f"payout_done_{user_id}_{amount}"))
    bot.send_message(ADMIN_GROUP_ID, admin_alert, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("payout_done_"))
def admin_payout_complete(call):
    _, _, user_id, amount = call.data.split("_")
    bot.edit_message_text(f"✅ *PAID & COMPLETED*\nHost ID `{user_id}` ko `{amount} Mins` transfer ho gaye hain.", ADMIN_GROUP_ID, call.message.message_id)
    bot.send_message(int(user_id), f"🔔 *PAYMENT SUCCESSFUL!*\nAapka `{amount} Mins` ka payout transfer ho gaya hai.")
    bot.answer_callback_query(call.id, "Marked as Paid!")

# --- 9. NEW HOST REGISTRATION WITH APPLICATION FORM & AUTO-LINK ---
@bot.message_handler(func=lambda msg: msg.text in ["Register as Host", "👑 Register as Host"])
def start_host_registration(message):
    user_id = message.chat.id
    msg = bot.send_message(
        user_id,
        "👑 *BECOME A VYNORA LIVE OFFICIAL HOST*\n\n"
        "👤 *Step 1/4:* Apna **Full Name aur Age** enter karein (e.g., *Priya Sharma, 22*):"
    )
    bot.register_next_step_handler(msg, process_host_name)

def process_host_name(message):
    user_id = message.chat.id
    name_age = message.text.strip() if message.text else "N/A"
    msg = bot.send_message(user_id, f"✅ *Name Recorded:* `{name_age}`\n\n📞 *Step 2/4:* Apna **Calling Phone Number** enter karein:")
    bot.register_next_step_handler(msg, process_host_phone, name_age)

def process_host_phone(message, name_age):
    user_id = message.chat.id
    phone = message.text.strip() if message.text else "N/A"
    msg = bot.send_message(user_id, f"✅ *Phone Recorded:* `{phone}`\n\n💬 *Step 3/4:* Apna **WhatsApp Number** enter karein:")
    bot.register_next_step_handler(msg, process_host_whatsapp, name_age, phone)

def process_host_whatsapp(message, name_age, phone):
    user_id = message.chat.id
    whatsapp = message.text.strip() if message.text else "N/A"
    msg = bot.send_message(user_id, f"✅ *WhatsApp Recorded:* `{whatsapp}`\n\n📲 *Step 4/4:* Apna **Telegram Username** enter karein (e.g. `@priya_vynora`):")
    bot.register_next_step_handler(msg, process_host_tg, name_age, phone, whatsapp)

def process_host_tg(message, name_age, phone, whatsapp):
    user_id = message.chat.id
    tg_id = message.text.strip() if message.text else "N/A"
    
    bot.send_message(user_id, "🎉 *HOST APPLICATION SUBMITTED!*\n\nVerification ke baad aapko approval notification mil jayega.")
    
    admin_markup = types.InlineKeyboardMarkup(row_width=2)
    admin_markup.add(
        types.InlineKeyboardButton("✅ Approve Host", callback_data=f"hostapp_{user_id}"),
        types.InlineKeyboardButton("❌ Reject Host", callback_data=f"hostrej_{user_id}")
    )
    admin_card = (
        "👑 *NEW HOST APPLICATION RECEIVED*\n\n"
        f"👤 *Applicant ID:* `{user_id}`\nf"👤 *Name & Age:* `{name_age}`\n"
        f"📞 *Calling Phone:* `{phone}`\n💬 *WhatsApp No:* `{whatsapp}`\n"
        f"📲 *Telegram Username:* `{tg_id}`"
    )
    bot.send_message(ADMIN_GROUP_ID, admin_card, reply_markup=admin_markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith(("hostapp_", "hostrej_")))
def handle_host_approval(call):
    data = call.data.split("_")
    action, applicant_id = data[0], int(data[1])
    
    if action == "hostapp":
        try:
            host_invite_link = bot.create_chat_invite_link(chat_id=HOST_GROUP_ID, member_limit=1).invite_link
        except Exception:
            host_invite_link = "https://t.me/+SampleHostGroupLink"

        congrats_msg = (
            "🎉 *CONGRATULATIONS FROM VYNORA LIVE OFFICIAL!* 🎉\n\n"
            "Aapki Host Application **Approved** ho gayi hai!\n\n"
            "Official Host Group join karne ke liye niche diye gaye link par click karein:\n\n"
            f"🔗 *Official Host Group Link:* {host_invite_link}\n\n"
            "💬 Policy janne ke liye `/hostpolicy` use karein."
        )
        bot.send_message(applicant_id, congrats_msg)
        bot.edit_message_text(f"✅ *HOST APPROVED*\nUser ID `{applicant_id}` successfully approved.", ADMIN_GROUP_ID, call.message.message_id)
        bot.answer_callback_query(call.id, "Host Approved!")
    elif action == "hostrej":
        bot.send_message(applicant_id, "❌ *HOST APPLICATION UPDATE*\n\nAapki Host Application approve nahi ho saki. Support: @VynoraSupport")
        bot.edit_message_text(f"❌ *HOST REJECTED*\nUser ID `{applicant_id}` reject ho gayi hai.", ADMIN_GROUP_ID, call.message.message_id)
        bot.answer_callback_query(call.id, "Host Rejected!")

# --- 10. BOOK HOST SESSION (8 HOSTS SELECTION) ---
@bot.message_handler(func=lambda msg: msg.text in ["Book Host Session", "🔥 Book Host Session"])
def book_host(message):
    user_id = message.chat.id
    user_info = get_user_data(user_id)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("💃 Host Priya — 🟢", callback_data="select_host_Priya"),
        types.InlineKeyboardButton("🔥 Host Ananya — 🟢", callback_data="select_host_Ananya"),
        types.InlineKeyboardButton("✨ Host Simran — 🟢", callback_data="select_host_Simran"),
        types.InlineKeyboardButton("🌸 Host Neha — 🟢", callback_data="select_host_Neha"),
        types.InlineKeyboardButton("👑 Host Pooja — 🟢", callback_data="select_host_Pooja"),
        types.InlineKeyboardButton("💫 Host Riya — 🟢", callback_data="select_host_Riya"),
        types.InlineKeyboardButton("🌹 Host Kavya — 🟢", callback_data="select_host_Kavya"),
        types.InlineKeyboardButton("🦋 Host Aarti — 🟢", callback_data="select_host_Aarti")
    )
    
    text = (
        "✨ *VYNORA LIVE - HOST SELECTION*\n\n"
        f"💰 *Available Balance:* `{user_info['balance']} Minutes`\n\n"
        "👇 *Session ke liye host select karein:*"
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
        types.InlineKeyboardButton("⏱️ 30 Mins", callback_data=f"book_{host_name}_30")
    )
    text = f"👤 *Selected Host: {host_name}*\n\n👇 *Duration select karein:*"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("book_"))
def process_booking_click(call):
    user_id = call.from_user.id
    _, host_name, mins = call.data.split("_")
    mins = int(mins)
    
    user_info = get_user_data(user_id)
    if user_info['balance'] < mins:
        bot.answer_callback_query(call.id, f"❌ Balance Kam Hai! {mins} Mins chahiye.", show_alert=True)
        return
        
    deduct_user_balance(user_id, mins)
    log_session(user_id, host_name, mins)
    new_bal = user_info['balance'] - mins
    
    try:
        invite_link = bot.create_chat_invite_link(chat_id=HOST_GROUP_ID, member_limit=1).invite_link
    except Exception:
        invite_link = "https://t.me/+SamplePrivateLink123"
    
    text = (
        "🎉 *SESSION BOOKING SUCCESSFUL!*\n\n"
        f"👤 *Host:* {host_name}\n⏱️ *Duration:* {mins} Minutes\n"
        f"💰 *Remaining Balance:* `{new_bal} Mins`\n\n"
        "👇 *Private Room join karne ke liye button dabayein:*"
    )
    link_markup = types.InlineKeyboardMarkup()
    link_markup.add(types.InlineKeyboardButton("🔗 Join Private Session Now", url=invite_link))
    bot.send_message(user_id, text, reply_markup=link_markup)

# --- 11. RECHARGE PLAN & SCREENSHOT + UTR (AUTO PHOTO DELETE) ---
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
    bot.send_message(message.chat.id, "💳 *SELECT RECHARGE PLAN*", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("payplan_"))
def show_plan_qr(call):
    _, amount, mins = call.data.split("_")
    upi_url = f"upi://pay?pa={UPI_ID}&pn={urllib.parse.quote(PAYEE_NAME)}&am={amount}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={urllib.parse.quote(upi_url)}"
    
    caption = f"🎯 *SELECTED PLAN: ₹{amount} ({mins} Mins)*\n\n📍 *UPI ID:* `{UPI_ID}`\n💰 *Amount:* `₹{amount}`\n\n📲 *QR Code scan karke pay karein aur Screenshot bhejein.*"
    bot.send_photo(call.message.chat.id, qr_url, caption=caption)
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=['photo'])
def handle_screenshot(message):
    if message.chat.type == 'private':
        photo_id = message.photo[-1].file_id
        user_id = message.chat.id
        txn_id = f"TXN{int(time.time())}"
        
        msg = bot.send_message(user_id, "📸 *Screenshot Received!*\n\n👇 Ab apna 12-digit **UTR / UPI Reference Number** text mein type karke bhejein:")
        bot.register_next_step_handler(msg, process_utr_submission, photo_id, txn_id)

def process_utr_submission(message, photo_id, txn_id):
    user_id = message.chat.id
    utr_number = message.text.strip() if message.text else "N/A"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("5 Min (Rs.100)", callback_data=f"app_{user_id}_5_{txn_id}"),
        types.InlineKeyboardButton("10 Min (Rs.200)", callback_data=f"app_{user_id}_10_{txn_id}"),
        types.InlineKeyboardButton("20 Min (Rs.400)", callback_data=f"app_{user_id}_20_{txn_id}"),
        types.InlineKeyboardButton("30 Min (Rs.500)", callback_data=f"app_{user_id}_30_{txn_id}"),
        types.InlineKeyboardButton("90 Min (Rs.1000)", callback_data=f"app_{user_id}_90_{txn_id}"),
        types.InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user_id}_{txn_id}")
    )
    caption = f"📸 *NEW RECHARGE SCREENSHOT*\n\n👤 *User ID:* `{user_id}`\n👤 *Name:* {message.from_user.first_name}\n🔢 *UTR:* `{utr_number}`\n🔖 *TXN ID:* `{txn_id}`"
    sent_msg = bot.send_photo(ADMIN_GROUP_ID, photo_id, caption=caption, reply_markup=markup)
    
    pending_txns[txn_id] = {"user_id": user_id, "utr": utr_number, "msg_id": sent_msg.message_id}
    bot.send_message(user_id, f"⏳ *Verification Under Process!*\n• *UTR:* `{utr_number}`\nVerification ke baad balance add ho jayega.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(("app_", "rej_")))
def process_admin_recharge_approval(call):
    data = call.data.split("_")
    action, user_id = data[0], int(data[1])
    
    if action == "app":
        mins, txn_id = int(data[2]), data[3]
        utr = pending_txns.get(txn_id, {}).get("utr", "N/A")
        photo_msg_id = pending_txns.get(txn_id, {}).get("msg_id")
        
        add_user_balance(user_id, mins)
        
        # Delete Photo from Admin Group for Privacy
        if photo_msg_id:
            try:
                bot.delete_message(ADMIN_GROUP_ID, photo_msg_id)
            except Exception:
                pass
                
        # Keep Text Record in Admin Group
        bot.send_message(
            ADMIN_GROUP_ID, 
            f"✅ *PAYMENT APPROVED & ADDED*\n\n👤 *User ID:* `{user_id}`\n🔢 *UTR Number:* `{utr}`\n💰 *Credited:* `{mins} Mins`"
        )
        bot.send_message(user_id, f"✅ *Payment Approved!*\nAapke account mein *{mins} Minutes* add kar diye gaye hain.")
        bot.answer_callback_query(call.id, "Approved & Photo Removed!")
        
    elif action == "rej":
        txn_id = data[2]
        photo_msg_id = pending_txns.get(txn_id, {}).get("msg_id")
        utr = pending_txns.get(txn_id, {}).get("utr", "N/A")
        
        if photo_msg_id:
            try:
                bot.delete_message(ADMIN_GROUP_ID, photo_msg_id)
            except Exception:
                pass
                
        bot.send_message(ADMIN_GROUP_ID, f"❌ *PAYMENT REJECTED*\n👤 User ID: `{user_id}`\n🔢 UTR: `{utr}`")
        bot.send_message(user_id, "❌ Aapka payment verification reject ho gaya hai.")
        bot.answer_callback_query(call.id, "Rejected!")

# --- 12. BALANCE, PROFILE & ADMIN STATS ---
@bot.message_handler(func=lambda msg: msg.text in ["My Balance & Referral", "💰 My Balance & Referral"])
def show_balance(message):
    user_id = message.chat.id
    user_info = get_user_data(user_id)
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start={user_id}"
    bot.send_message(message.chat.id, f"💰 *Account Balance*\n\n• Available: *{user_info['balance']} Minutes*\n\n🔗 *Referral Link:*\n`{ref_link}`")

@bot.message_handler(func=lambda msg: msg.text in ["Register / Profile", "📝 Register / Profile"])
def register_profile(message):
    user_id = message.chat.id
    user_info = get_user_data(user_id)
    if user_info['phone']:
        bot.send_message(message.chat.id, f"👤 *PROFILE DETAILS*\n\n• *Name:* `{user_info['name']}`\n• *Phone:* `{user_info['phone']}`\n• *Status:* ✅ Verified User")
    else:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton("📱 Share Phone Number (1-Click)", request_contact=True))
        bot.send_message(message.chat.id, "📝 Account verify karne ke liye button par click karein:", reply_markup=markup)

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    if message.contact:
        user_id = message.chat.id
        save_user_profile(user_id, message.from_user.first_name, message.contact.phone_number)
        bot.send_message(user_id, "🎉 *Registration Complete!*", reply_markup=get_main_keyboard())

@bot.message_handler(commands=['stats'])
def check_stats(message):
    users = get_all_db_users()
    bot.send_message(message.chat.id, f"📊 *VYNORA STATS*\n\n👤 *Total Users:* `{len(users)}`\n⏱️ *Total Active Balance:* `{sum([u[3] for u in users])} Mins`")

@bot.message_handler(commands=['allusers'])
def list_users(message):
    users = get_all_db_users()
    if not users:
        bot.send_message(message.chat.id, "❌ Koi user nahi hai.")
        return
    text = "📋 *REGISTERED USERS DATABASE*\n\n"
    for u in users:
        text += f"• *ID:* `{u[0]}` | *Name:* {u[1] or 'N/A'} | *Phone:* `{u[2] or 'N/A'}` | *Bal:* `{u[3]} Mins`\n"
    bot.send_message(message.chat.id, text)

if __name__ == '__main__':
    print("Vynora Bot Live with All Features Dynamic...")
    try:
        bot.remove_webhook()
    except Exception:
        pass
    bot.infinity_polling(skip_pending=True)
