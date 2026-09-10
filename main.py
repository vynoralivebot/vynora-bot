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

# --- RATES CONFIGURATION ---
HOST_RATE_PER_MIN = 14  # Host ko ₹14 per worked min milenge (5 min = ₹70)

# --- 2. PERMANENT SQLITE DATABASE SETUP WITH CONCURRENCY FIX ---
DB_NAME = "vynora.db"

def get_db():
    conn = sqlite3.connect(DB_NAME, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            phone TEXT,
            balance INTEGER DEFAULT 0,
            referred_by INTEGER DEFAULT 0
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_txns (
            txn_id TEXT PRIMARY KEY,
            user_id INTEGER,
            utr TEXT,
            msg_id INTEGER,
            status TEXT DEFAULT 'PENDING'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_plans (
            user_id INTEGER PRIMARY KEY,
            plan_text TEXT
        )
    ''')
    conn.commit()
    conn.close()

def auto_register_user(user_id, name, referrer_id=0):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    exists = cursor.fetchone()
    
    if not exists:
        cursor.execute('''
            INSERT INTO users (user_id, name, balance, referred_by) VALUES (?, ?, 0, ?)
        ''', (user_id, name, referrer_id if referrer_id != user_id else 0))
    else:
        cursor.execute("UPDATE users SET name = ? WHERE user_id = ?", (name, user_id))
    
    conn.commit()
    conn.close()

def get_user_data(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, phone, balance, referred_by FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"name": row[0], "phone": row[1], "balance": row[2], "referred_by": row[3]}
    return {"name": None, "phone": None, "balance": 0, "referred_by": 0}

def is_new_user(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ? AND duration > 0", (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count == 0

def add_user_balance(user_id, mins):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, balance) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?
    ''', (user_id, mins, mins))
    conn.commit()
    conn.close()

def deduct_user_balance(user_id, mins):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (mins, user_id))
    conn.commit()
    conn.close()

def save_user_phone(user_id, phone):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET phone = ? WHERE user_id = ?", (phone, user_id))
    conn.commit()
    conn.close()

def log_session(user_id, host_name, duration):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions (user_id, host_name, duration) VALUES (?, ?, ?)", (user_id, host_name, duration))
    conn.commit()
    conn.close()

def save_user_plan(user_id, plan_text):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO user_plans (user_id, plan_text) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET plan_text = ?
    ''', (user_id, plan_text, plan_text))
    conn.commit()
    conn.close()

def get_user_plan(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT plan_text FROM user_plans WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else "Custom / Not Selected"

def save_pending_txn(txn_id, user_id, utr, msg_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO pending_txns (txn_id, user_id, utr, msg_id, status) VALUES (?, ?, ?, ?, 'PENDING')
        ON CONFLICT(txn_id) DO UPDATE SET user_id=?, utr=?, msg_id=?
    ''', (txn_id, user_id, utr, msg_id, user_id, utr, msg_id))
    conn.commit()
    conn.close()

def get_pending_txn(txn_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, utr, msg_id, status FROM pending_txns WHERE txn_id = ?", (txn_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "utr": row[1], "msg_id": row[2], "status": row[3]}
    return None

def deduct_host_payout_mins(host_user_id, mins):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT slot_name FROM host_assignments WHERE user_id = ?", (host_user_id,))
    row = cursor.fetchone()
    if row:
        slot_name = row[0]
        cursor.execute("INSERT INTO sessions (user_id, host_name, duration) VALUES (?, ?, ?)", (host_user_id, slot_name, -mins))
        conn.commit()
    conn.close()

def get_host_worked_mins(host_user_id):
    conn = get_db()
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
    return max(0, total_worked), slot_name

def get_user_call_history(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT host_name, COUNT(*), SUM(duration) 
        FROM sessions 
        WHERE user_id = ? AND duration > 0
        GROUP BY host_name
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_all_db_users():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def assign_host_slot(user_id, slot_name):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO host_assignments (user_id, slot_name, status) VALUES (?, ?, 'ONLINE')
        ON CONFLICT(user_id) DO UPDATE SET slot_name = ?, status = 'ONLINE'
    ''', (user_id, slot_name, slot_name))
    conn.commit()
    conn.close()

def remove_host_slot(identifier):
    conn = get_db()
    cursor = conn.cursor()
    if str(identifier).isdigit():
        cursor.execute("DELETE FROM host_assignments WHERE user_id = ?", (int(identifier),))
    else:
        cursor.execute("DELETE FROM host_assignments WHERE slot_name = ?", (identifier,))
    conn.commit()
    conn.close()

def update_host_status(user_id, status):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE host_assignments SET status = ? WHERE user_id = ?", (status, user_id))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_hosts_status_map():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT slot_name, status FROM host_assignments")
    rows = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}

init_db()

# --- 3. BOT CONFIGURATION ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.environ.get("ADMIN_GROUP_ID", "-1004325621712"))
REGISTERED_USER_GROUP_ID = int(os.environ.get("REGISTERED_USER_GROUP_ID", "-1003698246938"))

HOST_GROUPS = {
    "Host Priya 01": int(os.environ.get("GROUP_PRIYA_01", "-1004312344325")),
    "Host Ananya 02": int(os.environ.get("GROUP_ANANYA_02", "-1004330981781")),
    "Host Simran 03": int(os.environ.get("GROUP_SIMRAN_03", "-1004350353315")),
    "Host Neha 04": int(os.environ.get("GROUP_NEHA_04", "-1003939071012")),
    "Host Pooja 05": int(os.environ.get("GROUP_POOJA_05", "-1004293963082")),
    "Host Riya 06": int(os.environ.get("GROUP_RIYA_06", "-1004459506130"))
}

UPI_ID = os.environ.get("UPI_ID", "vynoralive@slc")
PAYEE_NAME = os.environ.get("PAYEE_NAME", "Rajnish Kumar")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# --- SAFE INVITE LINK & NON-BLOCKING TIMER ---
def generate_safe_invite_link(group_id, user_id):
    try:
        link_obj = bot.create_chat_invite_link(chat_id=group_id, member_limit=1)
        return link_obj.invite_link
    except Exception as e:
        print(f"Invite Link Error: {e}")
        bot.send_message(ADMIN_GROUP_ID, f"🚨 *INVITE LINK ERROR!*\nGroup `{group_id}` me Bot permissions check karein.")
        return None

def kick_user_action(chat_id, user_id, mins):
    try:
        bot.ban_chat_member(chat_id, user_id)
        bot.unban_chat_member(chat_id, user_id)
        bot.send_message(user_id, f"⏰ *SESSION TIME EXPIRED!*\nAapka `{mins} Mins` ka session khatam ho gaya hai.")
    except Exception as e:
        print(f"Kick Error: {e}")

def schedule_auto_kick(chat_id, user_id, mins):
    timer = threading.Timer(mins * 60, kick_user_action, args=(chat_id, user_id, mins))
    timer.daemon = True
    timer.start()

# --- MAIN KEYBOARD MENU ---
def get_main_keyboard(user_id=None):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton("🔥 Book Host Session")
    btn2 = types.KeyboardButton("💳 Recharge Minutes")
    btn3 = types.KeyboardButton("👑 Host Earnings")
    btn4 = types.KeyboardButton("👤 Profile & Referral")
    btn5 = types.KeyboardButton("🆘 Help & Support")
    
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)
    markup.add(btn5)
    return markup

# --- 4. START COMMAND WITH REFERRAL TRACKING ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.chat.id
    name = message.from_user.first_name
    
    referrer_id = 0
    args = message.text.split()
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])

    auto_register_user(user_id, name, referrer_id)
    bot.send_message(
        user_id, 
        f"✨ *Welcome to Vynora Live Official Bot!*\n\nNamaste *{name}*, niche diye gaye menu se service chunein:", 
        reply_markup=get_main_keyboard(user_id)
    )

# --- ADMIN COMMANDS: BROADCAST, STATS, WITHDRAW ---
@bot.message_handler(commands=['broadcast'])
def broadcast_cmd(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    msg_text = message.text.replace("/broadcast", "").strip()
    if not msg_text:
        bot.send_message(ADMIN_GROUP_ID, "⚠️ Usage: `/broadcast <Aapka Message>`")
        return
        
    all_users = get_all_db_users()
    count = 0
    for uid in all_users:
        try:
            bot.send_message(uid, f"📢 *IMPORTANT ANNOUNCEMENT*\n\n{msg_text}")
            count += 1
            time.sleep(0.05)
        except Exception:
            pass
    bot.send_message(ADMIN_GROUP_ID, f"✅ *BROADCAST SENT!*\nTotal Delivered: `{count}/{len(all_users)} Users`")

@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    users_count = len(get_all_db_users())
    status_map = get_hosts_status_map()
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), SUM(duration) FROM sessions WHERE duration > 0")
    row = cursor.fetchone()
    conn.close()
    
    total_calls = row[0] or 0
    total_mins = row[1] or 0
    
    msg = (
        "📊 *VYNORA SYSTEM STATS*\n─────────────────────────\n"
        f"👤 *Total Registered Users:* `{users_count}`\n"
        f"👑 *Active Host Slots:* `{len(status_map)}`\n"
        f"📞 *Total Calls Completed:* `{total_calls}`\n"
        f"⏱️ *Total Minutes Served:* `{total_mins} Mins`\n"
    )
    bot.send_message(ADMIN_GROUP_ID, msg)

@bot.message_handler(commands=['adminwithdraw', 'withdraw'])
def admin_manual_withdraw(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    args = message.text.split()
    if len(args) < 3 or not args[1].isdigit() or not args[2].isdigit():
        bot.send_message(ADMIN_GROUP_ID, "⚠️ Usage: `/adminwithdraw <host_user_id> <amount_inr>`\nExample: `/adminwithdraw 123456789 1000`")
        return

    host_id = int(args[1])
    amount_inr = int(args[2])
    mins_to_deduct = round(amount_inr / HOST_RATE_PER_MIN)

    deduct_host_payout_mins(host_id, mins_to_deduct)

    try:
        bot.send_message(
            host_id,
            f"🎉 *CONGRATULATIONS!*\n\n"
            f"Aapka `₹{amount_inr}` (`{mins_to_deduct} Mins` Token) ka withdrawal process ho gaya hai.\n\n"
            f"⏳ Agle **12 se 24 ghante** ke andar paisa aapke UPI account me credit kar diya jayega."
        )
    except Exception as e:
        print(f"Host message error: {e}")

    bot.send_message(
        ADMIN_GROUP_ID, 
        f"✅ *MANUAL WITHDRAWAL PROCESSED*\n"
        f"👤 Host ID: `{host_id}`\n"
        f"💵 Amount: `₹{amount_inr}`\n"
        f"🪙 Deducted: `{mins_to_deduct} Mins Token`"
    )

@bot.message_handler(commands=['sethost'])
def set_host_direct(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        bot.send_message(
            message.chat.id, 
            "⚠️ Usage: `/sethost <user_id> <Host Slot Name>`\n\n*Available Slots:*\n• `Host Priya 01`\n• `Host Ananya 02`\n• `Host Simran 03`\n• `Host Neha 04`\n• `Host Pooja 05`\n• `Host Riya 06`"
        )
        return
        
    target_user = int(args[1])
    slot_name = args[2].strip()
    
    if slot_name not in HOST_GROUPS:
        bot.send_message(message.chat.id, f"❌ *Invalid Slot Name!* Kripya sahi slot name likhein.")
        return
    
    assign_host_slot(target_user, slot_name)
    bot.send_message(ADMIN_GROUP_ID, f"✅ *HOST LINKED SUCCESSFULLY!*\n👤 User ID: `{target_user}`\n👑 Slot Name: `{slot_name}`")
    try:
        bot.send_message(target_user, f"🎉 *CONGRATULATIONS!*\nAapko `{slot_name}` slot assign kar diya gaya hai.")
    except Exception:
        pass

@bot.message_handler(commands=['delhost'])
def delete_host_direct(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.send_message(message.chat.id, "⚠️ Usage: `/delhost <user_id or Slot Name>`")
        return
        
    target = args[1].strip()
    remove_host_slot(target)
    bot.send_message(ADMIN_GROUP_ID, f"🗑️ *HOST REMOVED SUCCESSFULLY!*\nTarget `{target}` ko unassign kar diya gaya hai.")

# --- 5. HOST BALANCE & EARNINGS ---
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
            "📌 *Note:* Aap abhi kisi Host Slot se linked nahi hain."
        )
        bot.send_message(user_id, msg)
        return

    net_earnings_inr = round(worked_mins * HOST_RATE_PER_MIN, 2)
    
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
    msg += f"⏱️ *Worked Mins Token:* `{worked_mins} Mins`\n"
    msg += f"💵 *Net INR Balance:* `₹{net_earnings_inr}`\n"
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
    
    active_hosts_count = 0
    for slot_name in HOST_GROUPS.keys():
        if slot_name in status_map:
            active_hosts_count += 1
            current_status = status_map[slot_name]
            if current_status == 'ONLINE':
                markup.add(types.InlineKeyboardButton(f"🟢 {slot_name} (Online)", callback_data=f"select_host_{slot_name}"))
            else:
                markup.add(types.InlineKeyboardButton(f"🔴 {slot_name} (Offline)", callback_data="host_offline"))
            
    if active_hosts_count == 0:
        bot.send_message(user_id, "⚠️ *Abhi koi Host active nahi hai.*\n\nKripya kuch samay baad dobara try karein!")
        return

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

        phone_num = message.contact.phone_number
        save_user_phone(user_id, phone_num)
        user_info = get_user_data(user_id)
        
        if user_info['referred_by'] > 0:
            add_user_balance(user_info['referred_by'], 5)
            try:
                bot.send_message(user_info['referred_by'], "🎉 *REFERRAL BONUS!* Aapke friend ne join kiya. Aapko **5 Minutes** free mil gaye hain!")
            except Exception:
                pass
        
        full_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
        username_str = f"@{message.from_user.username}" if message.from_user.username else "N/A"
        
        reg_card = (
            "🆕 *NEW USER REGISTERED!*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *Name:* `{full_name}`\n"
            f"🆔 *User ID:* `{user_id}`\n"
            f"🏷️ *Username:* {username_str}\n"
            f"📱 *Phone Number:* `{phone_num}`\n"
            f"🔗 *Referred By:* `{user_info['referred_by']}`\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        )
        try:
            bot.send_message(REGISTERED_USER_GROUP_ID, reg_card)
        except Exception as e:
            print(f"Reg Group Notify Error: {e}")

        bot.send_message(user_id, "🎉 *Registration Complete!* Ab aap Session Book kar sakte hain.", reply_markup=get_main_keyboard(user_id))

@bot.callback_query_handler(func=lambda call: call.data == "host_offline")
def alert_host_offline(call):
    bot.answer_callback_query(call.id, "⚠️ Yeh Host abhi offline hai. Kripya Online Host chunnein!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("select_host_"))
def show_host_durations(call):
    user_id = call.from_user.id
    host_name = call.data.replace("select_host_", "")
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    if is_new_user(user_id):
        markup.add(types.InlineKeyboardButton("🎁 1 Min (New User Offer - ₹20)", callback_data=f"book_{host_name}_1"))
    
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
    
    schedule_auto_kick(target_group_id, user_id, mins)
    
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
    
    bot.send_message(ADMIN_GROUP_ID, f"📊 *NEW BOOKING*\n👤 User: `{user_id}`\n💃 Host: `{host_name}`\n⏱️ Duration: `{mins} Mins`")
    bot.send_message(target_group_id, f"🔔🔔 *CALL BOOKED!* `{host_name}` -> Duration: `{mins} Mins`", disable_notification=False)

# --- 7. RECHARGE & PAYMENT APPROVAL ---
@bot.message_handler(func=lambda msg: msg.text in ["💳 Recharge Minutes", "Recharge Minutes"])
def buy_minutes(message):
    user_id = message.chat.id
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    if is_new_user(user_id):
        markup.add(types.InlineKeyboardButton("🎁 ₹20 — 1 Minute (New User Trial)", callback_data="payplan_20_1"))
        
    markup.add(
        types.InlineKeyboardButton("⭐ ₹100 — 5 Minutes", callback_data="payplan_100_5"),
        types.InlineKeyboardButton("🔥 ₹200 — 10 Minutes", callback_data="payplan_200_10"),
        types.InlineKeyboardButton("🚀 ₹400 — 20 Minutes", callback_data="payplan_400_20"),
        types.InlineKeyboardButton("💎 ₹600 — 30 Minutes", callback_data="payplan_600_30")
    )
    bot.send_message(message.chat.id, "💳 *SELECT RECHARGE PLAN*", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("payplan_"))
def show_plan_qr(call):
    _, amount, mins = call.data.split("_")
    user_id = call.message.chat.id
    save_user_plan(user_id, f"₹{amount} ({mins} Mins)")
    
    upi_url = f"upi://pay?pa={UPI_ID}&pn={urllib.parse.quote(PAYEE_NAME)}&am={amount}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={urllib.parse.quote(upi_url)}"
    
    caption = f"🎯 *SELECTED PLAN: ₹{amount} ({mins} Mins)*\n\n📍 *UPI ID:* `{UPI_ID}`\n💰 *Amount:* `₹{amount}`\n\n📲 *QR Code scan karke pay karein aur Screenshot bhejein.*"
    bot.send_photo(user_id, qr_url, caption=caption)
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
    selected_plan = get_user_plan(user_id)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("1 Min (Rs.20)", callback_data=f"app_{user_id}_1_{txn_id}"),
        types.InlineKeyboardButton("5 Min (Rs.100)", callback_data=f"app_{user_id}_5_{txn_id}"),
        types.InlineKeyboardButton("10 Min (Rs.200)", callback_data=f"app_{user_id}_10_{txn_id}"),
        types.InlineKeyboardButton("20 Min (Rs.400)", callback_data=f"app_{user_id}_20_{txn_id}"),
        types.InlineKeyboardButton("30 Min (Rs.600)", callback_data=f"app_{user_id}_30_{txn_id}"),
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
    save_pending_txn(txn_id, user_id, utr_number, sent_msg.message_id)
    bot.send_message(user_id, f"⏳ *Verification Under Process!*\n• *Plan:* `{selected_plan}`\n• *UTR:* `{utr_number}`")

@bot.callback_query_handler(func=lambda call: call.data.startswith(("app_", "rej_")))
def process_admin_recharge_approval(call):
    data = call.data.split("_")
    action, user_id = data[0], int(data[1])
    
    if action == "app":
        mins, txn_id = int(data[2]), data[3]
        txn_info = get_pending_txn(txn_id)
        add_user_balance(user_id, mins)
        if txn_info and txn_info.get("msg_id"):
            try: bot.delete_message(ADMIN_GROUP_ID, txn_info["msg_id"])
            except Exception: pass
                
        bot.send_message(ADMIN_GROUP_ID, f"✅ *PAYMENT APPROVED*\n👤 User ID: `{user_id}`\n💰 Credited: `{mins} Mins`")
        bot.send_message(user_id, f"✅ *Payment Approved!*\nAapke account mein *{mins} Minutes* add kar diye gaye hain.", reply_markup=get_main_keyboard(user_id))
        
    elif action == "rej":
        txn_id = data[2]
        txn_info = get_pending_txn(txn_id)
        if txn_info and txn_info.get("msg_id"):
            try: bot.delete_message(ADMIN_GROUP_ID, txn_info["msg_id"])
            except Exception: pass
        bot.send_message(user_id, "❌ Aapka payment verification reject ho gaya hai.")

# --- 8. PROFILE, REFERRAL & WITHDRAWAL ---
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
    
    markup = types.InlineKeyboardMarkup(row_width=1)

    if slot_name:
        net_inr = round(worked_mins * HOST_RATE_PER_MIN, 2)
        profile_card += f"👑 *Host Slot:* `{slot_name}`\n"
        profile_card += f"⏱️ *Worked Mins Token:* `{worked_mins} Mins`\n"
        profile_card += f"💵 *Net INR Balance:* `₹{net_inr}`\n"
        markup.add(
            types.InlineKeyboardButton("💸 Host Withdrawal (₹700-₹3000)", callback_data="action_withdraw")
        )

    profile_card += f"\n🔗 *Your Referral Link:*\n`{ref_link}`\n─────────────────────────"
    bot.send_message(user_id, profile_card, reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text in ["Help & Support", "🆘 Help & Support"])
def help_and_tutorial(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🎬 Watch Tutorial", callback_data="show_tutorial"),
        types.InlineKeyboardButton("💬 Contact Support", url="https://t.me/VynoraSupport")
    )
    
    text = (
        "🆘 *HELP & SUPPORT CENTER*\n\n"
        "• Booking ya Recharge issue ke liye Admin Support par message karein.\n"
        "• **👑 Host Banne Ke Liye:** Contact Support par message karke Admin se baat karein."
    )
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["show_tutorial", "action_withdraw"])
def handle_profile_help_actions(call):
    user_id = call.message.chat.id
    if call.data == "show_tutorial":
        bot.send_message(user_id, "🎬 *TUTORIAL*\n1. Recharge Mins -> QR Pay & send UTR\n2. Book Session -> Select active host")
    elif call.data == "action_withdraw":
        start_withdrawal(call.message)
    bot.answer_callback_query(call.id)

# --- HOST WITHDRAWAL FLOW ---
def start_withdrawal(message):
    user_id = message.chat.id
    worked_mins, slot_name = get_host_worked_mins(user_id)
    if not slot_name:
        bot.send_message(user_id, "⚠️ Aap Host slot se linked nahi hain.")
        return

    net_balance_inr = round(worked_mins * HOST_RATE_PER_MIN, 2)
    if net_balance_inr < 700:
        bot.send_message(
            user_id, 
            f"❌ *WITHDRAWAL REJECTED*\n\n"
            f"⏱️ Available Worked Mins: `{worked_mins} Mins` Token\n"
            f"💵 Net Available Balance: `₹{net_balance_inr}`\n\n"
            f"⚠️ Minimum Withdrawal Limit: **₹700**"
        )
        return

    msg = bot.send_message(
        user_id, 
        f"💳 *HOST WITHDRAWAL REQUEST*\n"
        f"⏱️ Worked Mins Token: `{worked_mins} Mins`\n"
        f"💵 Available Net Balance: `₹{net_balance_inr}`\n\n"
        f"👇 Enter Amount (₹700 se ₹3000 ke beech):"
    )
    bot.register_next_step_handler(msg, process_withdraw_amount, net_balance_inr, worked_mins)

def process_withdraw_amount(message, net_balance_inr, worked_mins):
    user_id = message.chat.id
    amount_text = message.text.strip() if message.text else ""
    
    if not amount_text.isdigit() or int(amount_text) < 700 or int(amount_text) > 3000 or int(amount_text) > net_balance_inr:
        msg = bot.send_message(
            user_id, 
            f"❌ *Invalid Amount!*\nRange: ₹700 - ₹3000 (aur maximum ₹{net_balance_inr} tak).\n\n👇 *Sahi amount dobara enter karein:*"
        )
        bot.register_next_step_handler(msg, process_withdraw_amount, net_balance_inr, worked_mins)
        return

    amount_inr = int(amount_text)
    mins_equivalent = round(amount_inr / HOST_RATE_PER_MIN)
    
    msg = bot.send_message(
        user_id, 
        f"✅ Selected Amount: `₹{amount_inr}` (`{mins_equivalent} Mins Token`)\n\n"
        f"📲 Apna **UPI ID / GPay / PhonePe** address type karke bhejein:"
    )
    bot.register_next_step_handler(msg, process_withdraw_upi, amount_inr, mins_equivalent)

def process_withdraw_upi(message, amount_inr, mins_equivalent):
    user_id = message.chat.id
    upi_id = message.text.strip()
    user_info = get_user_data(user_id)
    host_name = user_info['name'] or f"Host-{user_id}"

    bot.send_message(
        user_id, 
        f"🎉 *CONGRATULATIONS! WITHDRAWAL REQUEST SUBMITTED*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 *Amount:* `₹{amount_inr}`\n"
        f"🪙 *Mins Token:* `{mins_equivalent} Mins`\n"
        f"📍 *UPI ID:* `{upi_id}`\n"
        f"⏳ *Status:* Pending Admin Approval\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"ℹ️ Agle **12 se 24 ghante** ke andar paisa aapke UPI account me transfer kar diya jayega."
    )
    
    admin_card = (
        f"📥 *NEW HOST WITHDRAWAL REQUEST*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Host Name:* `{host_name}`\n"
        f"🆔 *Host ID:* `{user_id}`\n"
        f"🪙 *Mins Token:* `{mins_equivalent} Mins`\n"
        f"💰 *Payout INR:* `₹{amount_inr}`\n"
        f"📍 *UPI Address:* `{upi_id}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Approve & Mark Paid", callback_data=f"payout_done_{user_id}_{amount_inr}_{mins_equivalent}"),
        types.InlineKeyboardButton("❌ Reject", callback_data=f"payout_reject_{user_id}")
    )
    bot.send_message(ADMIN_GROUP_ID, admin_card, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith(("payout_done_", "payout_reject_")))
def admin_payout_action(call):
    parts = call.data.split("_")
    action = parts[0]
    
    if action == "payout" and parts[1] == "done":
        user_id, amount_inr, mins_equivalent = int(parts[2]), int(parts[3]), int(parts[4])
        deduct_host_payout_mins(user_id, mins_equivalent)
        
        bot.edit_message_text(
            f"✅ *PAID & DEDUCTED*\n👤 Host ID: `{user_id}`\n💵 Amount: `₹{amount_inr}`\n🪙 Deducted: `{mins_equivalent} Mins Token`", 
            ADMIN_GROUP_ID, 
            call.message.message_id
        )
        bot.send_message(
            user_id, 
            f"🔔 *PAYMENT SUCCESSFUL!*\n\nAapka `₹{amount_inr}` (`{mins_equivalent} Mins Token`) aapke UPI account me credit kar diya gaya hai."
        )
        
    elif action == "payout" and parts[1] == "reject":
        user_id = int(parts[2])
        bot.edit_message_text(f"❌ *WITHDRAWAL REJECTED*\n👤 Host ID: `{user_id}`", ADMIN_GROUP_ID, call.message.message_id)
        bot.send_message(user_id, "❌ Aapka withdrawal request admin dwara reject kar diya gaya hai.")

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
