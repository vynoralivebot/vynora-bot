import os
import sqlite3
import threading
import time
import uuid
import urllib.parse
from datetime import datetime, timedelta

import telebot
from telebot import types


# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")


ADMIN_GROUP_ID = int(
    os.environ.get(
        "ADMIN_GROUP_ID",
        "-1004325621712"
    )
)

REGISTERED_USER_GROUP_ID = int(
    os.environ.get(
        "REGISTERED_USER_GROUP_ID",
        "-1003698246938"
    )
)

UPI_ID = os.environ.get(
    "UPI_ID",
    "vynoralive@slc"
)

PAYEE_NAME = os.environ.get(
    "PAYEE_NAME",
    "Rajnish Kumar"
)


# ============================================================
# HOST GROUPS
# ============================================================

HOST_GROUPS = {
    "Host Priya 01": -1004312344325,
    "Host Ananya 02": -1004330981781,
    "Host Simran 03": -1004350353315,
    "Host Neha 04": -1003939071012,
    "Host Pooja 05": -1004293963082,
    "Host Riya 06": -1004459506130,
}


# ============================================================
# PAYMENT / HOST COMMISSION
# ============================================================

PLATFORM_CHARGE_PERCENT = 30
HOST_SHARE_PERCENT = 70


# ============================================================
# DATABASE
# ============================================================

DB_FILE = "vynora.db"


def get_db():
    conn = sqlite3.connect(
        DB_FILE,
        check_same_thread=False,
        timeout=30
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # Users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            username TEXT DEFAULT '',
            phone TEXT DEFAULT 'N/A',
            balance INTEGER DEFAULT 0,
            referred_by INTEGER DEFAULT 0,
            registered_at TEXT,
            last_seen TEXT
        )
    """)

    # Hosts
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hosts (
            user_id INTEGER PRIMARY KEY,
            host_name TEXT NOT NULL,
            group_id INTEGER NOT NULL,
            status TEXT DEFAULT 'OFFLINE',
            approved INTEGER DEFAULT 1,
            wallet INTEGER DEFAULT 0,
            total_minutes INTEGER DEFAULT 0,
            total_gross INTEGER DEFAULT 0,
            total_platform_charge INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    # Sessions
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            host_user_id INTEGER,
            host_name TEXT,
            group_id INTEGER,
            duration INTEGER,
            amount INTEGER,
            platform_charge INTEGER DEFAULT 0,
            host_earning INTEGER DEFAULT 0,
            status TEXT DEFAULT 'ACTIVE',
            created_at TEXT,
            expires_at TEXT
        )
    """)

    # Pending Payments
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_txns (
            txn_id TEXT PRIMARY KEY,
            user_id INTEGER,
            plan_minutes INTEGER,
            amount INTEGER,
            utr TEXT,
            msg_id INTEGER DEFAULT 0,
            status TEXT DEFAULT 'WAITING_PAYMENT',
            created_at TEXT,
            approved_at TEXT
        )
    """)

    # First Offer Tracking
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_plans (
            user_id INTEGER PRIMARY KEY,
            first_offer_used INTEGER DEFAULT 0
        )
    """)

    # Dynamic Plans Table (Command se add karne ke liye)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS custom_plans (
            minutes INTEGER PRIMARY KEY,
            amount INTEGER NOT NULL
        )
    """)

    # Default plans insert agar table khali ho
    cur.execute("SELECT COUNT(*) FROM custom_plans")
    if cur.fetchone()[0] == 0:
        default_plans = [
            (1, 20),
            (5, 100),
            (10, 200),
            (20, 400),
            (30, 600),
            (40, 800)
        ]
        cur.executemany(
            "INSERT OR IGNORE INTO custom_plans (minutes, amount) VALUES (?, ?)",
            default_plans
        )

    conn.commit()
    conn.close()


init_db()


# ============================================================
# BOT INSTANCE
# ============================================================

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="Markdown"
)


# ============================================================
# TIME HELPER
# ============================================================

def now_text():
    return datetime.now().strftime(
        "%d-%m-%Y %I:%M:%S %p"
    )


# ============================================================
# PLANS FUNCTIONS (DYNAMIC)
# ============================================================

def get_all_plans():
    conn = get_db()
    rows = conn.execute(
        "SELECT minutes, amount FROM custom_plans ORDER BY minutes ASC"
    ).fetchall()
    conn.close()
    return {row["minutes"]: row["amount"] for row in rows}


def add_custom_plan(minutes, amount):
    conn = get_db()
    conn.execute(
        """
        INSERT INTO custom_plans (minutes, amount)
        VALUES (?, ?)
        ON CONFLICT(minutes) DO UPDATE SET amount=excluded.amount
        """,
        (minutes, amount)
    )
    conn.commit()
    conn.close()


def remove_custom_plan(minutes):
    conn = get_db()
    conn.execute(
        "DELETE FROM custom_plans WHERE minutes=?",
        (minutes,)
    )
    conn.commit()
    conn.close()


# ============================================================
# USER FUNCTIONS
# ============================================================

def get_user(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()
    conn.close()
    return row


def register_user(user):
    user_id = user.id
    first_name = user.first_name or ""
    last_name = user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()
    username = user.username or ""

    existing = get_user(user_id)
    if existing:
        conn = get_db()
        conn.execute(
            """
            UPDATE users
            SET name=?, username=?, last_seen=?
            WHERE user_id=?
            """,
            (full_name, username, now_text(), user_id)
        )
        conn.commit()
        conn.close()
        return False

    conn = get_db()
    conn.execute(
        """
        INSERT INTO users
        (user_id, name, username, phone, balance, referred_by, registered_at, last_seen)
        VALUES (?, ?, ?, 'N/A', 0, 0, ?, ?)
        """,
        (user_id, full_name, username, now_text(), now_text())
    )
    conn.commit()
    conn.close()
    return True


def get_balance(user_id):
    user = get_user(user_id)
    if not user:
        return 0
    return int(user["balance"] or 0)


def add_balance(user_id, minutes):
    conn = get_db()
    conn.execute(
        "UPDATE users SET balance = balance + ? WHERE user_id=?",
        (minutes, user_id)
    )
    conn.commit()
    conn.close()


def deduct_balance(user_id, minutes):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE users
        SET balance = balance - ?
        WHERE user_id=? AND balance >= ?
        """,
        (minutes, user_id, minutes)
    )
    success = (cur.rowcount == 1)
    conn.commit()
    conn.close()
    return success


# ============================================================
# FIRST TIME OFFER CHECK
# ============================================================

def is_first_offer_available(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT first_offer_used FROM user_plans WHERE user_id=?",
        (user_id,)
    ).fetchone()
    conn.close()
    if not row:
        return True
    return int(row["first_offer_used"]) == 0


def mark_first_offer_used(user_id):
    conn = get_db()
    conn.execute(
        """
        INSERT INTO user_plans (user_id, first_offer_used)
        VALUES (?, 1)
        ON CONFLICT(user_id) DO UPDATE SET first_offer_used=1
        """,
        (user_id,)
    )
    conn.commit()
    conn.close()


# ============================================================
# HOST FUNCTIONS
# ============================================================

def get_host(host_user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM hosts WHERE user_id=?",
        (host_user_id,)
    ).fetchone()
    conn.close()
    return row


def add_host(host_user_id, host_name, group_id):
    conn = get_db()
    conn.execute(
        """
        INSERT INTO hosts
        (user_id, host_name, group_id, status, approved, wallet, total_minutes, total_gross, total_platform_charge, created_at)
        VALUES (?, ?, ?, 'OFFLINE', 1, 0, 0, 0, 0, ?)
        ON CONFLICT(user_id) DO UPDATE SET
        host_name=excluded.host_name,
        group_id=excluded.group_id,
        approved=1
        """,
        (host_user_id, host_name, group_id, now_text())
    )
    conn.commit()
    conn.close()


def remove_host(host_user_id):
    conn = get_db()
    conn.execute("DELETE FROM hosts WHERE user_id=?", (host_user_id,))
    conn.commit()
    conn.close()


def set_host_status(host_user_id, status):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE hosts SET status=? WHERE user_id=? AND approved=1",
        (status, host_user_id)
    )
    success = (cur.rowcount > 0)
    conn.commit()
    conn.close()
    return success


def get_online_hosts():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM hosts WHERE approved=1 AND status='ONLINE' ORDER BY host_name"
    ).fetchall()
    conn.close()
    return rows


def get_all_hosts():
    conn = get_db()
    rows = conn.execute("SELECT * FROM hosts ORDER BY host_name").fetchall()
    conn.close()
    return rows


# ============================================================
# COMMISSION CALCULATION (30% Platform, 70% Host)
# ============================================================

def calculate_host_earning(amount):
    platform_charge = int(round(amount * PLATFORM_CHARGE_PERCENT / 100))
    host_earning = amount - platform_charge
    return platform_charge, host_earning


def add_host_earning(host_user_id, minutes, amount):
    platform_charge, host_earning = calculate_host_earning(amount)
    conn = get_db()
    conn.execute(
        """
        UPDATE hosts
        SET
            wallet = wallet + ?,
            total_minutes = total_minutes + ?,
            total_gross = total_gross + ?,
            total_platform_charge = total_platform_charge + ?
        WHERE user_id=?
        """,
        (host_earning, minutes, amount, platform_charge, host_user_id)
    )
    conn.commit()
    conn.close()
    return platform_charge, host_earning


# ============================================================
# SESSION CREATION
# ============================================================

def create_session(user_id, host_user_id, host_name, group_id, minutes, amount):
    platform_charge, host_earning = calculate_host_earning(amount)
    created = datetime.now()
    expires = created + timedelta(minutes=minutes)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO sessions
        (user_id, host_user_id, host_name, group_id, duration, amount, platform_charge, host_earning, status, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
        """,
        (
            user_id, host_user_id, host_name, group_id, minutes, amount,
            platform_charge, host_earning,
            created.strftime("%Y-%m-%d %H:%M:%S"),
            expires.strftime("%Y-%m-%d %H:%M:%S")
        )
    )
    session_id = cur.lastrowid
    conn.commit()
    conn.close()
    return session_id, expires


def get_active_session(session_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM sessions WHERE id=? AND status='ACTIVE'",
        (session_id,)
    ).fetchone()
    conn.close()
    return row


def finish_session(session_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE sessions SET status='COMPLETED' WHERE id=? AND status='ACTIVE'",
        (session_id,)
    )
    success = (cur.rowcount == 1)
    conn.commit()
    conn.close()
    return success


# ============================================================
# INVITE LINK HELPER
# ============================================================

def create_private_invite(group_id, expires_at):
    try:
        expire_timestamp = int(expires_at.timestamp())
        invite = bot.create_chat_invite_link(
            chat_id=group_id,
            member_limit=1,
            expire_date=expire_timestamp
        )
        return invite.invite_link
    except Exception as e:
        print("Invite error:", e)
        try:
            invite = bot.create_chat_invite_link(
                chat_id=group_id,
                member_limit=1
            )
            return invite.invite_link
        except Exception as e2:
            print("Fallback invite error:", e2)
            return None


# ============================================================
# AUTO FINISH SESSION
# ============================================================

def auto_finish_session(session_id):
    session = get_active_session(session_id)
    if not session:
        return

    user_id = session["user_id"]
    host_user_id = session["host_user_id"]
    host_name = session["host_name"]
    group_id = session["group_id"]
    minutes = session["duration"]
    amount = session["amount"]
    platform_charge = session["platform_charge"]
    host_earning = session["host_earning"]

    # Remove user from group
    try:
        bot.ban_chat_member(chat_id=group_id, user_id=user_id)
        try:
            bot.unban_chat_member(chat_id=group_id, user_id=user_id, only_if_banned=True)
        except Exception:
            pass
    except Exception as e:
        print("Remove user error:", e)

    if not finish_session(session_id):
        return

    add_host_earning(host_user_id, minutes, amount)

    # User notification
    try:
        bot.send_message(
            user_id,
            f"""
⏰ *CALL COMPLETED*

👑 Host: *{host_name}*
⏱ Duration: *{minutes} Minutes*
💰 Paid: ₹{amount}
💳 Remaining Wallet: *{get_balance(user_id)} Minutes*

Thank you for using *Vynora Live*.
"""
        )
    except Exception:
        pass

    # Host notification
    try:
        stats = get_host(host_user_id)
        bot.send_message(
            host_user_id,
            f"""
💰 *CALL EARNING RECEIVED*

👑 Host: *{host_name}*
⏱ Call: *{minutes} Minutes*
💵 Customer Payment: ₹{amount}
➖ Platform Charge (30%): ₹{platform_charge}
💰 *Your Earning (70%): ₹{host_earning}*

━━━━━━━━━━━━━━
💳 Wallet: *₹{stats["wallet"]}*
⏱ Total Worked: *{stats["total_minutes"]} Minutes*
"""
        )
    except Exception:
        pass

    # Host group notification
    try:
        bot.send_message(
            group_id,
            f"""
✅ *CALL COMPLETED*

👑 Host: *{host_name}*
⏱ Duration: *{minutes} Minutes*
💰 Customer Payment: ₹{amount}
➖ Platform Charge: ₹{platform_charge}
💵 Host Earning: *₹{host_earning}*

👤 User has been removed automatically.
"""
        )
    except Exception:
        pass

    # Admin group notification
    try:
        bot.send_message(
            ADMIN_GROUP_ID,
            f"""
✅ *SESSION COMPLETED*

👤 User ID: `{user_id}`
👑 Host: *{host_name}* (`{host_user_id}`)
⏱ Duration: *{minutes} Minutes*
💰 Customer Paid: ₹{amount}
➖ Platform Charge: ₹{platform_charge}
💰 Host Earning: ₹{host_earning}
🆔 Session ID: `{session_id}`
📅 Completed: {now_text()}
"""
        )
    except Exception:
        pass


# ============================================================
# KEYBOARDS
# ============================================================

def main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🔥 Book Host Session")
    kb.row("💳 Recharge Minutes", "👤 Profile")
    kb.row("🆘 Help & Support")
    return kb


def host_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🟢 GO ONLINE", "🔴 GO OFFLINE")
    kb.row("💰 My Earnings", "📊 My Stats")
    return kb


# ============================================================
# START HANDLER
# ============================================================

@bot.message_handler(commands=["start"])
def start_handler(message):
    user = message.from_user
    is_new = register_user(user)

    host = get_host(user.id)
    if host and int(host["approved"]) == 1:
        bot.send_message(
            message.chat.id,
            f"""
👑 *VYNORA LIVE HOST PANEL*

Welcome: *{host["host_name"]}*
📡 Status: *{host["status"]}*
Use the buttons below.
""",
            reply_markup=host_keyboard()
        )
        return

    if is_new:
        username = f"@{user.username}" if user.username else "N/A"
        try:
            bot.send_message(
                REGISTERED_USER_GROUP_ID,
                f"""
🆕 *NEW USER REGISTERED*

👤 Name: {user.first_name or "N/A"}
🔗 Username: {username}
🆔 User ID: `{user.id}`
📅 Joining Date & Time: {now_text()}
💰 Wallet: 0 Minutes
"""
            )
        except Exception:
            pass

    bot.send_message(
        message.chat.id,
        f"""
🔥 *WELCOME TO VYNORA LIVE*

👤 User: *{user.first_name or "User"}*
💳 Wallet: *{get_balance(user.id)} Minutes*

Book a private 1-to-1 host session. Select an option below.
""",
        reply_markup=main_keyboard()
    )


# ============================================================
# RECHARGE MENU
# ============================================================

@bot.message_handler(func=lambda m: m.text == "💳 Recharge Minutes")
def recharge_handler(message):
    user_id = message.from_user.id
    kb = types.InlineKeyboardMarkup()

    # First time offer
    if is_first_offer_available(user_id):
        kb.add(
            types.InlineKeyboardButton(
                "🔥 FIRST CALL — 1 MIN ₹20",
                callback_data="plan:1:20:first"
            )
        )

    # Dynamic Plans from DB
    plans = get_all_plans()
    for minutes, amount in plans.items():
        kb.add(
            types.InlineKeyboardButton(
                f"{minutes} MIN — ₹{amount}",
                callback_data=f"plan:{minutes}:{amount}"
            )
        )

    bot.send_message(
        message.chat.id,
        """
💳 *RECHARGE MINUTES*

🔥 *FIRST TIME USER*
1 Minute — ₹20

━━━━━━━━━━━━━━
📦 *REGULAR & CUSTOM PLANS*
Select your plan below.
""",
        reply_markup=kb
    )


# ============================================================
# PLAN SELECT & PAYMENT
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("plan:"))
def plan_callback(call):
    bot.answer_callback_query(call.id)
    parts = call.data.split(":")
    minutes = int(parts[1])
    amount = int(parts[2])
    is_first = (len(parts) > 3 and parts[3] == "first")

    if is_first and not is_first_offer_available(call.from_user.id):
        bot.send_message(call.message.chat.id, "❌ First-time offer already used.")
        return

    txn_id = "TXN-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6].upper()

    conn = get_db()
    conn.execute(
        """
        INSERT INTO pending_txns
        (txn_id, user_id, plan_minutes, amount, utr, msg_id, status, created_at)
        VALUES (?, ?, ?, ?, '', 0, 'WAITING_PAYMENT', ?)
        """,
        (txn_id, call.from_user.id, minutes, amount, now_text())
    )
    conn.commit()
    conn.close()

    upi_data = f"upi://pay?pa={urllib.parse.quote(UPI_ID)}&pn={urllib.parse.quote(PAYEE_NAME)}&am={amount}&cu=INR"
    qr_url = "https://api.qrserver.com/v1/create-qr-code/?size=400x400&data=" + urllib.parse.quote(upi_data)

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton(
            "📸 UPLOAD PAYMENT SCREENSHOT",
            callback_data=f"upload:{txn_id}"
        )
    )

    bot.send_message(
        call.message.chat.id,
        f"""
💳 *PAYMENT DETAILS*

📦 Plan: *{minutes} Minutes*
💰 Amount: *₹{amount}*
🆔 Transaction ID: `{txn_id}`
🏦 UPI ID: `{UPI_ID}`
👤 Payee: *{PAYEE_NAME}*

━━━━━━━━━━━━━━
1. Pay the exact amount.
2. Upload screenshot.
3. Enter UTR number.
""",
        reply_markup=kb
    )

    try:
        bot.send_photo(
            call.message.chat.id,
            qr_url,
            caption=f"📲 *SCAN & PAY*\nAmount: ₹{amount}\nUPI: `{UPI_ID}`"
        )
    except Exception as e:
        print("QR error:", e)


@bot.callback_query_handler(func=lambda call: call.data.startswith("upload:"))
def upload_callback(call):
    bot.answer_callback_query(call.id)
    txn_id = call.data.split(":", 1)[1]
    bot.send_message(call.message.chat.id, f"📸 *UPLOAD PAYMENT SCREENSHOT*\nTransaction: `{txn_id}`\nPlease send the screenshot as a photo.")
    bot.register_next_step_handler(call.message, receive_payment_screenshot, txn_id)


def receive_payment_screenshot(message, txn_id):
    if not message.photo:
        bot.send_message(message.chat.id, "❌ Please send the screenshot as a photo.")
        bot.register_next_step_handler(message, receive_payment_screenshot, txn_id)
        return

    screenshot_file_id = message.photo[-1].file_id
    bot.send_message(message.chat.id, f"✅ *SCREENSHOT RECEIVED*\nTransaction: `{txn_id}`\nNow send your *UTR / Transaction Number*.")
    bot.register_next_step_handler(message, receive_utr, txn_id, screenshot_file_id)


def receive_utr(message, txn_id, screenshot_file_id):
    utr = (message.text or "").strip()
    if len(utr) < 4:
        bot.send_message(message.chat.id, "❌ Invalid UTR. Please enter the correct UTR.")
        bot.register_next_step_handler(message, receive_utr, txn_id, screenshot_file_id)
        return

    conn = get_db()
    txn = conn.execute("SELECT * FROM pending_txns WHERE txn_id=?", (txn_id,)).fetchone()
    if not txn:
        conn.close()
        bot.send_message(message.chat.id, "❌ Transaction not found.")
        return

    conn.execute("UPDATE pending_txns SET utr=?, status='PENDING' WHERE txn_id=?", (utr, txn_id))
    conn.commit()
    conn.close()

    user = message.from_user
    username = f"@{user.username}" if user.username else "N/A"

    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ APPROVE", callback_data=f"approve:{txn_id}"),
        types.InlineKeyboardButton("❌ REJECT", callback_data=f"reject:{txn_id}")
    )

    admin_text = f"""
💳 *NEW PAYMENT VERIFICATION*

👤 Name: {user.first_name or "N/A"}
🔗 Username: {username}
🆔 User ID: `{user.id}`
🆔 Transaction: `{txn_id}`
📦 Minutes: *{txn["plan_minutes"]}*
💰 Amount: *₹{txn["amount"]}*
🔢 UTR: `{utr}`
📅 Submitted: {now_text()}
"""

    try:
        sent = bot.send_photo(ADMIN_GROUP_ID, screenshot_file_id, caption=admin_text, reply_markup=kb)
        conn = get_db()
        conn.execute("UPDATE pending_txns SET msg_id=? WHERE txn_id=?", (sent.message_id, txn_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print("Admin payment message error:", e)

    bot.send_message(message.chat.id, "✅ *PAYMENT SUBMITTED*\nUnder verification by admin.")


# ============================================================
# ADMIN PAYMENT APPROVAL & REJECTION
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("approve:"))
def approve_payment(call):
    if call.message.chat.id != ADMIN_GROUP_ID:
        bot.answer_callback_query(call.id, "Not authorized.", show_alert=True)
        return

    txn_id = call.data.split(":", 1)[1]
    conn = get_db()
    txn = conn.execute("SELECT * FROM pending_txns WHERE txn_id=?", (txn_id,)).fetchone()

    if not txn or txn["status"] != "PENDING":
        conn.close()
        bot.answer_callback_query(call.id, "Invalid or already processed transaction.", show_alert=True)
        return

    user_id = int(txn["user_id"])
    minutes = int(txn["plan_minutes"])

    conn.execute("UPDATE pending_txns SET status='APPROVED', approved_at=? WHERE txn_id=?", (now_text(), txn_id))
    conn.commit()
    conn.close()

    add_balance(user_id, minutes)
    if minutes == 1:
        mark_first_offer_used(user_id)

    try:
        bot.edit_message_reply_markup(ADMIN_GROUP_ID, call.message.message_id, reply_markup=None)
    except Exception:
        pass

    try:
        bot.send_message(
            user_id,
            f"""
✅ *PAYMENT APPROVED*

🆔 Transaction: `{txn_id}`
💰 Paid: ₹{txn["amount"]}
➕ Added: *{minutes} Minutes*
💳 Wallet: *{get_balance(user_id)} Minutes*
"""
        )
    except Exception:
        pass

    bot.answer_callback_query(call.id, "Payment approved.")
    bot.send_message(ADMIN_GROUP_ID, f"✅ *PAYMENT APPROVED*\nUser ID: `{user_id}`\nMinutes: *{minutes}*")


@bot.callback_query_handler(func=lambda call: call.data.startswith("reject:"))
def reject_payment(call):
    if call.message.chat.id != ADMIN_GROUP_ID:
        bot.answer_callback_query(call.id, "Not authorized.", show_alert=True)
        return

    txn_id = call.data.split(":", 1)[1]
    conn = get_db()
    txn = conn.execute("SELECT * FROM pending_txns WHERE txn_id=?", (txn_id,)).fetchone()

    if not txn:
        conn.close()
        bot.answer_callback_query(call.id, "Transaction not found.", show_alert=True)
        return

    conn.execute("UPDATE pending_txns SET status='REJECTED' WHERE txn_id=?", (txn_id,))
    conn.commit()
    conn.close()

    try:
        bot.send_message(txn["user_id"], f"❌ *PAYMENT REJECTED*\nTransaction: `{txn_id}`")
        bot.edit_message_reply_markup(ADMIN_GROUP_ID, call.message.message_id, reply_markup=None)
    except Exception:
        pass

    bot.answer_callback_query(call.id, "Payment rejected.")


# ============================================================
# BOOK HOST & SESSIONS
# ============================================================

@bot.message_handler(func=lambda m: m.text == "🔥 Book Host Session")
def book_host(message):
    user_id = message.from_user.id
    balance = get_balance(user_id)

    if balance <= 0:
        bot.send_message(message.chat.id, "❌ *NO MINUTES AVAILABLE*\nPlease recharge first.", reply_markup=main_keyboard())
        return

    hosts = get_online_hosts()
    if not hosts:
        bot.send_message(message.chat.id, "😔 *NO HOST ONLINE*\nPlease try again later.")
        return

    kb = types.InlineKeyboardMarkup()
    for host in hosts:
        kb.add(types.InlineKeyboardButton(f"🟢 {host['host_name']}", callback_data=f"hsel:{host['user_id']}"))

    bot.send_message(message.chat.id, f"👑 *ONLINE HOSTS*\n💳 Your Wallet: *{balance} Minutes*\nSelect a host below.", reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("hsel:"))
def host_select(call):
    bot.answer_callback_query(call.id)
    host_id = int(call.data.split(":")[1])
    host = get_host(host_id)

    if not host or host["status"] != "ONLINE":
        bot.send_message(call.message.chat.id, "❌ Host not found or offline.")
        return

    user_id = call.from_user.id
    balance = get_balance(user_id)
    kb = types.InlineKeyboardMarkup()

    if is_first_offer_available(user_id):
        kb.add(types.InlineKeyboardButton("🔥 FIRST CALL — 1 MIN ₹20", callback_data=f"book:{host_id}:1:20"))

    plans = get_all_plans()
    for minutes, amount in plans.items():
        if balance >= minutes:
            kb.add(types.InlineKeyboardButton(f"{minutes} MIN — ₹{amount}", callback_data=f"book:{host_id}:{minutes}:{amount}"))

    bot.send_message(call.message.chat.id, f"👑 *{host['host_name']}*\nSelect call duration:", reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("book:"))
def booking_callback(call):
    bot.answer_callback_query(call.id)
    parts = call.data.split(":")
    host_id = int(parts[1])
    minutes = int(parts[2])
    amount = int(parts[3])
    user_id = call.from_user.id

    host = get_host(host_id)
    if not host or host["status"] != "ONLINE":
        bot.send_message(call.message.chat.id, "❌ Host is offline.")
        return

    if get_balance(user_id) < minutes:
        bot.send_message(call.message.chat.id, "❌ Not enough minutes.")
        return

    if not deduct_balance(user_id, minutes):
        bot.send_message(call.message.chat.id, "❌ Booking failed.")
        return

    if minutes == 1:
        mark_first_offer_used(user_id)

    session_id, expires_at = create_session(user_id, host_id, host["host_name"], host["group_id"], minutes, amount)
    invite_link = create_private_invite(host["group_id"], expires_at)

    if not invite_link:
        add_balance(user_id, minutes)
        conn = get_db()
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        conn.commit()
        conn.close()
        bot.send_message(call.message.chat.id, "❌ Group invite creation failed. Minutes refunded.")
        return

    user = get_user(user_id)
    username = f"@{user['username']}" if user and user["username"] else "N/A"
    platform_charge, host_earning = calculate_host_earning(amount)

    # User Notification
    bot.send_message(
        user_id,
        f"""
✅ *BOOKING CONFIRMED*

👑 Host: *{host["host_name"]}*
⏱ Duration: *{minutes} Minutes*
💰 Paid: ₹{amount}
💳 Remaining: *{get_balance(user_id)} Minutes*

━━━━━━━━━━━━━━
🔗 *PRIVATE GROUP LINK*
{invite_link}
━━━━━━━━━━━━━━
⏰ Session End: *{expires_at.strftime("%d-%m-%Y %I:%M %p")}*
⚠️ You will automatically be removed when session ends.
"""
    )

    # Admin Notification
    try:
        bot.send_message(
            ADMIN_GROUP_ID,
            f"""
🔥 *NEW HOST BOOKING*
👤 User: {user["name"] if user else "N/A"} (`{user_id}`)
👑 Host: *{host["host_name"]}*
⏱ Duration: *{minutes} Minutes*
💰 Paid: ₹{amount} (Platform: ₹{platform_charge} | Host: ₹{host_earning})
🆔 Session: `{session_id}`
"""
        )
    except Exception:
        pass

    # Host Group Notification
    try:
        bot.send_message(
            host["group_id"],
            f"""
🔥 *NEW BOOKING*
👑 Host: *{host["host_name"]}*
👤 User: {user["name"] if user else "N/A"} (`{user_id}`)
⏱ Duration: *{minutes} Minutes*
💰 Gross: ₹{amount} | Host Share: *₹{host_earning}*
🆔 Session: `{session_id}`
"""
        )
    except Exception:
        pass

    # Timer for Session End
    timer = threading.Timer(minutes * 60, auto_finish_session, args=(session_id,))
    timer.daemon = True
    timer.start()


# ============================================================
# USER PROFILE
# ============================================================

@bot.message_handler(func=lambda m: m.text == "👤 Profile")
def profile_handler(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        register_user(message.from_user)
        user = get_user(user_id)

    username = f"@{user['username']}" if user["username"] else "N/A"
    plans_text = ""
    for mins, amt in get_all_plans().items():
        plans_text += f"• {mins} Minute — ₹{amt}\n"

    bot.send_message(
        message.chat.id,
        f"""
👤 *MY PROFILE*

Name: *{user["name"]}*
Username: {username}
User ID: `{user_id}`
Wallet: *{user["balance"]} Minutes*

🔥 *ACTIVE PLANS*
{plans_text}
"""
    )


# ============================================================
# HOST PANEL COMMANDS
# ============================================================

@bot.message_handler(func=lambda m: m.text == "🟢 GO ONLINE")
def host_online(message):
    host = get_host(message.from_user.id)
    if not host:
        bot.send_message(message.chat.id, "❌ Not an approved host.")
        return
    set_host_status(message.from_user.id, "ONLINE")
    bot.send_message(message.chat.id, f"🟢 *YOU ARE ONLINE* ({host['host_name']})", reply_markup=host_keyboard())


@bot.message_handler(func=lambda m: m.text == "🔴 GO OFFLINE")
def host_offline(message):
    host = get_host(message.from_user.id)
    if not host:
        bot.send_message(message.chat.id, "❌ Not an approved host.")
        return
    set_host_status(message.from_user.id, "OFFLINE")
    bot.send_message(message.chat.id, f"🔴 *YOU ARE OFFLINE* ({host['host_name']})", reply_markup=host_keyboard())


@bot.message_handler(func=lambda m: m.text == "💰 My Earnings")
def host_earnings(message):
    host = get_host(message.from_user.id)
    if not host:
        return
    bot.send_message(
        message.chat.id,
        f"""
💰 *MY HOST WALLET*
👑 Host: *{host["host_name"]}*
⏱ Total Worked: *{host["total_minutes"]} Minutes*
💵 Gross: ₹{host["total_gross"]}
➖ Platform Charge (30%): ₹{host["total_platform_charge"]}
💰 *Your Wallet (70%): ₹{host["wallet"]}*
"""
    )


@bot.message_handler(func=lambda m: m.text == "📊 My Stats")
def host_stats(message):
    host = get_host(message.from_user.id)
    if not host:
        return
    bot.send_message(
        message.chat.id,
        f"""
📊 *HOST STATISTICS*
Status: *{host["status"]}*
Minutes: *{host["total_minutes"]}*
Wallet: *₹{host["wallet"]}*
"""
    )


# ============================================================
# ADMIN MANAGEMENT COMMANDS (ADD/REMOVE PLANS, HOSTS, BROADCAST)
# ============================================================

@bot.message_handler(commands=["addplan"])
def admin_add_plan(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "❌ Format: `/addplan MINUTES AMOUNT`\nExample: `/addplan 15 300`")
        return
    try:
        mins = int(parts[1])
        amt = int(parts[2])
        add_custom_plan(mins, amt)
        bot.reply_to(message, f"✅ Plan added/updated successfully: *{mins} Minutes* = *₹{amt}*")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["removeplan"])
def admin_remove_plan(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "❌ Format: `/removeplan MINUTES`\nExample: `/removeplan 15`")
        return
    try:
        mins = int(parts[1])
        remove_custom_plan(mins)
        bot.reply_to(message, f"✅ Plan for *{mins} Minutes* removed successfully.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["addhost"])
def admin_add_host(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    parts = message.text.split()
    if len(parts) < 4:
        bot.reply_to(message, "❌ Format: `/addhost HOST_ID HOST_NAME GROUP_ID`")
        return
    try:
        host_user_id = int(parts[1])
        group_id = int(parts[-1])
        host_name = " ".join(parts[2:-1])
        add_host(host_user_id, host_name, group_id)
        bot.reply_to(message, f"✅ Host *{host_name}* added & approved successfully.")
        try:
            bot.send_message(host_user_id, "🎉 *HOST ACCOUNT APPROVED*\nOpen bot and send `/start`.")
        except Exception:
            pass
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["removehost"])
def admin_remove_host(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "❌ Format: `/removehost HOST_ID`")
        return
    try:
        host_id = int(parts[1])
        remove_host(host_id)
        bot.reply_to(message, f"✅ Host `{host_id}` removed.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["addmins", "givemins"])
def admin_add_minutes(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "❌ Format: `/addmins USER_ID MINUTES`")
        return
    try:
        user_id = int(parts[1])
        mins = int(parts[2])
        add_balance(user_id, mins)
        bot.reply_to(message, f"✅ Added *{mins} Minutes* to user `{user_id}`.")
        try:
            bot.send_message(user_id, f"🎁 *ADMIN CREDIT*\nAdded: *{mins} Minutes*")
        except Exception:
            pass
    except Exception as e:
        bot.reply_to(message, f"❌ {e}")


# ============================================================
# BROADCAST / ANNOUNCEMENT COMMAND
# ============================================================

@bot.message_handler(commands=["broadcast"])
def broadcast_message(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return

    text = message.text[len("/broadcast"):].strip()
    if not text:
        bot.reply_to(message, "❌ Please provide message text.\nExample: `/broadcast Hello users!`")
        return

    conn = get_db()
    users = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()

    total = len(users)
    sent = 0
    failed = 0

    status_message = bot.reply_to(message, f"📢 *BROADCAST STARTED*\nTotal Users: *{total}*\nSending...")

    for row in users:
        user_id = row["user_id"]
        try:
            bot.send_message(
                user_id,
                f"""
📢 *ANNOUNCEMENT*

{text}
"""
            )
            sent += 1
            time.sleep(0.04)
        except Exception:
            failed += 1

    try:
        bot.edit_message_text(
            f"""
✅ *BROADCAST COMPLETED*
👥 Total: *{total}*
✅ Sent: *{sent}*
❌ Failed: *{failed}*
""",
            ADMIN_GROUP_ID,
            status_message.message_id
        )
    except Exception:
        pass


# ============================================================
# HELP & FALLBACK
# ============================================================

@bot.message_handler(func=lambda m: m.text == "🆘 Help & Support")
def help_handler(message):
    bot.send_message(
        message.chat.id,
        f"""
🆘 *VYNORA LIVE SUPPORT*
WhatsApp: `+91 8417046044`
UPI: `{UPI_ID}`
"""
    )


@bot.message_handler(func=lambda m: True, content_types=["text"])
def fallback_handler(message):
    host = get_host(message.from_user.id)
    if host and int(host["approved"]) == 1:
        bot.send_message(message.chat.id, "Please use the host panel buttons.", reply_markup=host_keyboard())
        return
    bot.send_message(message.chat.id, "Please use the menu buttons.", reply_markup=main_keyboard())


# ============================================================
# MAIN LOOP
# ============================================================

if __name__ == "__main__":
    print("====================================")
    print("VYNORA LIVE BOT STARTED")
    print("====================================")
    try:
        bot.remove_webhook()
    except Exception:
        pass

    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
