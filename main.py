import os
import time
import sqlite3
import urllib.parse
import threading
import telebot
from telebot import types
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- 1. WEB SERVICE PORT BINDING ---
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            phone TEXT,
            balance INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS host_assignments (
            user_id INTEGER PRIMARY KEY,
            slot_name TEXT UNIQUE,
            status TEXT DEFAULT 'ONLINE'
        )
    ''')
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

def set_user_balance(user_id, mins):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, balance) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET balance = ?
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
    cursor.execute('''
        INSERT INTO users (user_id, phone, balance) VALUES (?, ?, 0)
        ON CONFLICT(user_id) DO UPDATE SET phone = ?
    ''', (user_id, phone, phone))
    conn.commit()
    conn.close()

def log_session(user_id, host_name, duration):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions (user_id, host_name, duration) VALUES (?, ?, ?)", (user_id, host_name, duration))
    conn.commit()
    conn.close()

def get_host_worked_mins(host_user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT slot_name FROM host_assignments WHERE user_id = ?", (host_user_id,))
    slot_row = cursor.fetchone()
    if not slot_row:
        conn.close()
        return 0, None
    slot_name = slot_row[0]
    cursor.execute("SELECT SUM(duration) FROM sessions WHERE host_name = ?", (slot_name,))
    sum_row = cursor.fetchone()
    conn.close()
    total_worked = sum_row[0] if sum_row and sum_row[0] else 0
    return total_worked, slot_name

def get_user_call_history(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT host_name, COUNT(*), SUM(duration) 
        FROM sessions 
        WHERE user_id = ? 
        GROUP BY host_name
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

def assign_host_slot(user_id, slot_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO host_assignments (user_id, slot_name, status) VALUES (?, ?, 'ONLINE')
        ON CONFLICT(user_id) DO UPDATE SET slot_name = ?, status = 'ONLINE'
    ''', (user_id, slot_name, slot_name))
    conn.commit()
    conn.close()

def update_host_status(user_id, status):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE host_assignments SET status = ? WHERE user_id = ?", (status, user_id))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_hosts_status_map():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT slot_name, status FROM host_assignments")
    rows = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}

init_db()

# Caches
pending_txns = {}
user_selected_plan = {}

# --- 3. BOT CONFIGURATION ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.environ.get("ADMIN_GROUP_ID", "-1004325621712"))

HOST_GROUPS = {
    "Host Priya 01": int(os.environ.get("GROUP_PRIYA_01", "-1004312344325")),
    "Host Ananya 02": int(os.environ.get("GROUP_ANANYA_02", "-1004330981781"))
}

UPI_ID = os.environ.get("UPI_ID", "vynoralive@slc")
PAYEE_NAME = os.environ.get("PAYEE_NAME", "Rajnish Kumar")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# --- SAFE INVITE LINK & KICK TIMER ---
def generate_safe_invite_link(group_id, user_id):
    try:
        link_obj = bot.create_chat_invite_link(chat_id=group_id, member_limit=1)
        return link_obj.invite_link
    except Exception as e:
        print(f"Invite Link Error: {e}")
        bot.send_message(ADMIN_GROUP_ID, f"🚨 *INVITE LINK ERROR!*\nGroup `{group_id}` me Bot permissions check karein.")
        return None

def auto_kick_timer(chat_id, user_id, mins):
    time.sleep(mins * 60)
    try:
        bot.ban_chat_member(chat_id, user_id)
        bot.unban_chat_member(chat_id, user_id)
        bot.send_message(user_id, f"⏰ *SESSION TIME EXPIRED!*\nAapka `{mins} Mins` ka session khatam ho gaya hai.")
    except Exception as e:
        print(f"Kick Error: {e}")

# --- MAIN KEYBOARD MENU WITH HOST DASHBOARD ---
def get_main_keyboard(user_id=None):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton("🔥 Book Host Session")
    btn2 = types.KeyboardButton("💳 Recharge Minutes")
    btn3 = types.KeyboardButton("👑 Host Earnings")
    btn4 = types.KeyboardButton("👤 Profile & Referral")
    btn5 = types.KeyboardButton("🆘 Help & Tutorial")
    
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)
    markup.add(btn5)
    return markup

# --- 4. START COMMAND ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.chat.id
    name = message.from_user.first_name
    auto_register_user(user_id, name)
    bot.send_message(
        user_id, 
        f"✨ *Welcome to Vynora Live Official Bot!*\n\nNamaste *{name}*, niche diye gaye menu se service chunein:", 
        reply_markup=get_main_keyboard(user_id)
    )

# --- DIRECT HOST ASSIGNMENT COMMAND FOR ADMIN ---
@bot.message_handler(commands=['sethost'])
def set_host_direct(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        bot.send_message(message.chat.id, "⚠️ Usage: `/sethost <user_id> <Host Slot Name>`\n*Example:* `/sethost 1108685585 Host Priya 01`")
        return
        
    target_user = int(args[1])
    slot_name = args[2].strip()
    
    assign_host_slot(target_user, slot_name)
    bot.send_message(ADMIN_GROUP_ID, f"✅ *HOST LINKED SUCCESSFULLY!*\n👤 User ID: `{target_user}`\n👑 Slot Name: `{slot_name}`")
    try:
        bot.send_message(target_user, f"🎉 *CONGRATULATIONS!*\nAapko `{slot_name}` slot assign kar diya gaya hai. Ab aap `/balance` ya **👑 Host Earnings** button se apni earning check kar sakti hain.")
    except Exception:
        pass

# --- 5. HOST BALANCE & EARNINGS POPUP BUTTON ---
@bot.message_handler(func=lambda msg: msg.text in ["👑 Host Earnings", "Host Earnings", "/balance", "/earnings"])
def check_balance_earnings(message):
    user_id = message.chat.id
    user_info = get_user_data(user_id)
    worked_mins, slot_name = get_host_worked_mins(user_id)

    if not slot_name:
        msg = (
            "⚠️ *HOST NOT REGISTERED*\n─────────────────────────\n"
            f"👤 *User ID:* `{user_id}`\n"
            f"💎 *User Wallet Balance:* `{user_info['balance']} Mins`\n\n"
            "📌 *Note:* Aap abhi Host Slot se linked nahi hain. Host banne ke liye Profile section me **Register as Host** par click karein ya Admin se contact karein."
        )
        bot.send_message(user_id, msg)
        return

    net_earnings_inr = round(worked_mins * 0.70, 2)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🟢 Go Online", callback_data="host_cmd_online"),
        types.InlineKeyboardButton("🔴 Go Offline", callback_data="host_cmd_offline")
    )
    markup.add(
        types.InlineKeyboardButton("💸 Withdraw (₹700 - ₹3000)", callback_data="action_withdraw")
    )

    msg = f"👑 *HOST DASHBOARD & EARNINGS*\n─────────────────────────\n"
    msg += f"👤 *Host ID:* `{user_id}`\n"
    msg += f"💃 *Assigned Slot:* `{slot_name}`\n"
    msg += f"⏱️ *Total Worked:* `{worked_mins} Minutes`\n"
    msg += f"💵 *Net INR Earnings (30% Cut):* `₹{net_earnings_inr}`\n"
    msg += "─────────────────────────\n"
    msg += "👇 *Status update ya withdrawal ke liye niche button click karein:*"

    bot.send_message(user_id, msg, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["host_cmd_online", "host_cmd_offline"])
def inline_host_status_change(call):
    user_id = call.message.chat.id
    if call.data == "host_cmd_online":
        update_host_status(user_id, 'ONLINE')
        bot.answer_callback_query(call.id, "🟢 Status: ONLINE", show_alert=True)
    else:
        update_host_status(user_id, 'OFFLINE')
        bot.answer_callback_query(call.id, "🔴 Status: OFFLINE", show_alert=True)

# --- 6. BOOK HOST SESSION ---
@bot.message_handler(func=lambda msg: msg.text in ["Book Host Session", "🔥 Book Host Session"])
def book_host(message):
    user_id = message.chat.id
    user_info = get_user_data(user_id)
    
    if not user_info['phone']:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton("📱 Share Phone Number (1-Click)", request_contact=True))
        bot.send_message(user_id, "⚠️ *Phone Registration Required!*\n\nSession book karne ke liye kripya button par click karke apna contact share karein:", reply_markup=markup)
        return

    if user_info['balance'] <= 0:
        bot.send_message(
            user_id, 
            "⚠️ *Insufficient Balance!*\n\nAapka balance **0 Mins** hai. Session book karne ke liye pehle `💳 Recharge Minutes` par click karke recharge karein.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
        
    status_map = get_hosts_status_map()
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for slot_name in HOST_GROUPS.keys():
        current_status = status_map.get(slot_name, 'ONLINE')
        if current_status == 'ONLINE':
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
        if message.contact.user_id != message.from_user.id:
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add(types.KeyboardButton("📱 Share Phone Number (1-Click)", request_contact=True))
            bot.send_message(user_id, "❌ *Security Error:* Apna original SIM number share karein.", reply_markup=markup)
            return

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
        
    target_group_id = HOST_GROUPS.get(host_name)
    invite_link = generate_safe_invite_link(target_group_id, user_id)
    
    if not invite_link:
        bot.send_message(user_id, "⚠️ Technical Issue ke karan link generate nahi ho paya.")
        return

    deduct_user_balance(user_id, mins)
    log_session(user_id, host_name, mins)
    new_bal = user_info['balance'] - mins
    
    threading.Thread(target=auto_kick_timer, args=(target_group_id, user_id, mins), daemon=True).start()
    
    text = (
        "🎉 *SESSION BOOKING SUCCESSFUL!*\n\n"
        f"👤 *Selected Host:* `{host_name}`\n"
        f"⏱️ *Duration:* `{mins} Minutes`\n"
        f"💰 *Remaining Balance:* `{new_bal} Mins`\n\n"
        "👇 *Private Room Join Karein:*"
    )
    link_markup = types.InlineKeyboardMarkup()
    link_markup.add(types.InlineKeyboardButton("🔗 Join Private Session Now", url=invite_link))
    bot.send_message(user_id, text, reply_markup=link_markup)
    
    # Notifications
    bot.send_message(ADMIN_GROUP_ID, f"📊 *NEW BOOKING*\n👤 User: `{user_id}`\n💃 Host: `{host_name}`\n⏱️ Duration: `{mins} Mins`")
    bot.send_message(target_group_id, f"🔔🔔 *CALL BOOKED!* `{host_name}` -> Duration: `{mins} Mins`", disable_notification=False)

# --- 7. RECHARGE & PAYMENT APPROVAL ---
@bot.message_handler(func=lambda msg: msg.text in ["💳 Recharge Minutes", "Recharge Minutes"])
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
        f"🎯 *Selected Plan:* `{selected_plan}`\n"
        f"🔢 *UTR:* `{utr_number}`\n"
        f"🔖 *TXN ID:* `{txn_id}`"
    )
    sent_msg = bot.send_photo(ADMIN_GROUP_ID, photo_id, caption=caption, reply_markup=markup)
    pending_txns[txn_id] = {"user_id": user_id, "utr": utr_number, "msg_id": sent_msg.message_id}
    bot.send_message(user_id, f"⏳ *Verification Under Process!*\n• *Plan:* `{selected_plan}`\n• *UTR:* `{utr_number}`")

@bot.callback_query_handler(func=lambda call: call.data.startswith(("app_", "rej_")))
def process_admin_recharge_approval(call):
    data = call.data.split("_")
    action, user_id = data[0], int(data[1])
    
    if action == "app":
        mins, txn_id = int(data[2]), data[3]
        photo_msg_id = pending_txns.get(txn_id, {}).get("msg_id")
        add_user_balance(user_id, mins)
        if photo_msg_id:
            try: bot.delete_message(ADMIN_GROUP_ID, photo_msg_id)
            except Exception: pass
                
        bot.send_message(ADMIN_GROUP_ID, f"✅ *PAYMENT APPROVED*\n👤 User ID: `{user_id}`\n💰 Credited: `{mins} Mins`")
        bot.send_message(user_id, f"✅ *Payment Approved!*\nAapke account mein *{mins} Minutes* add kar diye gaye hain.", reply_markup=get_main_keyboard(user_id))
        
    elif action == "rej":
        txn_id = data[2]
        photo_msg_id = pending_txns.get(txn_id, {}).get("msg_id")
        if photo_msg_id:
            try: bot.delete_message(ADMIN_GROUP_ID, photo_msg_id)
            except Exception: pass
        bot.send_message(user_id, "❌ Aapka payment verification reject ho gaya hai.")

# --- 8. PROFILE, REFERRAL & WITHDRAWALS ---
@bot.message_handler(func=lambda msg: msg.text in ["Profile & Referral", "👤 Profile & Referral"])
def profile_and_ref(message):
    user_id = message.chat.id
    user_info = get_user_data(user_id)
    worked_mins, slot_name = get_host_worked_mins(user_id)
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start={user_id}"
    
    profile_card = (
        "👤 *VYNORA USER PROFILE*\n─────────────────────────\n"
        f"🆔 *User ID:* `{user_id}`\n"
        f"📛 *Name:* `{user_info['name'] or message.from_user.first_name}`\n"
        f"📱 *Phone:* `{user_info['phone'] or 'Not Registered'}`\n"
        f"💎 *Wallet Balance:* `{user_info['balance']} Mins`\n"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)

    if slot_name:
        net_inr = round(worked_mins * 0.70, 2)
        profile_card += f"👑 *Host Slot:* `{slot_name}`\n"
        profile_card += f"📊 *Total Worked Mins:* `{worked_mins} Mins`\n"
        profile_card += f"💵 *Net Balance (30% Cut):* `₹{net_inr}`\n"
        markup.add(
            types.InlineKeyboardButton("💸 Host Withdrawal (₹700-₹3000)", callback_data="action_withdraw")
        )
    else:
        markup.add(
            types.InlineKeyboardButton("👑 Register as Host", callback_data="action_reghost")
        )

    profile_card += f"\n🔗 *Your Referral Link:*\n`{ref_link}`\n─────────────────────────"
    bot.send_message(user_id, profile_card, reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text in ["Help & Tutorial", "🆘 Help & Tutorial"])
def help_and_tutorial(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🎬 Watch Tutorial", callback_data="show_tutorial"),
        types.InlineKeyboardButton("💬 Admin Support", url="https://t.me/VynoraSupport")
    )
    bot.send_message(message.chat.id, "🆘 *HELP & SUPPORT CENTER*", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["show_tutorial", "action_reghost", "action_withdraw"])
def handle_profile_help_actions(call):
    user_id = call.message.chat.id
    if call.data == "show_tutorial":
        bot.send_message(user_id, "🎬 *TUTORIAL*\n1. Recharge Mins -> QR Pay & send UTR\n2. Book Session -> Select host")
    elif call.data == "action_reghost":
        msg = bot.send_message(user_id, "👑 *BECOME A HOST*\nStep 1/4: Apna Name & Age type karein:")
        bot.register_next_step_handler(msg, process_host_name)
    elif call.data == "action_withdraw":
        start_withdrawal(call.message)
    bot.answer_callback_query(call.id)

def process_host_name(message):
    msg = bot.send_message(message.chat.id, "Step 2/4: Calling Phone Number enter karein:")
    bot.register_next_step_handler(msg, process_host_phone, message.text)

def process_host_phone(message, name_age):
    msg = bot.send_message(message.chat.id, "Step 3/4: WhatsApp Number enter karein:")
    bot.register_next_step_handler(msg, process_host_whatsapp, name_age, message.text)

def process_host_whatsapp(message, name_age, phone):
    msg = bot.send_message(message.chat.id, "Step 4/4: Telegram Username enter karein:")
    bot.register_next_step_handler(msg, process_host_tg, name_age, phone, message.text)

def process_host_tg(message, name_age, phone, whatsapp):
    user_id = message.chat.id
    bot.send_message(user_id, "🎉 *APPLICATION SUBMITTED!* Admin verification ka wait karein.")
    
    admin_markup = types.InlineKeyboardMarkup(row_width=2)
    admin_markup.add(
        types.InlineKeyboardButton("✅ Approve Host", callback_data=f"hostapp_{user_id}"),
        types.InlineKeyboardButton("❌ Reject Host", callback_data=f"hostrej_{user_id}")
    )
    admin_card = f"👑 *NEW HOST APPLICATION*\n🆔 User ID: `{user_id}`\n👤 Name: `{name_age}`\n📞 Phone: `{phone}`"
    bot.send_message(ADMIN_GROUP_ID, admin_card, reply_markup=admin_markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith(("hostapp_", "hostrej_")))
def handle_host_approval(call):
    data = call.data.split("_")
    action, applicant_id = data[0], int(data[1])
    
    if action == "hostapp":
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT slot_name FROM host_assignments")
        assigned = [r[0] for r in cursor.fetchall()]
        conn.close()
        
        vacant_slots = [s for s in HOST_GROUPS.keys() if s not in assigned]
        if not vacant_slots:
            bot.answer_callback_query(call.id, "❌ No Vacant Slots!", show_alert=True)
            return
            
        assigned_slot = vacant_slots[0]
        assign_host_slot(applicant_id, assigned_slot)
        bot.send_message(applicant_id, f"🎉 *HOST APPROVED!*\n👑 Slot: `{assigned_slot}`")
    bot.answer_callback_query(call.id)

def start_withdrawal(message):
    user_id = message.chat.id
    worked_mins, slot_name = get_host_worked_mins(user_id)
    if not slot_name:
        bot.send_message(user_id, "⚠️ Aap Host nahi hain.")
        return

    net_balance_inr = round(worked_mins * 0.70, 2)
    if net_balance_inr < 700:
        bot.send_message(user_id, f"❌ *Withdrawal Rejected!*\n💵 Available Net Balance: `₹{net_balance_inr}`\n⚠️ Minimum Withdrawal Limit: **₹700**")
        return

    msg = bot.send_message(
        user_id, 
        f"💳 *HOST RUPEE WITHDRAWAL*\n💵 Net Balance: `₹{net_balance_inr}`\n\n👇 Enter Amount (₹700 to ₹3000):"
    )
    bot.register_next_step_handler(msg, process_withdraw_amount, net_balance_inr, worked_mins)

def process_withdraw_amount(message, net_balance_inr, worked_mins):
    user_id = message.chat.id
    amount_text = message.text.strip() if message.text else ""
    
    if not amount_text.isdigit() or int(amount_text) < 700 or int(amount_text) > 3000 or int(amount_text) > net_balance_inr:
        bot.send_message(user_id, f"❌ *Invalid Amount!* Range: ₹700 - ₹3000")
        return

    amount_inr = int(amount_text)
    msg = bot.send_message(user_id, f"✅ Amount: `₹{amount_inr}`\n📲 Type UPI ID:")
    bot.register_next_step_handler(msg, process_withdraw_upi, amount_inr)

def process_withdraw_upi(message, amount_inr):
    user_id = message.chat.id
    upi_id = message.text.strip()
    mins_to_deduct = int(amount_inr / 0.70)
    
    bot.send_message(user_id, f"🎉 *WITHDRAWAL REQUEST SUBMITTED!*\n💵 Amount: `₹{amount_inr}`\n📍 UPI ID: `{upi_id}`")
    
    admin_alert = f"💸 *WITHDRAWAL REQUEST*\n👤 Host ID: `{user_id}`\n💵 Payout: `₹{amount_inr}`\n📍 UPI: `{upi_id}`"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Mark Paid", callback_data=f"payout_done_{user_id}_{amount_inr}_{mins_to_deduct}"))
    bot.send_message(ADMIN_GROUP_ID, admin_alert, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("payout_done_"))
def admin_payout_action(call):
    parts = call.data.split("_")
    user_id, amount_inr = int(parts[2]), int(parts[3])
    bot.edit_message_text(f"✅ *PAID* Host `{user_id}` -> `₹{amount_inr}`", ADMIN_GROUP_ID, call.message.message_id)
    bot.send_message(user_id, f"🔔 *PAYMENT SUCCESSFUL!* `₹{amount_inr}` transferred.")

# --- ADVANCED COMMANDS ---
@bot.message_handler(commands=['history'])
def user_history_cmd(message):
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        bot.send_message(message.chat.id, "⚠️ Usage: `/history <user_id>`")
        return
    target_user = int(args[1])
    u_data = get_user_data(target_user)
    history = get_user_call_history(target_user)
    
    msg = f"📜 *CALL HISTORY*\n👤 Name: `{u_data['name']}`\n📞 Phone: `{u_data['phone'] or 'N/A'}`\n\n"
    for row in history:
        msg += f"💃 Host: `{row[0]}` | Calls: `{row[1]}` | Mins: `{row[2]}`\n"
    bot.send_message(message.chat.id, msg)

if __name__ == '__main__':
    print("Vynora Bot Online...")
    try: bot.remove_webhook()
    except Exception: pass
    bot.infinity_polling(skip_pending=True)
