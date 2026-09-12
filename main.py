import json
import os
import sqlite3
import threading
import time
import urllib.parse
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread
import telebot
from telebot import types

# --- 1. WEB SERVICE PORT BINDING ---

from http.server import BaseHTTPRequestHandler, HTTPServer

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Vynora Live Bot with Inline Host Dashboard is Online!")

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# --- RATES CONFIGURATION ---

HOST_RATE_PER_MIN = 14

# --- 2. GOOGLE SHEETS SETUP & HELPER ---

SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "Private_Live_Official")

def get_gsheet_client():
    try:
        creds_raw = os.environ.get("GOOGLE_CREDENTIALS")
        if creds_raw:
            creds_dict = json.loads(creds_raw)
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            return gspread.authorize(creds)
    except Exception as e:
        print(f"[Sheet Auth Error]: {e}")
    return None

def append_to_google_sheet(tab_name, row_data):
    def _async_append():
        try:
            client = get_gsheet_client()
            if not client:
                return
            spreadsheet = client.open(SHEET_NAME)
            try:
                worksheet = spreadsheet.worksheet(tab_name)
            except Exception:
                worksheet = spreadsheet.sheet1
            worksheet.append_row(row_data)
        except Exception as e:
            print(f"❌ [Google Sheet Save Error]: {e}")
    threading.Thread(target=_async_append, daemon=True).start()

# --- 3. PERMANENT SQLITE DATABASE SETUP ---

DB_NAME = "vynora.db"

def get_db():
    conn = sqlite3.connect(DB_NAME, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        name TEXT,
        phone TEXT DEFAULT 'N/A',
        balance INTEGER DEFAULT 0,
        referred_by INTEGER DEFAULT 0
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS host_assignments (
        user_id INTEGER PRIMARY KEY,
        slot_name TEXT UNIQUE,
        group_id INTEGER,
        status TEXT DEFAULT 'ONLINE'
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        host_name TEXT,
        duration INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pending_txns (
        txn_id TEXT PRIMARY KEY,
        user_id INTEGER,
        utr TEXT,
        msg_id INTEGER,
        status TEXT DEFAULT 'PENDING'
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_plans (
        user_id INTEGER PRIMARY KEY,
        plan_text TEXT
    )
    """)
    conn.commit()
    conn.close()

def auto_register_user(user_id, name, referrer_id=0):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    exists = cursor.fetchone()
    if not exists:
        cursor.execute("""
        INSERT INTO users (user_id, name, balance, referred_by) VALUES (?, ?, 0, ?)
        """, (user_id, name, referrer_id if referrer_id != user_id else 0))
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
    return {"name": None, "phone": "N/A", "balance": 0, "referred_by": 0}

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
    cursor.execute("""
    INSERT INTO users (user_id, balance) VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?
    """, (user_id, mins, mins))
    conn.commit()
    conn.close()

def deduct_user_balance(user_id, mins):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (mins, user_id))
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
    cursor.execute("""
    INSERT INTO user_plans (user_id, plan_text) VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET plan_text = ?
    """, (user_id, plan_text, plan_text))
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
    cursor.execute("""
    INSERT INTO pending_txns (txn_id, user_id, utr, msg_id, status) VALUES (?, ?, ?, ?, 'PENDING')
    ON CONFLICT(txn_id) DO UPDATE SET user_id=?, utr=?, msg_id=?
    """, (txn_id, user_id, utr, msg_id, user_id, utr, msg_id))
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

def assign_host_slot(user_id, slot_name, group_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO host_assignments (user_id, slot_name, group_id, status) VALUES (?, ?, ?, 'ONLINE')
    ON CONFLICT(user_id) DO UPDATE SET slot_name = ?, group_id = ?, status = 'ONLINE'
    """, (user_id, slot_name, group_id, slot_name, group_id))
    conn.commit()
    conn.close()

def remove_host_slot(identifier):
    conn = get_db()
    cursor = conn.cursor()
    if str(identifier).isdigit() or (str(identifier).startswith("-") and str(identifier)[1:].isdigit()):
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

def get_host_info_by_userid(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT slot_name, group_id, status FROM host_assignments WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"slot_name": row[0], "group_id": row[1], "status": row[2]}
    return None

def get_all_hosts_map():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, slot_name, group_id, status FROM host_assignments")
    rows = cursor.fetchall()
    conn.close()
    hosts = {}
    for r in rows:
        hosts[r[1]] = {"user_id": r[0], "group_id": r[2], "status": r[3]}
    return hosts

init_db()

# --- 4. BOT CONFIGURATION ---

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.environ.get("ADMIN_GROUP_ID", "-1004325621712"))
REGISTERED_USER_GROUP_ID = int(os.environ.get("REGISTERED_USER_GROUP_ID", "-1003698246938"))

DEFAULT_HOST_GROUPS = {
    "Host Priya 01": int(os.environ.get("GROUP_PRIYA_01", "-1004312344325")),
    "Host Ananya 02": int(os.environ.get("GROUP_ANANYA_02", "-1004330981781")),
    "Host Simran 03": int(os.environ.get("GROUP_SIMRAN_03", "-1004350353315")),
    "Host Neha 04": int(os.environ.get("GROUP_NEHA_04", "-1003939071012")),
    "Host Pooja 05": int(os.environ.get("GROUP_POOJA_05", "-1004293963082")),
    "Host Riya 06": int(os.environ.get("GROUP_RIYA_06", "-1004459506130")),
}

UPI_ID = os.environ.get("UPI_ID", "vynoralive@slc")
PAYEE_NAME = os.environ.get("PAYEE_NAME", "Rajnish Kumar")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# --- SAFE INVITE LINK & AUTO-KICK TIMER ---

def generate_safe_invite_link(group_id):
    try:
        link_obj = bot.create_chat_invite_link(chat_id=group_id, member_limit=1)
        return link_obj.invite_link
    except Exception as e:
        print(f"Invite Link Error: {e}")
        return None

def kick_user_action(chat_id, user_id, mins, host_name):
    try:
        bot.ban_chat_member(chat_id, user_id)
        bot.unban_chat_member(chat_id, user_id)

        bot.send_message(
            user_id,
            f"⏰ *SESSION TIME EXPIRED!*\n\nAapka `{mins} Mins` ka session khatam ho gaya hai aur aapko private room se hata diya gaya hai."
        )

        gross_earning = mins * HOST_RATE_PER_MIN
        platform_deduction = round(gross_earning * 0.30, 2)
        net_earning = round(gross_earning - platform_deduction, 2)
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        completion_card = (
            "🏁 *SESSION EXPIRED & COMPLETED*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 *Date & Time:* `{current_time_str}`\n"
            f"👤 *User ID:* `{user_id}`\n"
            f"💃 *Host Slot:* `{host_name}`\n"
            f"⏱️ *Call Duration:* `{mins} Minutes`\n"
            f"💰 *Gross Earnings:* `₹{gross_earning}`\n"
            f"📉 *Platform Deduction (30%):* `-₹{platform_deduction}`\n"
            f"💵 *Net Earning Added:* `₹{net_earning}`\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.send_message(chat_id, completion_card)
    except Exception as e:
        print(f"Kick Error: {e}")

def schedule_auto_kick(chat_id, user_id, mins, host_name):
    timer = threading.Timer(mins * 60, kick_user_action, args=(chat_id, user_id, mins, host_name))
    timer.daemon = True
    timer.start()

# --- KEYBOARDS & INLINE DASHBOARD BUILDERS ---

def get_main_keyboard(user_id=None):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton("🔥 Book Host Session"),
        types.KeyboardButton("💳 Recharge Minutes"),
        types.KeyboardButton("👑 Host Earnings"),
        types.KeyboardButton("👤 Profile & Referral"),
        types.KeyboardButton("🆘 Help & Support")
    )
    return markup

def get_host_dashboard_markup(status):
    markup = types.InlineKeyboardMarkup(row_width=2)
    if status == "ONLINE":
        markup.add(types.InlineKeyboardButton("🔴 GO OFFLINE", callback_data="hd_offline"))
    else:
        markup.add(types.InlineKeyboardButton("🟢 GO ONLINE", callback_data="hd_online"))
    markup.add(
        types.InlineKeyboardButton("🔄 Refresh Stats", callback_data="hd_refresh"),
        types.InlineKeyboardButton("🆘 Support", callback_data="hd_support")
    )
    return markup

def build_host_dashboard_content(user_id):
    worked_mins, slot_name = get_host_worked_mins(user_id)
    host_info = get_host_info_by_userid(user_id)
    status = host_info["status"] if host_info else "OFFLINE"
    
    gross_earning = worked_mins * HOST_RATE_PER_MIN
    platform_deduction = round(gross_earning * 0.30, 2)
    net_earning = round(gross_earning - platform_deduction, 2)
    emoji = "🟢" if status == "ONLINE" else "🔴"

    text = (
        "👩‍💼 *VYNORA HOST DASHBOARD*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Assigned Slot:* `{slot_name}`\n"
        f"📊 *Current Status:* {emoji} `{status}`\n"
        f"⏱️ *Total Worked Minutes:* `{worked_mins} Mins`\n"
        f"💰 *Gross Earnings:* `₹{gross_earning}`\n"
        f"📉 *Platform Cut (30%):* `-₹{platform_deduction}`\n"
        f"💵 *Net Total Earnings:* `₹{net_earning}`\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )
    return text, get_host_dashboard_markup(status)

# --- START COMMAND ---

@bot.message_handler(commands=["start"])
def start_cmd(message):
    user_id = message.chat.id
    name = message.from_user.first_name
    full_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
    username_str = f"@{message.from_user.username}" if message.from_user.username else "N/A"

    host_info = get_host_info_by_userid(user_id)
    if host_info:
        text, markup = build_host_dashboard_content(user_id)
        bot.send_message(user_id, text, reply_markup=markup)
        return

    referrer_id = 0
    args = message.text.split()
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])

    auto_register_user(user_id, full_name, referrer_id)
    reg_id = f"REG{user_id}"
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    reg_card = (
        "🆕 *NEW USER ACTIVITY / START*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 *Date & Time:* `{current_time_str}`\n"
        f"👤 *Name:* `{full_name}`\n"
        f"🆔 *User ID:* `{user_id}`\n"
        f"🔖 *Reg Number:* `{reg_id}`\n"
        f"🏷️ *Username:* {username_str}\n"
        f"🔗 *Referred By:* `{referrer_id}`\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )
    try:
        bot.send_message(REGISTERED_USER_GROUP_ID, reg_card)
    except Exception:
        pass

    bot.send_message(
        user_id,
        f"✨ *Welcome to Vynora Live Official Bot!*\n\nNamaste *{name}*,\nAapka Registration Number: `{reg_id}`\n\nNiche diye gaye menu se service chunein:",
        reply_markup=get_main_keyboard(user_id)
    )

# --- INLINE HOST DASHBOARD CALLBACK HANDLERS ---

@bot.callback_query_handler(func=lambda call: call.data.startswith("hd_"))
def host_dashboard_callbacks(call):
    user_id = call.from_user.id
    action = call.data.replace("hd_", "", 1)
    
    host_info = get_host_info_by_userid(user_id)
    if not host_info:
        bot.answer_callback_query(call.id, "⚠️ Aap registered host nahi hain.", show_alert=True)
        return

    if action == "online":
        update_host_status(user_id, "ONLINE")
        bot.answer_callback_query(call.id, "Status changed to ONLINE!")
    elif action == "offline":
        update_host_status(user_id, "OFFLINE")
        bot.answer_callback_query(call.id, "Status changed to OFFLINE!")
    elif action == "refresh":
        bot.answer_callback_query(call.id, "Stats refreshed successfully!")
    elif action == "support":
        bot.answer_callback_query(call.id, "Support: @VynoraSupport", show_alert=True)
        return

    text, markup = build_host_dashboard_content(user_id)
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception:
        pass

# --- ADMIN HOST MANAGEMENT COMMANDS ---

@bot.message_handler(commands=["addhost"])
def admin_add_host(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    
    args = message.text.split()
    if len(args) < 3:
        bot.send_message(ADMIN_GROUP_ID, "⚠️ Usage: `/addhost <telegram_id> <group_id>`\nExample: `/addhost 1108685585 -1004312344325`")
        return
    
    try:
        target_user = int(args[1])
        group_id = int(args[2])
    except ValueError:
        bot.send_message(ADMIN_GROUP_ID, "⚠️ Invalid format! Telegram ID aur Group ID numbers hone chahiye.")
        return

    slot_name = f"Host_{target_user}"
    for name, gid in DEFAULT_HOST_GROUPS.items():
        if gid == group_id:
            slot_name = name
            break

    assign_host_slot(target_user, slot_name, group_id)
    bot.send_message(
        ADMIN_GROUP_ID,
        f"✅ *Host Added & Approved*\n👤 Slot: `{slot_name}`\n🆔 ID: `{target_user}`\n🏢 Group ID: `{group_id}`\n🟢 Status: `ONLINE`"
    )
    try:
        text, markup = build_host_dashboard_content(target_user)
        bot.send_message(
            target_user,
            f"🎉 *Aapko Vynora Live par Host ke roop mein approve kar diya gaya hai!*\nAapka slot: `{slot_name}`\n\nNeeche aapka live dashboard hai:",
            reply_markup=markup
        )
    except Exception:
        pass

@bot.message_handler(commands=["removehost"])
def admin_remove_host(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        bot.send_message(ADMIN_GROUP_ID, "⚠️ Usage: `/removehost <telegram_id_or_slot_name>`")
        return
    identifier = args[1]
    if identifier.isdigit() or (identifier.startswith("-") and identifier[1:].isdigit()):
        identifier = int(identifier)
    remove_host_slot(identifier)
    bot.send_message(ADMIN_GROUP_ID, f"🗑️ Host slot `{identifier}` successfully removed from database.")

@bot.message_handler(commands=["hosts"])
def admin_list_hosts(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    hosts = get_all_hosts_map()
    if not hosts:
        bot.send_message(ADMIN_GROUP_ID, "⚠️ Koi bhi host database mein registered nahi hai.")
        return
    
    text = "👩‍💼 *HOST MANAGEMENT LIST*\n━━━━━━━━━━━━━━━━━━━━━\n"
    for slot, data in hosts.items():
        emoji = "🟢" if data["status"] == "ONLINE" else "🔴"
        text += f"{emoji} `{slot}` — Status: *{data['status']}* (ID: `{data['user_id']}`)\n"
    text += "━━━━━━━━━━━━━━━━━━━━━"
    bot.send_message(ADMIN_GROUP_ID, text)

# --- ADMIN BALANCE COMMANDS ---

@bot.message_handler(commands=["addmins", "givemins"])
def admin_add_mins(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    args = message.text.split()
    if len(args) < 3 or not args[1].isdigit() or not args[2].isdigit():
        bot.send_message(ADMIN_GROUP_ID, "⚠️ Usage: /addmins <user_id> <minutes>")
        return
    target_user, mins = int(args[1]), int(args[2])
    add_user_balance(target_user, mins)
    bot.send_message(ADMIN_GROUP_ID, f"✅ MINUTES ADDED\n👤 User ID: {target_user}\n⏱️ Added: {mins} Mins")
    try:
        bot.send_message(target_user, f"🎁 BONUS CREDITED!\n\nAdmin dwara aapke account mein {mins} Minutes add kar diye gaye hain.")
    except Exception:
        pass

@bot.message_handler(commands=["deductmins", "removemins"])
def admin_deduct_mins(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    args = message.text.split()
    if len(args) < 3 or not args[1].isdigit() or not args[2].isdigit():
        bot.send_message(ADMIN_GROUP_ID, "⚠️ Usage: /deductmins <user_id> <minutes>")
        return
    target_user, mins = int(args[1]), int(args[2])
    deduct_user_balance(target_user, mins)
    bot.send_message(ADMIN_GROUP_ID, f"🗑️ MINUTES DEDUCTED\n👤 User ID: {target_user}\n⏱️ Deducted: {mins} Mins")
    try:
        bot.send_message(target_user, f"ℹ️ BALANCE UPDATE\n\nAdmin dwara aapke account se {mins} Minutes deduct kar liye gaye hain.")
    except Exception:
        pass

# --- HOST EARNINGS (USER MENU) ---

@bot.message_handler(func=lambda msg: msg.text in ["👑 Host Earnings", "Host Earnings"])
def user_menu_host_earnings(message):
    user_id = message.chat.id
    host_info = get_host_info_by_userid(user_id)
    if host_info:
        text, markup = build_host_dashboard_content(user_id)
        bot.send_message(user_id, text, reply_markup=markup)
    else:
        bot.send_message(user_id, "⚠️ Aap ek registered Host nahi hain.", reply_markup=get_main_keyboard(user_id))

# --- BOOK HOST SESSION ---

@bot.message_handler(func=lambda msg: msg.text in ["Book Host Session", "🔥 Book Host Session"])
def book_host(message):
    user_id = message.chat.id
    user_info = get_user_data(user_id)

    if user_info["balance"] <= 0:
        bot.send_message(
            user_id,
            "⚠️ *Insufficient Balance!*\n\nAapka balance **0 Mins** hai. Session book karne ke liye pehle recharge karein.",
            reply_markup=get_main_keyboard(user_id)
        )
        return

    all_hosts = get_all_hosts_map()
    if not all_hosts:
        for slot, gid in DEFAULT_HOST_GROUPS.items():
            all_hosts[slot] = {"group_id": gid, "status": "ONLINE"}

    markup = types.InlineKeyboardMarkup(row_width=1)
    active_count = 0
    for slot_name, data in all_hosts.items():
        if data["status"] == "ONLINE":
            active_count += 1
            markup.add(types.InlineKeyboardButton(f"🟢 {slot_name} (Online)", callback_data=f"sh_{slot_name}"))

    if active_count == 0:
        bot.send_message(user_id, "⚠️ *Abhi koi Host active nahi hai.* Kripya baad mein try karein!")
        return

    bot.send_message(message.chat.id, "✨ *VYNORA LIVE - HOST SELECTION*\n\n👇 *Active host select karein:*", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("sh_"))
def show_host_durations(call):
    user_id = call.from_user.id
    host_name = call.data.replace("sh_", "", 1)
    markup = types.InlineKeyboardMarkup(row_width=2)

    if is_new_user(user_id):
        markup.add(types.InlineKeyboardButton("🎁 1 Min (New User Offer - ₹20)", callback_data=f"bk_{host_name}_1"))

    markup.add(
        types.InlineKeyboardButton("⏱️ 5 Mins", callback_data=f"bk_{host_name}_5"),
        types.InlineKeyboardButton("⏱️ 10 Mins", callback_data=f"bk_{host_name}_10"),
        types.InlineKeyboardButton("⏱️ 20 Mins", callback_data=f"bk_{host_name}_20"),
        types.InlineKeyboardButton("⏱️ 30 Mins", callback_data=f"bk_{host_name}_30"),
        types.InlineKeyboardButton("⏱️ 40 Mins", callback_data=f"bk_{host_name}_40")
    )
    bot.edit_message_text(f"👤 *Selected Host:* `{host_name}`\n\n👇 *Duration select karein:*", call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("bk_"))
def process_booking_click(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    mins = int(parts[-1])
    host_name = "_".join(parts[1:-1])

    user_info = get_user_data(user_id)
    if user_info["balance"] < mins:
        bot.answer_callback_query(call.id, f"❌ Balance Kam Hai! {mins} Mins chahiye.", show_alert=True)
        return

    all_hosts = get_all_hosts_map()
    target_group_id = None
    if host_name in all_hosts:
        target_group_id = all_hosts[host_name]["group_id"]
    else:
        target_group_id = DEFAULT_HOST_GROUPS.get(host_name)

    if not target_group_id:
        bot.answer_callback_query(call.id, "⚠️ Host group configuration nahi mili.", show_alert=True)
        return

    invite_link = generate_safe_invite_link(target_group_id)
    if not invite_link:
        bot.send_message(user_id, "⚠️ Technical Issue ke karan link generate nahi ho paya.")
        return

    deduct_user_balance(user_id, mins)
    log_session(user_id, host_name, mins)
    new_bal = user_info["balance"] - mins

    schedule_auto_kick(target_group_id, user_id, mins, host_name)

    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_full_name = f"{call.from_user.first_name or ''} {call.from_user.last_name or ''}".strip()
    username_str = f"@{call.from_user.username}" if call.from_user.username else "N/A"

    text = (
        "🎉 *SESSION BOOKING SUCCESSFUL!*\n\n"
        f"📅 *Date & Time:* `{current_time_str}`\n"
        f"👤 *Selected Host:* `{host_name}`\n"
        f"⏱️ *Duration:* `{mins} Minutes`\n"
        f"💰 *Remaining Balance:* `{new_bal} Mins`\n\n"
        "👇 *Private Room Join Karein:*"
    )
    link_markup = types.InlineKeyboardMarkup()
    link_markup.add(types.InlineKeyboardButton("🔗 Join Private Session Now", url=invite_link))
    bot.send_message(user_id, text, reply_markup=link_markup)

    admin_card = (
        "🔥 *NEW HOST SESSION BOOKING*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 *Date & Time:* `{current_time_str}`\n"
        f"👤 *User Name:* `{user_full_name}`\n"
        f"🆔 *User ID:* `{user_id}`\n"
        f"💃 *Assigned Host:* `{host_name}`\n"
        f"⏱️ *Duration:* `{mins} Mins`\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )
    bot.send_message(ADMIN_GROUP_ID, admin_card)

    host_group_card = (
        "🔔 *NEW CALL BOOKED IN SLOT!*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 *Date & Time:* `{current_time_str}`\n"
        f"👤 *User Name:* `{user_full_name}`\n"
        f"🆔 *User ID:* `{user_id}`\n"
        f"🏷️ *Username:* `{username_str}`\n"
        f"⏱️ *Duration Booked:* `{mins} Minutes`\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Kripya user ke sath private room me connect rahein!*"
    )
    try:
        bot.send_message(target_group_id, host_group_card)
    except Exception as e:
        print(f"Host Group Notify Error: {e}")

# --- PROFILE & REFERRAL HANDLER ---

@bot.message_handler(func=lambda msg: msg.text in ["👤 Profile & Referral", "Profile & Referral"])
def profile_handler(message):
    user_id = message.chat.id
    user_info = get_user_data(user_id)
    reg_id = f"REG{user_id}"
    bot_info = bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"

    profile_text = (
        "👤 *USER PROFILE & WALLET*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📛 *Name:* `{user_info['name']}`\n"
        f"🆔 *User ID:* `{user_id}`\n"
        f"🔖 *Reg Number:* `{reg_id}`\n"
        f"⏱️ *Available Balance:* `{user_info['balance']} Minutes`\n"
        f"📞 *Phone:* `{user_info['phone']}`\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔗 *Refer & Earn Link:*\n"
        f"`{ref_link}`\n\n"
        "💡 *Apne dosto ko share karein aur rewards paayein!*"
    )
    bot.send_message(user_id, profile_text, reply_markup=get_main_keyboard(user_id))

# --- HELP & SUPPORT HANDLER ---

@bot.message_handler(func=lambda msg: msg.text in ["🆘 Help & Support", "Help & Support"])
def support_handler(message):
    user_id = message.chat.id
    text = (
        "🆘 *VYNORA LIVE SUPPORT*\n\n"
        "Agar aapko recharge, booking ya kisi bhi cheez me samasya aa rahi hai, toh kripya admin se sampark karein:\n\n"
        "💬 Support Admin: `@VynoraSupport`"
    )
    bot.send_message(user_id, text, reply_markup=get_main_keyboard(user_id))

# --- RECHARGE FLOW ---

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
        types.InlineKeyboardButton("💎 ₹600 — 30 Minutes", callback_data="payplan_600_30"),
        types.InlineKeyboardButton("👑 ₹800 — 40 Minutes", callback_data="payplan_800_40")
    )
    bot.send_message(message.chat.id, "💳 SELECT RECHARGE PLAN", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("payplan_"))
def show_plan_qr(call):
    _, amount, mins = call.data.split("_")
    user_id = call.message.chat.id
    save_user_plan(user_id, f"₹{amount} ({mins} Mins)")
    upi_url = f"upi://pay?pa={UPI_ID}&pn={urllib.parse.quote(PAYEE_NAME)}&am={amount}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={urllib.parse.quote(upi_url)}"
    bot.send_photo(user_id, qr_url, caption=f"🎯 SELECTED PLAN: ₹{amount} ({mins} Mins)\n\n📍 UPI ID: {UPI_ID}\n\n📲 Scan QR and Send Screenshot.")
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=["photo"])
def handle_screenshot(message):
    if message.chat.type == "private":
        photo_id = message.photo[-1].file_id
        user_id = message.chat.id
        txn_id = f"TXN{int(time.time())}"
        msg = bot.send_message(user_id, "📸 Screenshot Received!\n\n👇 Ab apna 12-digit UTR / UPI Reference Number type karke bhejein:")
        bot.register_next_step_handler(msg, process_utr_submission, photo_id, txn_id)

def process_utr_submission(message, photo_id, txn_id):
    user_id = message.chat.id
    utr_number = message.text.strip() if message.text else "N/A"
    selected_plan = get_user_plan(user_id)
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("1 Min (Rs.20)", callback_data=f"app_{user_id}_1_{txn_id}"),
        types.InlineKeyboardButton("5 Min (Rs.100)", callback_data=f"app_{user_id}_5_{txn_id}"),
        types.InlineKeyboardButton("10 Min (Rs.200)", callback_data=f"app_{user_id}_10_{txn_id}"),
        types.InlineKeyboardButton("20 Min (Rs.400)", callback_data=f"app_{user_id}_20_{txn_id}"),
        types.InlineKeyboardButton("30 Min (Rs.600)", callback_data=f"app_{user_id}_30_{txn_id}"),
        types.InlineKeyboardButton("40 Min (Rs.800)", callback_data=f"app_{user_id}_40_{txn_id}"),
        types.InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user_id}_{txn_id}")
    )
    caption = (
        "📸 *NEW RECHARGE SCREENSHOT SUBMISSION*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 *Date & Time:* `{current_time_str}`\n"
        f"👤 *User ID:* `{user_id}`\n"
        f"🎯 *Selected Plan:* `{selected_plan}`\n"
        f"🔢 *UTR Number:* `{utr_number}`\n"
        f"🔖 *TXN ID:* `{txn_id}`\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *Bina approval ke balance add nahi hoga.*"
    )
    sent_msg = bot.send_photo(ADMIN_GROUP_ID, photo_id, caption=caption, reply_markup=markup)
    save_pending_txn(txn_id, user_id, utr_number, sent_msg.message_id)
    bot.send_message(user_id, "⏳ *Verification Under Process!* Admin dwara verify hote hi minutes add kar diye jayenge.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(("app_", "rej_")))
def process_admin_recharge_approval(call):
    data = call.data.split("_")
    action, user_id = data[0], int(data[1])

    if action == "app":
        mins, txn_id = int(data[2]), data[3]
        txn_info = get_pending_txn(txn_id)
        add_user_balance(user_id, mins)

        if txn_info and txn_info.get("msg_id"):
            try:
                bot.delete_message(ADMIN_GROUP_ID, txn_info["msg_id"])
            except Exception:
                pass

        bot.send_message(ADMIN_GROUP_ID, f"✅ *PAYMENT APPROVED*\n👤 User ID: `{user_id}`\n💰 Credited: `{mins} Mins`")
        bot.send_message(user_id, f"✅ *Payment Approved!*\nAapke account mein *{mins} Minutes* add kar diye gaye hain.", reply_markup=get_main_keyboard(user_id))

    elif action == "rej":
        txn_id = data[2]
        txn_info = get_pending_txn(txn_id)
        if txn_info and txn_info.get("msg_id"):
            try:
                bot.delete_message(ADMIN_GROUP_ID, txn_info["msg_id"])
            except Exception:
                pass
        bot.send_message(user_id, "❌ Aapka payment verification admin dwara reject kar diya gaya hai.")
        bot.answer_callback_query(call.id, "Rejected successfully!")

if __name__ == "__main__":
    print("Vynora Bot Online - Inline Dashboard & All Features Active...")
    try:
        bot.remove_webhook()
    except Exception:
        pass
    bot.infinity_polling(skip_pending=True)
