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
    # Hosts Slot Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS host_assignments (
            user_id INTEGER PRIMARY KEY,
            slot_name TEXT UNIQUE,
            status TEXT DEFAULT 'APPROVED'
        )
    ''')
    # Sessions History Table
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

def auto_register_user(user_id, name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, name, balance) VALUES (?, ?, 0)
        ON CONFLICT(user_id) DO UPDATE SET name = ?
    ''', (user_id, name, name))
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

def save_user_phone(user_id, phone):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET phone = ? WHERE user_id = ?", (phone, user_id))
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

def get_assigned_hosts():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, slot_name FROM host_assignments WHERE status = 'APPROVED'")
    rows = cursor.fetchall()
    conn.close()
    return {row[1]: row[0] for row in rows}

def assign_host_slot(user_id, slot_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO host_assignments (user_id, slot_name, status) VALUES (?, ?, 'APPROVED')
        ON CONFLICT(user_id) DO UPDATE SET slot_name = ?, status = 'APPROVED'
    ''', (user_id, slot_name, slot_name))
    conn.commit()
    conn.close()

init_db()

# Pending Transaction & Selected Plan Cache
pending_txns = {}
user_selected_plan = {}

# --- 3. BOT CONFIGURATION & ENVIRONMENT VARIABLES ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.environ.get("ADMIN_GROUP_ID", "-1004325621712"))

# TOTAL 8 HOST GROUPS
HOST_GROUPS = {
    "Host Priya 01": int(os.environ.get("GROUP_PRIYA_01", "-1004312344325")),
    "Host Ananya 02": int(os.environ.get("GROUP_ANANYA_02", "-1004330981781")),
    "Host Simran 03": int(os.environ.get("GROUP_SIMRAN_03", "-1004350353315")),
    "Host Neha 04": int(os.environ.get("GROUP_NEHA_04", "-1003939071012")),
    "Host Pooja 05": int(os.environ.get("GROUP_POOJA_05", "-1004293963082")),
    "Host Riya 06": int(os.environ.get("GROUP_RIYA_06", "-1004459506130")),
    "Host Kavya 07": int(os.environ.get("GROUP_KAVYA_07", "-1004459506131")),
    "Host Sneha 08": int(os.environ.get("GROUP_SNEHA_08", "-1004459506132"))
}

# 6 ONLINE HOSTS LIST (6 Online & 2 Offline)
ONLINE_HOSTS = [
    "Host Priya 01",
    "Host Ananya 02",
    "Host Simran 03",
    "Host Neha 04",
    "Host Pooja 05",
    "Host Riya 06"
]

UPI_ID = os.environ.get("UPI_ID", "vynoralive@slc")
PAYEE_NAME = os.environ.get("PAYEE_NAME", "Rajnish Kumar")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# --- AUTO-KICK TIMER FUNCTION ---
def auto_kick_timer(chat_id, user_id, mins):
    time.sleep(mins * 60)
    try:
        bot.ban_chat_member(chat_id, user_id)
        bot.unban_chat_member(chat_id, user_id)
        bot.send_message(user_id, f"⏰ *SESSION TIME EXPIRED!*\nAapka `{mins} Mins` ka session khatam ho gaya hai.")
    except Exception as e:
        print(f"Auto-kick error: {e}")

# --- CLEAN 4-BUTTON DYNAMIC KEYBOARD ---
def get_main_keyboard(user_id=None):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton("🔥 Book Host Session")
    
    pay_btn_text = "💳 Recharge Minutes"
    if user_id:
        u_data = get_user_data(user_id)
        if u_data['balance'] > 0:
            pay_btn_text = "💼 Wallet / Balance"
            
    btn2 = types.KeyboardButton(pay_btn_text)
    btn3 = types.KeyboardButton("👤 Profile & Referral")
    btn4 = types.KeyboardButton("🆘 Help & Tutorial")
    
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)
    return markup

# --- 4. START COMMAND (Auto-Registration) ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.chat.id
    name = message.from_user.first_name
    
    # Automatic registration in DB
    auto_register_user(user_id, name)
    
    bot.send_message(
        user_id, 
        f"✨ *Welcome to Vynora Live Official Bot!*\n\nNamaste *{name}*, niche diye gaye menu se service chunein:", 
        reply_markup=get_main_keyboard(user_id)
    )

# --- 5. BOOK HOST SESSION (With Mandatory Phone Verification) ---
@bot.message_handler(func=lambda msg: msg.text in ["Book Host Session", "🔥 Book Host Session"])
def book_host(message):
    user_id = message.chat.id
    user_info = get_user_data(user_id)
    
    # Check Phone Registration
    if not user_info['phone']:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton("📱 Share Phone Number (1-Click)", request_contact=True))
        bot.send_message(user_id, "⚠️ *Phone Registration Required!*\n\nSession book karne ke liye kripya niche button par click karke pehle apna contact share karein:", reply_markup=markup)
        return
        
    markup = types.InlineKeyboardMarkup(row_width=1)
    for slot_name in HOST_GROUPS.keys():
        if slot_name in ONLINE_HOSTS:
            markup.add(types.InlineKeyboardButton(f"🟢 {slot_name} (Online)", callback_data=f"select_host_{slot_name}"))
        else:
            markup.add(types.InlineKeyboardButton(f"🔴 {slot_name} (Offline)", callback_data="host_offline"))
            
    text = (
        "✨ *VYNORA LIVE - HOST SELECTION*\n\n"
        f"💰 *Available Balance:* `{user_info['balance']} Minutes`\n\n"
        "👇 *Session ke liye active host select karein:*"
    )
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    if message.contact:
        user_id = message.chat.id
        save_user_phone(user_id, message.contact.phone_number)
        bot.send_message(user_id, "🎉 *Registration Complete!* Ab aap Session Book kar sakte hain.", reply_markup=get_main_keyboard(user_id))

@bot.callback_query_handler(func=lambda call: call.data == "host_offline")
def alert_host_offline(call):
    bot.answer_callback_query(call.id, "⚠️ Yeh Host abhi offline hai. Kripya Online Host chunnein!", show_alert=True)

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
    text = f"👤 *Selected Host:* `{host_name}`\n\n👇 *Duration select karein:*"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("book_"))
def process_booking_click(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    host_name, mins = parts[1], int(parts[2])
    
    user_info = get_user_data(user_id)
    if user_info['balance'] < mins:
        bot.answer_callback_query(call.id, f"❌ Balance Kam Hai! {mins} Mins chahiye.", show_alert=True)
        return
        
    deduct_user_balance(user_id, mins)
    log_session(user_id, host_name, mins)
    new_bal = user_info['balance'] - mins
    
    target_group_id = HOST_GROUPS.get(host_name)
    
    try:
        invite_link = bot.create_chat_invite_link(chat_id=target_group_id, member_limit=1).invite_link
    except Exception as e:
        invite_link = "https://t.me/+SamplePrivateLink123"
        print(f"Error creating invite link: {e}")
    
    threading.Thread(target=auto_kick_timer, args=(target_group_id, user_id, mins), daemon=True).start()
    
    text = (
        "🎉 *SESSION BOOKING SUCCESSFUL!*\n\n"
        f"👤 *Selected Host:* `{host_name}`\n"
        f"⏱️ *Duration:* `{mins} Minutes`\n"
        f"💰 *Remaining Balance:* `{new_bal} Mins`\n\n"
        "🔒 *Note:* Invite link 1-time single use hai. Time khatam hote hi bot aapko auto-kick kar dega.\n\n"
        "👇 *Private Room Join Karein:*"
    )
    link_markup = types.InlineKeyboardMarkup()
    link_markup.add(types.InlineKeyboardButton("🔗 Join Private Session Now", url=invite_link))
    bot.send_message(user_id, text, reply_markup=link_markup)
    
    admin_private_log = (
        "📊 *NEW PRIVATE SESSION BOOKED*\n─────────────────────────\n"
        f"👤 *User ID:* `{user_id}`\n"
        f"👤 *User Name:* {call.from_user.first_name}\n"
        f"💃 *Booked Host:* `{host_name}`\n"
        f"⏱️ *Duration:* `{mins} Minutes`\n"
        f"💰 *User Left Balance:* `{new_bal} Mins`"
    )
    bot.send_message(ADMIN_GROUP_ID, admin_private_log)

# --- 6. RECHARGE & PLAN DETAILS IN ADMIN ALERT ---
@bot.message_handler(func=lambda msg: msg.text in ["💳 Recharge Minutes", "Recharge Minutes", "💼 Wallet / Balance", "Wallet / Balance"])
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
    user_selected_plan[call.message.chat.id] = f"₹{amount} ({mins} Mins)"
    
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
    selected_plan = user_selected_plan.get(user_id, "Custom / Not Selected")
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("5 Min (Rs.100)", callback_data=f"app_{user_id}_5_{txn_id}"),
        types.InlineKeyboardButton("10 Min (Rs.200)", callback_data=f"app_{user_id}_10_{txn_id}"),
        types.InlineKeyboardButton("20 Min (Rs.400)", callback_data=f"app_{user_id}_20_{txn_id}"),
        types.InlineKeyboardButton("30 Min (Rs.500)", callback_data=f"app_{user_id}_30_{txn_id}"),
        types.InlineKeyboardButton("90 Min (Rs.1000)", callback_data=f"app_{user_id}_90_{txn_id}"),
        types.InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user_id}_{txn_id}")
    )
    caption = (
        f"📸 *NEW RECHARGE SCREENSHOT*\n\n"
        f"👤 *User ID:* `{user_id}`\n"
        f"👤 *Name:* {message.from_user.first_name}\n"
        f"🎯 *Selected Plan:* `{selected_plan}`\n"
        f"🔢 *UTR:* `{utr_number}`\n"
        f"🔖 *TXN ID:* `{txn_id}`"
    )
    sent_msg = bot.send_photo(ADMIN_GROUP_ID, photo_id, caption=caption, reply_markup=markup)
    pending_txns[txn_id] = {"user_id": user_id, "utr": utr_number, "msg_id": sent_msg.message_id}
    bot.send_message(user_id, f"⏳ *Verification Under Process!*\n• *Plan:* `{selected_plan}`\n• *UTR:* `{utr_number}`\nVerification ke baad balance credit ho jayega.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(("app_", "rej_")))
def process_admin_recharge_approval(call):
    data = call.data.split("_")
    action, user_id = data[0], int(data[1])
    
    if action == "app":
        mins, txn_id = int(data[2]), data[3]
        utr = pending_txns.get(txn_id, {}).get("utr", "N/A")
        photo_msg_id = pending_txns.get(txn_id, {}).get("msg_id")
        
        add_user_balance(user_id, mins)
        
        if photo_msg_id:
            try:
                bot.delete_message(ADMIN_GROUP_ID, photo_msg_id)
            except Exception:
                pass
                
        bot.send_message(ADMIN_GROUP_ID, f"✅ *PAYMENT APPROVED*\n👤 User ID: `{user_id}`\n🔢 UTR: `{utr}`\n💰 Credited: `{mins} Mins`")
        bot.send_message(user_id, f"✅ *Payment Approved!*\nAapke account mein *{mins} Minutes* add kar diye gaye hain.", reply_markup=get_main_keyboard(user_id))
        bot.answer_callback_query(call.id, "Approved!")
        
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

# --- 7. PROFILE, REFERRAL & HOST OPTIONS ---
@bot.message_handler(func=lambda msg: msg.text in ["Profile & Referral", "👤 Profile & Referral"])
def profile_and_ref(message):
    user_id = message.chat.id
    user_info = get_user_data(user_id)
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start={user_id}"
    
    profile_card = (
        "👤 *VYNORA USER PROFILE*\n─────────────────────────\n"
        f"🆔 *User ID:* `{user_id}`\n"
        f"📛 *Name:* `{user_info['name'] or message.from_user.first_name}`\n"
        f"📱 *Phone:* `{user_info['phone'] or 'Not Registered'}`\n"
        f"💎 *Available Balance:* `{user_info['balance']} Mins`\n\n"
        f"🔗 *Your Referral Link:*\n`{ref_link}`\n"
        "─────────────────────────"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👑 Register as Host", callback_data="action_reghost"),
        types.InlineKeyboardButton("💸 Host Withdrawal", callback_data="action_withdraw")
    )
    bot.send_message(user_id, profile_card, reply_markup=markup)

# --- 8. HELP & TUTORIAL ---
@bot.message_handler(func=lambda msg: msg.text in ["Help & Tutorial", "🆘 Help & Tutorial"])
def help_and_tutorial(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🎬 Watch Tutorial", callback_data="show_tutorial"),
        types.InlineKeyboardButton("📜 Host Policy", callback_data="show_policy"),
        types.InlineKeyboardButton("💬 Admin Support", url="https://t.me/VynoraSupport")
    )
    bot.send_message(message.chat.id, "🆘 *HELP & SUPPORT CENTER*\n\nNiche kisi bhi option par click karein:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["show_tutorial", "show_policy", "action_reghost", "action_withdraw"])
def handle_profile_help_actions(call):
    user_id = call.message.chat.id
    
    if call.data == "show_tutorial":
        tutorial_text = (
            "🎬 *VYNORA LIVE TUTORIAL*\n\n"
            "1️⃣ *Recharge Minutes:* Plan select karke QR code scan karein aur UTR number bhejein.\n"
            "2️⃣ *Book Session:* Online host aur Duration chunein.\n"
            "3️⃣ *Private Call:* Bot dwara mile Single-User link se group join karein."
        )
        bot.send_message(user_id, tutorial_text)
        
    elif call.data == "show_policy":
        policy_text = (
            "📜 *HOST WORKING POLICY*\n\n"
            "• **Earning Split:** 70% Host Wallet / 30% Platform Fee.\n"
            "• **Limits:** Daily Min 500 Mins & Max 5000 Mins withdrawal.\n"
            "• **Payout Time:** 12 to 24 Hours."
        )
        bot.send_message(user_id, policy_text)
        
    elif call.data == "action_reghost":
        msg = bot.send_message(user_id, "👑 *BECOME A HOST*\n\nStep 1/4: Apna **Full Name & Age** type karke bhejein:")
        bot.register_next_step_handler(msg, process_host_name)
        
    elif call.data == "action_withdraw":
        start_withdrawal(call.message)
        
    bot.answer_callback_query(call.id)

# --- 9. HOST REGISTRATION & WITHDRAWALS ---
def process_host_name(message):
    user_id = message.chat.id
    name_age = message.text.strip() if message.text else "N/A"
    msg = bot.send_message(user_id, f"✅ *Name Recorded:* `{name_age}`\n\nStep 2/4: Apna **Calling Phone Number** enter karein:")
    bot.register_next_step_handler(msg, process_host_phone, name_age)

def process_host_phone(message, name_age):
    user_id = message.chat.id
    phone = message.text.strip() if message.text else "N/A"
    msg = bot.send_message(user_id, f"✅ *Phone Recorded:* `{phone}`\n\nStep 3/4: Apna **WhatsApp Number** enter karein:")
    bot.register_next_step_handler(msg, process_host_whatsapp, name_age, phone)

def process_host_whatsapp(message, name_age, phone):
    user_id = message.chat.id
    whatsapp = message.text.strip() if message.text else "N/A"
    msg = bot.send_message(user_id, f"✅ *WhatsApp Recorded:* `{whatsapp}`\n\nStep 4/4: Apna **Telegram Username** enter karein:")
    bot.register_next_step_handler(msg, process_host_tg, name_age, phone, whatsapp)

def process_host_tg(message, name_age, phone, whatsapp):
    user_id = message.chat.id
    tg_id = message.text.strip() if message.text else "N/A"
    bot.send_message(user_id, "🎉 *HOST APPLICATION SUBMITTED!* Verification ke baad aapko notification mil jayega.")
    
    admin_markup = types.InlineKeyboardMarkup(row_width=2)
    admin_markup.add(
        types.InlineKeyboardButton("✅ Approve Host", callback_data=f"hostapp_{user_id}"),
        types.InlineKeyboardButton("❌ Reject Host", callback_data=f"hostrej_{user_id}")
    )
    admin_card = f"👑 *NEW HOST APPLICATION*\n\n👤 *ID:* `{user_id}`\n👤 *Name:* `{name_age}`\n📞 *Phone:* `{phone}`\n💬 *WhatsApp:* `{whatsapp}`\n📲 *TG:* `{tg_id}`"
    bot.send_message(ADMIN_GROUP_ID, admin_card, reply_markup=admin_markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith(("hostapp_", "hostrej_")))
def handle_host_approval(call):
    data = call.data.split("_")
    action, applicant_id = data[0], int(data[1])
    
    if action == "hostapp":
        assigned = get_assigned_hosts()
        vacant_slots = [s for s in HOST_GROUPS.keys() if s not in assigned]
        if not vacant_slots:
            bot.answer_callback_query(call.id, "❌ Koi Host Slot khaali nahi hai!", show_alert=True)
            return
            
        assigned_slot = vacant_slots[0]
        assign_host_slot(applicant_id, assigned_slot)
        group_id = HOST_GROUPS[assigned_slot]
        
        try:
            host_invite_link = bot.create_chat_invite_link(chat_id=group_id, member_limit=1).invite_link
        except Exception:
            host_invite_link = "https://t.me/+SampleHostGroupLink"

        bot.send_message(applicant_id, f"🎉 *APPLICATION APPROVED!*\n👑 *Slot:* `{assigned_slot}`\n🔗 *Join Group:* {host_invite_link}")
        bot.edit_message_text(f"✅ *HOST APPROVED*\nUser `{applicant_id}` -> Slot *{assigned_slot}*", ADMIN_GROUP_ID, call.message.message_id)
        bot.answer_callback_query(call.id, "Approved!")
    elif action == "hostrej":
        bot.send_message(applicant_id, "❌ *APPLICATION REJECTED*")
        bot.edit_message_text(f"❌ *HOST REJECTED*\nUser ID `{applicant_id}`", ADMIN_GROUP_ID, call.message.message_id)
        bot.answer_callback_query(call.id, "Rejected!")

def start_withdrawal(message):
    user_id = message.chat.id
    user_info = get_user_data(user_id)
    balance = user_info['balance']
    
    if balance < 500:
        bot.send_message(user_id, f"❌ *Withdrawal Reject!*\n💰 Current Balance: `{balance} Mins`\n⚠️ Minimum withdrawal 500 Mins hai.")
        return

    msg = bot.send_message(user_id, f"💳 *HOST WITHDRAWAL*\n💰 Balance: `{balance} Mins` (Min: 500 | Max: 5000)\n\n👇 Kitne Mins withdraw karne hain enter karein:")
    bot.register_next_step_handler(msg, process_withdraw_amount, balance)

def process_withdraw_amount(message, total_balance):
    user_id = message.chat.id
    amount_text = message.text.strip() if message.text else ""
    
    if not amount_text.isdigit() or int(amount_text) < 500 or int(amount_text) > 5000 or int(amount_text) > total_balance:
        msg = bot.send_message(user_id, "❌ Invalid Amount! Limits (500-5000 Mins) ke andar daalein:")
        bot.register_next_step_handler(msg, process_withdraw_amount, total_balance)
        return

    amount = int(amount_text)
    msg = bot.send_message(user_id, f"✅ Validated: `{amount} Mins`\n\n📲 Apna **UPI ID** type karke bhejein:")
    bot.register_next_step_handler(msg, process_withdraw_upi, amount)

def process_withdraw_upi(message, amount):
    user_id = message.chat.id
    upi_id = message.text.strip()
    
    deduct_user_balance(user_id, amount)
    bot.send_message(user_id, f"🎉 *WITHDRAWAL REQUEST SUBMITTED!*\n💵 Amount: `{amount} Mins`\n📍 UPI: `{upi_id}`")
    
    admin_alert = f"💸 *HOST WITHDRAWAL REQUEST*\n\n👤 Host ID: `{user_id}`\n💰 Mins: `{amount}`\n📲 UPI ID: `{upi_id}`"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Mark Paid", callback_data=f"payout_done_{user_id}_{amount}"))
    bot.send_message(ADMIN_GROUP_ID, admin_alert, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("payout_done_"))
def admin_payout_complete(call):
    _, _, user_id, amount = call.data.split("_")
    bot.edit_message_text(f"✅ *PAID & COMPLETED*\nHost ID `{user_id}` -> `{amount} Mins`", ADMIN_GROUP_ID, call.message.message_id)
    bot.send_message(int(user_id), f"🔔 *PAYMENT SUCCESSFUL!*\nAapka `{amount} Mins` ka payout transfer ho gaya hai.")
    bot.answer_callback_query(call.id, "Paid!")

# --- 10. ADMIN COMMANDS ---
@bot.message_handler(commands=['user'])
def inspect_user(message):
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        bot.send_message(message.chat.id, "⚠️ Usage: `/user <user_id>`")
        return
    u_data = get_user_data(int(args[1]))
    bot.send_message(message.chat.id, f"🔍 *USER DATA:* `{args[1]}`\n👤 Name: `{u_data['name']}`\n📞 Phone: `{u_data['phone']}`\n💰 Balance: `{u_data['balance']} Mins`")

@bot.message_handler(commands=['addbal'])
def add_balance_manual(message):
    args = message.text.split()
    if len(args) < 3 or not args[1].isdigit():
        bot.send_message(message.chat.id, "⚠️ Usage: `/addbal <user_id> <mins>`")
        return
    add_user_balance(int(args[1]), int(args[2]))
    bot.send_message(message.chat.id, f"✅ Account `{args[1]}` ka balance `{args[2]} Mins` update kar diya gaya.")

@bot.message_handler(commands=['stats'])
def check_stats(message):
    users = get_all_db_users()
    bot.send_message(message.chat.id, f"📊 *STATS*\nTotal Users: `{len(users)}` | Total Balance: `{sum([u[3] for u in users])} Mins`")

# --- MAIN RUNNER ---
if __name__ == '__main__':
    print("Vynora Bot Live with Fully Clean Layout...")
    try:
        bot.remove_webhook()
    except Exception:
        pass
    bot.infinity_polling(skip_pending=True)
