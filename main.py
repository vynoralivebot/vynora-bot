import os
import sqlite3
import threading
import time
import uuid
import urllib.parse
from datetime import datetime, timedelta

import telebot
from telebot import types
from flask import Flask, request


# ============================================================
# VYNORA LIVE BOT
# Render Web Service + Telegram Webhook
# Google Sheets logic removed
# ============================================================


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

# Optional. If empty, RENDER_EXTERNAL_URL will be used.
WEBHOOK_URL = os.environ.get(
    "WEBHOOK_URL",
    ""
).strip()

# Optional extra Telegram webhook security.
WEBHOOK_SECRET = os.environ.get(
    "WEBHOOK_SECRET",
    ""
).strip()

PORT = int(
    os.environ.get(
        "PORT",
        "10000"
    )
)


# ============================================================
# HOST GROUPS
# ============================================================

HOST_GROUPS = {

    "Host Priya 01":
        -1004312344325,

    "Host Ananya 02":
        -1004330981781,

    "Host Simran 03":
        -1004350353315,

    "Host Neha 04":
        -1003939071012,

    "Host Pooja 05":
        -1004293963082,

    "Host Riya 06":
        -1004459506130,
}


# ============================================================
# PAYMENT / HOST COMMISSION
# ============================================================

PLATFORM_CHARGE_PERCENT = 30
HOST_SHARE_PERCENT = 70


PLANS = {
    5: 100,
    10: 200,
    20: 400,
    30: 600,
    40: 800,
}


FIRST_TIME_MINUTES = 1
FIRST_TIME_AMOUNT = 20


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

    conn.execute(
        "PRAGMA journal_mode=WAL"
    )

    conn.execute(
        "PRAGMA busy_timeout=30000"
    )

    return conn


def init_db():

    conn = get_db()
    cur = conn.cursor()

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_plans (
            user_id INTEGER PRIMARY KEY,
            first_offer_used INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


init_db()


# ============================================================
# BOT
# ============================================================

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="Markdown"
)


# ============================================================
# FLASK / RENDER WEB SERVER
# ============================================================

app = Flask(__name__)


@app.get("/")
def health_check():
    return "Vynora Live Bot is running", 200


@app.get("/health")
def health():
    return "OK", 200


@app.post("/webhook")
def telegram_webhook():

    if WEBHOOK_SECRET:
        incoming_secret = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token",
            ""
        )

        if incoming_secret != WEBHOOK_SECRET:
            return "Unauthorized", 401

    try:
        update_data = request.get_data(
            as_text=True
        )

        if update_data:
            update = telebot.types.Update.de_json(
                update_data
            )

            bot.process_new_updates(
                [update]
            )

        return "OK", 200

    except Exception as e:

        print(
            "Webhook processing error:",
            e
        )

        return "OK", 200


# ============================================================
# TIME
# ============================================================

def now_text():

    return datetime.now().strftime(
        "%d-%m-%Y %I:%M:%S %p"
    )


# ============================================================
# USER FUNCTIONS
# ============================================================

def get_user(user_id):

    conn = get_db()

    row = conn.execute(
        """
        SELECT *
        FROM users
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()

    conn.close()

    return row


def register_user(user):

    user_id = user.id

    first_name = user.first_name or ""
    last_name = user.last_name or ""

    full_name = (
        f"{first_name} {last_name}"
    ).strip()

    username = user.username or ""

    existing = get_user(user_id)

    if existing:

        conn = get_db()

        conn.execute(
            """
            UPDATE users
            SET
                name=?,
                username=?,
                last_seen=?
            WHERE user_id=?
            """,
            (
                full_name,
                username,
                now_text(),
                user_id
            )
        )

        conn.commit()
        conn.close()

        return False

    conn = get_db()

    conn.execute(
        """
        INSERT INTO users
        (
            user_id,
            name,
            username,
            phone,
            balance,
            referred_by,
            registered_at,
            last_seen
        )
        VALUES
        (?, ?, ?, 'N/A', 0, 0, ?, ?)
        """,
        (
            user_id,
            full_name,
            username,
            now_text(),
            now_text()
        )
    )

    conn.commit()
    conn.close()

    return True


def get_balance(user_id):

    user = get_user(user_id)

    if not user:
        return 0

    return int(
        user["balance"] or 0
    )


def add_balance(
    user_id,
    minutes
):

    conn = get_db()

    conn.execute(
        """
        UPDATE users
        SET balance = balance + ?
        WHERE user_id=?
        """,
        (
            minutes,
            user_id
        )
    )

    conn.commit()
    conn.close()


def deduct_balance(
    user_id,
    minutes
):

    conn = get_db()

    cur = conn.cursor()

    cur.execute(
        """
        UPDATE users
        SET balance = balance - ?
        WHERE user_id=?
        AND balance >= ?
        """,
        (
            minutes,
            user_id,
            minutes
        )
    )

    success = (
        cur.rowcount == 1
    )

    conn.commit()
    conn.close()

    return success


# ============================================================
# FIRST TIME OFFER
# ============================================================

def is_first_offer_available(
    user_id
):

    conn = get_db()

    row = conn.execute(
        """
        SELECT first_offer_used
        FROM user_plans
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()

    conn.close()

    if not row:
        return True

    return int(
        row["first_offer_used"]
    ) == 0


def mark_first_offer_used(
    user_id
):

    conn = get_db()

    conn.execute(
        """
        INSERT INTO user_plans
        (
            user_id,
            first_offer_used
        )
        VALUES (?, 1)

        ON CONFLICT(user_id)

        DO UPDATE SET
            first_offer_used=1
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
        """
        SELECT *
        FROM hosts
        WHERE user_id=?
        """,
        (host_user_id,)
    ).fetchone()

    conn.close()

    return row


def add_host(
    host_user_id,
    host_name,
    group_id
):

    conn = get_db()

    conn.execute(
        """
        INSERT INTO hosts
        (
            user_id,
            host_name,
            group_id,
            status,
            approved,
            wallet,
            total_minutes,
            total_gross,
            total_platform_charge,
            created_at
        )
        VALUES
        (
            ?, ?, ?, 'OFFLINE',
            1, 0, 0, 0, 0, ?
        )
        ON CONFLICT(user_id)
        DO UPDATE SET
            host_name=excluded.host_name,
            group_id=excluded.group_id,
            approved=1
        """,
        (
            host_user_id,
            host_name,
            group_id,
            now_text()
        )
    )

    conn.commit()
    conn.close()


def remove_host(
    host_user_id
):

    conn = get_db()

    conn.execute(
        """
        DELETE FROM hosts
        WHERE user_id=?
        """,
        (host_user_id,)
    )

    conn.commit()
    conn.close()


def set_host_status(
    host_user_id,
    status
):

    conn = get_db()

    cur = conn.cursor()

    cur.execute(
        """
        UPDATE hosts
        SET status=?
        WHERE user_id=?
        AND approved=1
        """,
        (
            status,
            host_user_id
        )
    )

    success = (
        cur.rowcount > 0
    )

    conn.commit()
    conn.close()

    return success


def get_online_hosts():

    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM hosts
        WHERE approved=1
        AND status='ONLINE'
        ORDER BY host_name
        """
    ).fetchall()

    conn.close()

    return rows


def get_all_hosts():

    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM hosts
        ORDER BY host_name
        """
    ).fetchall()

    conn.close()

    return rows


# ============================================================
# HOST EARNING CALCULATION
# ============================================================

def calculate_host_earning(
    amount
):

    platform_charge = int(
        round(
            amount *
            PLATFORM_CHARGE_PERCENT /
            100
        )
    )

    host_earning = (
        amount -
        platform_charge
    )

    return (
        platform_charge,
        host_earning
    )


def add_host_earning(
    host_user_id,
    minutes,
    amount
):

    platform_charge, host_earning = \
        calculate_host_earning(
            amount
        )

    conn = get_db()

    conn.execute(
        """
        UPDATE hosts
        SET
            wallet = wallet + ?,
            total_minutes = total_minutes + ?,
            total_gross = total_gross + ?,
            total_platform_charge =
                total_platform_charge + ?
        WHERE user_id=?
        """,
        (
            host_earning,
            minutes,
            amount,
            platform_charge,
            host_user_id
        )
    )

    conn.commit()
    conn.close()

    return (
        platform_charge,
        host_earning
    )


# ============================================================
# SESSION CREATION
# ============================================================

def create_session(
    user_id,
    host_user_id,
    host_name,
    group_id,
    minutes,
    amount
):

    platform_charge, host_earning = \
        calculate_host_earning(
            amount
        )

    created = datetime.now()

    expires = (
        created +
        timedelta(
            minutes=minutes
        )
    )

    conn = get_db()

    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO sessions
        (
            user_id,
            host_user_id,
            host_name,
            group_id,
            duration,
            amount,
            platform_charge,
            host_earning,
            status,
            created_at,
            expires_at
        )
        VALUES
        (
            ?, ?, ?, ?, ?, ?,
            ?, ?, 'ACTIVE', ?, ?
        )
        """,
        (
            user_id,
            host_user_id,
            host_name,
            group_id,
            minutes,
            amount,
            platform_charge,
            host_earning,
            created.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            expires.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )
    )

    session_id = cur.lastrowid

    conn.commit()
    conn.close()

    return (
        session_id,
        expires
    )


def get_active_session(
    session_id
):

    conn = get_db()

    row = conn.execute(
        """
        SELECT *
        FROM sessions
        WHERE id=?
        AND status='ACTIVE'
        """,
        (session_id,)
    ).fetchone()

    conn.close()

    return row


def finish_session(
    session_id
):

    conn = get_db()

    cur = conn.cursor()

    cur.execute(
        """
        UPDATE sessions
        SET status='COMPLETED'
        WHERE id=?
        AND status='ACTIVE'
        """,
        (session_id,)
    )

    success = (
        cur.rowcount == 1
    )

    conn.commit()
    conn.close()

    return success


# ============================================================
# RECOVER ACTIVE SESSIONS AFTER RESTART
# ============================================================

def recover_active_sessions():

    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM sessions
        WHERE status='ACTIVE'
        """
    ).fetchall()

    conn.close()

    now = datetime.now()

    for session in rows:

        try:

            expires_at = datetime.strptime(
                session["expires_at"],
                "%Y-%m-%d %H:%M:%S"
            )

            remaining = (
                expires_at - now
            ).total_seconds()

            if remaining <= 0:

                threading.Thread(
                    target=auto_finish_session,
                    args=(session["id"],),
                    daemon=True
                ).start()

            else:

                timer = threading.Timer(
                    remaining,
                    auto_finish_session,
                    args=(session["id"],)
                )

                timer.daemon = True
                timer.start()

        except Exception as e:

            print(
                "Session recovery error:",
                e
            )


# ============================================================
# INVITE LINK
# ============================================================

def create_private_invite(
    group_id,
    expires_at
):

    try:

        expire_timestamp = int(
            expires_at.timestamp()
        )

        invite = \
            bot.create_chat_invite_link(
                chat_id=group_id,
                member_limit=1,
                expire_date=expire_timestamp
            )

        return invite.invite_link

    except Exception as e:

        print(
            "Invite error:",
            e
        )

        try:

            invite = \
                bot.create_chat_invite_link(
                    chat_id=group_id,
                    member_limit=1
                )

            return invite.invite_link

        except Exception as e2:

            print(
                "Fallback invite error:",
                e2
            )

            return None


# ============================================================
# AUTO FINISH SESSION
# ============================================================

def auto_finish_session(
    session_id
):

    session = get_active_session(
        session_id
    )

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

    # Remove user from host group
    try:

        bot.ban_chat_member(
            chat_id=group_id,
            user_id=user_id
        )

        try:

            bot.unban_chat_member(
                chat_id=group_id,
                user_id=user_id,
                only_if_banned=True
            )

        except Exception:
            pass

    except Exception as e:

        print(
            "Remove user error:",
            e
        )

    # Finish only once
    if not finish_session(
        session_id
    ):
        return

    # Add host wallet
    add_host_earning(
        host_user_id,
        minutes,
        amount
    )

    # User notification
    try:

        bot.send_message(
            user_id,
            f"""
⏰ *CALL COMPLETED*

👑 Host:
*{host_name}*

⏱ Duration:
*{minutes} Minutes*

💰 Paid:
₹{amount}

💳 Remaining Wallet:
*{get_balance(user_id)} Minutes*

Thank you for using *Vynora Live*.
"""
        )

    except Exception as e:

        print(
            "User completion notification:",
            e
        )

    # Host notification
    try:

        stats = get_host(
            host_user_id
        )

        if stats:

            bot.send_message(
                host_user_id,
                f"""
💰 *CALL EARNING RECEIVED*

👑 Host:
*{host_name}*

⏱ Call:
*{minutes} Minutes*

💵 Customer Payment:
₹{amount}

➖ Platform Charge:
30% = ₹{platform_charge}

💰 *Your Earning: ₹{host_earning}*

━━━━━━━━━━━━━━

💳 Wallet:
*₹{stats["wallet"]}*

⏱ Total Worked:
*{stats["total_minutes"]} Minutes*
"""
            )

    except Exception as e:

        print(
            "Host notification error:",
            e
        )

    # Host group notification
    try:

        bot.send_message(
            group_id,
            f"""
✅ *CALL COMPLETED*

👑 Host:
*{host_name}*

⏱ Duration:
*{minutes} Minutes*

💰 Customer Payment:
₹{amount}

➖ Platform Charge:
₹{platform_charge}

💵 Host Earning:
*₹{host_earning}*

👤 User has been removed automatically.
"""
        )

    except Exception as e:

        print(
            "Host group notification:",
            e
        )

    # Admin notification
    try:

        bot.send_message(
            ADMIN_GROUP_ID,
            f"""
✅ *SESSION COMPLETED*

👤 User ID:
`{user_id}`

👑 Host:
*{host_name}*

🆔 Host ID:
`{host_user_id}`

⏱ Duration:
*{minutes} Minutes*

💰 Customer Paid:
₹{amount}

➖ Platform Charge:
₹{platform_charge}

💰 Host Earning:
₹{host_earning}

🆔 Session ID:
`{session_id}`

📅 Completed:
{now_text()}
"""
        )

    except Exception:
        pass


# ============================================================
# MAIN KEYBOARD
# ============================================================

def main_keyboard():

    kb = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    kb.row(
        "🔥 Book Host Session"
    )

    kb.row(
        "💳 Recharge Minutes",
        "👤 Profile"
    )

    kb.row(
        "🆘 Help & Support"
    )

    return kb


# ============================================================
# HOST KEYBOARD
# ============================================================

def host_keyboard():

    kb = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    kb.row(
        "🟢 GO ONLINE",
        "🔴 GO OFFLINE"
    )

    kb.row(
        "💰 My Earnings",
        "📊 My Stats"
    )

    return kb


# ============================================================
# /START
# ============================================================

@bot.message_handler(
    commands=["start"]
)
def start_handler(message):

    user = message.from_user

    is_new = register_user(
        user
    )

    host = get_host(
        user.id
    )

    if host and int(
        host["approved"]
    ) == 1:

        bot.send_message(
            message.chat.id,
            f"""
👑 *VYNORA LIVE HOST PANEL*

Welcome:

*{host["host_name"]}*

📡 Current Status:
*{host["status"]}*

Use the buttons below.
""",
            reply_markup=host_keyboard()
        )

        return

    if is_new:

        username = (
            f"@{user.username}"
            if user.username
            else "N/A"
        )

        try:

            bot.send_message(
                REGISTERED_USER_GROUP_ID,
                f"""
🆕 *NEW USER REGISTERED*

👤 Name:
{user.first_name or "N/A"}

🔗 Username:
{username}

🆔 User ID:
`{user.id}`

📅 Joining Date & Time:
{now_text()}

💰 Wallet:
0 Minutes
"""
            )

        except Exception as e:

            print(
                "Registration group error:",
                e
            )

    bot.send_message(
        message.chat.id,
        f"""
🔥 *WELCOME TO VYNORA LIVE*

👤 User:
*{user.first_name or "User"}*

💳 Wallet:
*{get_balance(user.id)} Minutes*

Book a private 1-to-1 host session.

Please select an option below.
""",
        reply_markup=main_keyboard()
    )


# ============================================================
# RECHARGE
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.text == "💳 Recharge Minutes"
)
def recharge_handler(message):

    user_id = message.from_user.id

    kb = types.InlineKeyboardMarkup()

    if is_first_offer_available(
        user_id
    ):

        kb.add(
            types.InlineKeyboardButton(
                "🔥 FIRST CALL — 1 MIN ₹20",
                callback_data="plan:1:20:first"
            )
        )

    for minutes, amount in PLANS.items():

        kb.add(
            types.InlineKeyboardButton(
                f"{minutes} MIN — ₹{amount}",
                callback_data=
                f"plan:{minutes}:{amount}"
            )
        )

    bot.send_message(
        message.chat.id,
        """
💳 *RECHARGE MINUTES*

🔥 *FIRST TIME USER*

1 Minute — ₹20

━━━━━━━━━━━━━━

📦 *REGULAR PLANS*

5 Minutes — ₹100
10 Minutes — ₹200
20 Minutes — ₹400
30 Minutes — ₹600
40 Minutes — ₹800

Select your plan below.
""",
        reply_markup=kb
    )


# ============================================================
# PLAN SELECT
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("plan:")
)
def plan_callback(call):

    bot.answer_callback_query(
        call.id
    )

    parts = call.data.split(":")

    minutes = int(parts[1])
    amount = int(parts[2])

    is_first = (
        len(parts) > 3
        and parts[3] == "first"
    )

    if is_first:

        if not is_first_offer_available(
            call.from_user.id
        ):

            bot.send_message(
                call.message.chat.id,
                "❌ First-time offer already used."
            )

            return

    txn_id = (
        "TXN-"
        + datetime.now().strftime(
            "%Y%m%d%H%M%S"
        )
        + "-"
        + uuid.uuid4().hex[:6].upper()
    )

    conn = get_db()

    conn.execute(
        """
        INSERT INTO pending_txns
        (
            txn_id,
            user_id,
            plan_minutes,
            amount,
            utr,
            msg_id,
            status,
            created_at
        )
        VALUES
        (?, ?, ?, ?, '', 0, 'WAITING_PAYMENT', ?)
        """,
        (
            txn_id,
            call.from_user.id,
            minutes,
            amount,
            now_text()
        )
    )

    conn.commit()
    conn.close()

    upi_data = (
        f"upi://pay?"
        f"pa={urllib.parse.quote(UPI_ID)}"
        f"&pn={urllib.parse.quote(PAYEE_NAME)}"
        f"&am={amount}"
        f"&cu=INR"
    )

    qr_url = (
        "https://api.qrserver.com/v1/create-qr-code/"
        "?size=400x400&data="
        + urllib.parse.quote(
            upi_data
        )
    )

    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton(
            "📸 UPLOAD PAYMENT SCREENSHOT",
            callback_data=
            f"upload:{txn_id}"
        )
    )

    bot.send_message(
        call.message.chat.id,
        f"""
💳 *PAYMENT DETAILS*

📦 Plan:
*{minutes} Minutes*

💰 Amount:
*₹{amount}*

🆔 Transaction ID:
`{txn_id}`

🏦 UPI ID:
`{UPI_ID}`

👤 Payee:
*{PAYEE_NAME}*

━━━━━━━━━━━━━━

1. Pay the exact amount.
2. Take payment screenshot.
3. Upload screenshot.
4. Enter UTR number.
5. Admin will verify your payment.

⚠️ Minutes will be added only after admin approval.
""",
        reply_markup=kb
    )

    try:

        bot.send_photo(
            call.message.chat.id,
            qr_url,
            caption=f"""
📲 *SCAN & PAY*

💰 Amount: ₹{amount}

🏦 UPI:
`{UPI_ID}`

🆔 Transaction:
`{txn_id}`
"""
        )

    except Exception as e:

        print(
            "QR error:",
            e
        )


# ============================================================
# UPLOAD BUTTON
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("upload:")
)
def upload_callback(call):

    bot.answer_callback_query(
        call.id
    )

    txn_id = call.data.split(
        ":",
        1
    )[1]

    bot.send_message(
        call.message.chat.id,
        f"""
📸 *UPLOAD PAYMENT SCREENSHOT*

Transaction:

`{txn_id}`

Please send the payment screenshot as a photo.
"""
    )

    bot.register_next_step_handler(
        call.message,
        receive_payment_screenshot,
        txn_id
    )


# ============================================================
# PAYMENT SCREENSHOT
# ============================================================

def receive_payment_screenshot(
    message,
    txn_id
):

    if not message.photo:

        bot.send_message(
            message.chat.id,
            "❌ Please send the screenshot as a photo."
        )

        bot.register_next_step_handler(
            message,
            receive_payment_screenshot,
            txn_id
        )

        return

    screenshot_file_id = \
        message.photo[-1].file_id

    bot.send_message(
        message.chat.id,
        f"""
✅ *SCREENSHOT RECEIVED*

Transaction:
`{txn_id}`

Now send your *UTR / Transaction Number*.
"""
    )

    bot.register_next_step_handler(
        message,
        receive_utr,
        txn_id,
        screenshot_file_id
    )


# ============================================================
# UTR
# ============================================================

def receive_utr(
    message,
    txn_id,
    screenshot_file_id
):

    utr = (
        message.text or ""
    ).strip()

    if len(utr) < 4:

        bot.send_message(
            message.chat.id,
            "❌ Invalid UTR. Please enter the correct UTR."
        )

        bot.register_next_step_handler(
            message,
            receive_utr,
            txn_id,
            screenshot_file_id
        )

        return

    conn = get_db()

    txn = conn.execute(
        """
        SELECT *
        FROM pending_txns
        WHERE txn_id=?
        """,
        (txn_id,)
    ).fetchone()

    if not txn:

        conn.close()

        bot.send_message(
            message.chat.id,
            "❌ Transaction not found."
        )

        return

    # Prevent changing an already processed transaction.
    if txn["status"] in (
        "APPROVED",
        "REJECTED"
    ):

        conn.close()

        bot.send_message(
            message.chat.id,
            "❌ This transaction has already been processed."
        )

        return

    conn.execute(
        """
        UPDATE pending_txns
        SET
            utr=?,
            status='PENDING'
        WHERE txn_id=?
        """,
        (
            utr,
            txn_id
        )
    )

    conn.commit()
    conn.close()

    user = message.from_user

    username = (
        f"@{user.username}"
        if user.username
        else "N/A"
    )

    kb = types.InlineKeyboardMarkup()

    kb.row(

        types.InlineKeyboardButton(
            "✅ APPROVE",
            callback_data=
            f"approve:{txn_id}"
        ),

        types.InlineKeyboardButton(
            "❌ REJECT",
            callback_data=
            f"reject:{txn_id}"
        )
    )

    admin_text = f"""
💳 *NEW PAYMENT VERIFICATION*

👤 Name:
{user.first_name or "N/A"}

🔗 Username:
{username}

🆔 User ID:
`{user.id}`

🆔 Transaction:
`{txn_id}`

📦 Minutes:
*{txn["plan_minutes"]}*

💰 Amount:
*₹{txn["amount"]}*

🔢 UTR:
`{utr}`

📅 Submitted:
{now_text()}

Please verify the payment.
"""

    try:

        sent = bot.send_photo(
            ADMIN_GROUP_ID,
            screenshot_file_id,
            caption=admin_text,
            reply_markup=kb
        )

        conn = get_db()

        conn.execute(
            """
            UPDATE pending_txns
            SET msg_id=?
            WHERE txn_id=?
            """,
            (
                sent.message_id,
                txn_id
            )
        )

        conn.commit()
        conn.close()

    except Exception as e:

        print(
            "Admin payment message error:",
            e
        )

    bot.send_message(
        message.chat.id,
        """
✅ *PAYMENT SUBMITTED*

Your payment is now under verification.

After admin approval, minutes will automatically be added to your wallet.
"""
    )


# ============================================================
# ADMIN APPROVE PAYMENT
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("approve:")
)
def approve_payment(call):

    if call.message.chat.id != \
            ADMIN_GROUP_ID:

        bot.answer_callback_query(
            call.id,
            "Not authorized.",
            show_alert=True
        )

        return

    txn_id = call.data.split(
        ":",
        1
    )[1]

    conn = get_db()

    txn = conn.execute(
        """
        SELECT *
        FROM pending_txns
        WHERE txn_id=?
        """,
        (txn_id,)
    ).fetchone()

    if not txn:

        conn.close()

        bot.answer_callback_query(
            call.id,
            "Transaction not found.",
            show_alert=True
        )

        return

    if txn["status"] == "APPROVED":

        conn.close()

        bot.answer_callback_query(
            call.id,
            "Already approved.",
            show_alert=True
        )

        return

    if txn["status"] != "PENDING":

        conn.close()

        bot.answer_callback_query(
            call.id,
            "Transaction is not pending.",
            show_alert=True
        )

        return

    user_id = int(
        txn["user_id"]
    )

    minutes = int(
        txn["plan_minutes"]
    )

    conn.execute(
        """
        UPDATE pending_txns
        SET
            status='APPROVED',
            approved_at=?
        WHERE txn_id=?
        AND status='PENDING'
        """,
        (
            now_text(),
            txn_id
        )
    )

    conn.commit()
    conn.close()

    add_balance(
        user_id,
        minutes
    )

    if minutes == FIRST_TIME_MINUTES:
        mark_first_offer_used(
            user_id
        )

    try:

        bot.edit_message_reply_markup(
            ADMIN_GROUP_ID,
            call.message.message_id,
            reply_markup=None
        )

    except Exception:
        pass

    try:

        bot.send_message(
            user_id,
            f"""
✅ *PAYMENT APPROVED*

🆔 Transaction:
`{txn_id}`

💰 Paid:
₹{txn["amount"]}

➕ Added:
*{minutes} Minutes*

💳 Wallet:
*{get_balance(user_id)} Minutes*

You can now book an online host.
"""
        )

    except Exception:
        pass

    bot.answer_callback_query(
        call.id,
        "Payment approved."
    )

    try:

        bot.send_message(
            ADMIN_GROUP_ID,
            f"""
✅ *PAYMENT APPROVED*

👤 User ID:
`{user_id}`

🆔 Transaction:
`{txn_id}`

➕ Minutes:
*{minutes}*

💰 Amount:
₹{txn["amount"]}

📅 Approved:
{now_text()}
"""
        )

    except Exception:
        pass


# ============================================================
# ADMIN REJECT PAYMENT
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("reject:")
)
def reject_payment(call):

    if call.message.chat.id != \
            ADMIN_GROUP_ID:

        bot.answer_callback_query(
            call.id,
            "Not authorized.",
            show_alert=True
        )

        return

    txn_id = call.data.split(
        ":",
        1
    )[1]

    conn = get_db()

    txn = conn.execute(
        """
        SELECT *
        FROM pending_txns
        WHERE txn_id=?
        """,
        (txn_id,)
    ).fetchone()

    if not txn:

        conn.close()

        bot.answer_callback_query(
            call.id,
            "Transaction not found.",
            show_alert=True
        )

        return

    if txn["status"] in (
        "APPROVED",
        "REJECTED"
    ):

        conn.close()

        bot.answer_callback_query(
            call.id,
            "Already processed.",
            show_alert=True
        )

        return

    conn.execute(
        """
        UPDATE pending_txns
        SET status='REJECTED'
        WHERE txn_id=?
        """,
        (txn_id,)
    )

    conn.commit()
    conn.close()

    try:

        bot.send_message(
            txn["user_id"],
            f"""
❌ *PAYMENT REJECTED*

Transaction:
`{txn_id}`

Amount:
₹{txn["amount"]}

If you believe this is incorrect, please contact admin.
"""
        )

    except Exception:
        pass

    try:

        bot.edit_message_reply_markup(
            ADMIN_GROUP_ID,
            call.message.message_id,
            reply_markup=None
        )

    except Exception:
        pass

    bot.answer_callback_query(
        call.id,
        "Payment rejected."
    )


# ============================================================
# BOOK HOST
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.text == "🔥 Book Host Session"
)
def book_host(message):

    user_id = message.from_user.id

    balance = get_balance(
        user_id
    )

    if balance <= 0:

        bot.send_message(
            message.chat.id,
            """
❌ *NO MINUTES AVAILABLE*

Please recharge your wallet first.
""",
            reply_markup=main_keyboard()
        )

        return

    hosts = get_online_hosts()

    if not hosts:

        bot.send_message(
            message.chat.id,
            """
😔 *NO HOST ONLINE*

Please try again later.
"""
        )

        return

    kb = types.InlineKeyboardMarkup()

    for host in hosts:

        kb.add(
            types.InlineKeyboardButton(
                f"🟢 {host['host_name']}",
                callback_data=
                f"hsel:{host['user_id']}"
            )
        )

    bot.send_message(
        message.chat.id,
        f"""
👑 *ONLINE HOSTS*

💳 Your Wallet:
*{balance} Minutes*

Select a host below.
""",
        reply_markup=kb
    )


# ============================================================
# HOST SELECT
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("hsel:")
)
def host_select(call):

    bot.answer_callback_query(
        call.id
    )

    host_id = int(
        call.data.split(":")[1]
    )

    host = get_host(
        host_id
    )

    if not host:

        bot.send_message(
            call.message.chat.id,
            "❌ Host not found."
        )

        return

    if host["status"] != "ONLINE":

        bot.send_message(
            call.message.chat.id,
            "❌ Host is currently offline."
        )

        return

    user_id = call.from_user.id

    balance = get_balance(
        user_id
    )

    kb = types.InlineKeyboardMarkup()

    if is_first_offer_available(
        user_id
    ):

        # First-call option is only shown when
        # the user has at least 1 minute available.
        if balance >= FIRST_TIME_MINUTES:

            kb.add(
                types.InlineKeyboardButton(
                    "🔥 FIRST CALL — 1 MIN ₹20",
                    callback_data=
                    f"book:{host_id}:1:20"
                )
            )

    for minutes, amount in PLANS.items():

        if balance >= minutes:

            kb.add(
                types.InlineKeyboardButton(
                    f"{minutes} MIN — ₹{amount}",
                    callback_data=
                    f"book:{host_id}:{minutes}:{amount}"
                )
            )

    if not kb.keyboard:

        bot.send_message(
            call.message.chat.id,
            "❌ Your wallet does not have enough minutes for the available plans."
        )

        return

    bot.send_message(
        call.message.chat.id,
        f"""
👑 *{host["host_name"]}*

🟢 Status:
ONLINE

💳 Your Wallet:
*{balance} Minutes*

Select call duration:
""",
        reply_markup=kb
    )


# ============================================================
# BOOK SESSION
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("book:")
)
def booking_callback(call):

    bot.answer_callback_query(
        call.id
    )

    parts = call.data.split(":")

    if len(parts) != 4:

        bot.send_message(
            call.message.chat.id,
            "❌ Invalid booking request."
        )

        return

    host_id = int(parts[1])
    minutes = int(parts[2])
    amount = int(parts[3])

    user_id = call.from_user.id

    # Validate the selected plan server-side.
    valid_plan = (
        amount == FIRST_TIME_AMOUNT
        and minutes == FIRST_TIME_MINUTES
    )

    if not valid_plan:

        valid_plan = (
            minutes in PLANS
            and PLANS[minutes] == amount
        )

    if not valid_plan:

        bot.send_message(
            call.message.chat.id,
            "❌ Invalid plan."
        )

        return

    host = get_host(
        host_id
    )

    if not host:

        bot.send_message(
            call.message.chat.id,
            "❌ Host not found."
        )

        return

    if host["status"] != "ONLINE":

        bot.send_message(
            call.message.chat.id,
            """
❌ Host has gone offline.

Please select another host.
"""
        )

        return

    user_id = call.from_user.id

    if get_balance(user_id) < minutes:

        bot.send_message(
            call.message.chat.id,
            """
❌ Not enough minutes.

Please recharge.
"""
        )

        return

    # First offer must still be available.
    if (
        minutes == FIRST_TIME_MINUTES
        and amount == FIRST_TIME_AMOUNT
        and not is_first_offer_available(user_id)
    ):

        bot.send_message(
            call.message.chat.id,
            "❌ First-time offer already used."
        )

        return

    if not deduct_balance(
        user_id,
        minutes
    ):

        bot.send_message(
            call.message.chat.id,
            "❌ Booking failed. Please try again."
        )

        return

    if (
        minutes == FIRST_TIME_MINUTES
        and amount == FIRST_TIME_AMOUNT
    ):

        mark_first_offer_used(
            user_id
        )

    session_id, expires_at = \
        create_session(
            user_id,
            host_id,
            host["host_name"],
            host["group_id"],
            minutes,
            amount
        )

    invite_link = \
        create_private_invite(
            host["group_id"],
            expires_at
        )

    if not invite_link:

        add_balance(
            user_id,
            minutes
        )

        conn = get_db()

        conn.execute(
            """
            DELETE FROM sessions
            WHERE id=?
            """,
            (session_id,)
        )

        conn.commit()
        conn.close()

        bot.send_message(
            call.message.chat.id,
            """
❌ Unable to create private group invite.

Your minutes have been refunded.

Please try again later.
"""
        )

        return

    user = get_user(
        user_id
    )

    username = (
        f"@{user['username']}"
        if user and user["username"]
        else "N/A"
    )

    platform_charge, host_earning = \
        calculate_host_earning(
            amount
        )

    # USER
    bot.send_message(
        user_id,
        f"""
✅ *BOOKING CONFIRMED*

👑 Host:
*{host["host_name"]}*

⏱ Duration:
*{minutes} Minutes*

💰 Paid:
₹{amount}

💳 Remaining:
*{get_balance(user_id)} Minutes*

━━━━━━━━━━━━━━

🔗 *PRIVATE GROUP LINK*

{invite_link}

━━━━━━━━━━━━━━

⏰ Session End:
*{expires_at.strftime("%d-%m-%Y %I:%M %p")}*

⚠️ Join the group immediately.

You will automatically be removed when your session time ends.
"""
    )

    # ADMIN
    try:

        bot.send_message(
            ADMIN_GROUP_ID,
            f"""
🔥 *NEW HOST BOOKING*

👤 Name:
{user["name"] if user else "N/A"}

🔗 Username:
{username}

🆔 User ID:
`{user_id}`

👑 Host:
*{host["host_name"]}*

🆔 Host ID:
`{host_id}`

👥 Group ID:
`{host["group_id"]}`

⏱ Duration:
*{minutes} Minutes*

💰 Customer Paid:
₹{amount}

➖ Platform Charge:
₹{platform_charge}

💰 Host Earning:
₹{host_earning}

💳 User Remaining:
{get_balance(user_id)} Minutes

📅 Start:
{now_text()}

⏰ End:
{expires_at.strftime("%d-%m-%Y %I:%M %p")}

🆔 Session:
`{session_id}`
"""
        )

    except Exception as e:

        print(
            "Admin booking error:",
            e
        )

    # HOST GROUP
    try:

        bot.send_message(
            host["group_id"],
            f"""
🔥 *NEW BOOKING*

👑 Host:
*{host["host_name"]}*

👤 User:
{user["name"] if user else "N/A"}

🔗 Username:
{username}

🆔 User ID:
`{user_id}`

⏱ Duration:
*{minutes} Minutes*

💰 Customer Payment:
₹{amount}

➖ Platform Charge:
₹{platform_charge}

💰 *Host Earning: ₹{host_earning}*

━━━━━━━━━━━━━━

📅 Start:
{now_text()}

⏰ End:
{expires_at.strftime("%d-%m-%Y %I:%M %p")}

🆔 Session:
`{session_id}`

⚠️ User will automatically be removed after the session.
"""
        )

    except Exception as e:

        print(
            "Host group error:",
            e
        )

    timer = threading.Timer(
        minutes * 60,
        auto_finish_session,
        args=(session_id,)
    )

    timer.daemon = True
    timer.start()


# ============================================================
# USER PROFILE
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.text == "👤 Profile"
)
def profile_handler(message):

    user_id = message.from_user.id

    user = get_user(
        user_id
    )

    if not user:

        register_user(
            message.from_user
        )

        user = get_user(
            user_id
        )

    username = (
        f"@{user['username']}"
        if user["username"]
        else "N/A"
    )

    bot.send_message(
        message.chat.id,
        f"""
👤 *MY PROFILE*

━━━━━━━━━━━━━━

👤 Name:
*{user["name"]}*

🔗 Username:
{username}

🆔 User ID:
`{user_id}`

📅 Registration:
{user["registered_at"]}

💳 Wallet:
*{user["balance"]} Minutes*

━━━━━━━━━━━━━━

🔥 *CALL PLANS*

First Call:
1 Minute — ₹20

Regular:

5 Minutes — ₹100
10 Minutes — ₹200
20 Minutes — ₹400
30 Minutes — ₹600
40 Minutes — ₹800

Use *🔥 Book Host Session* to book an online host.
"""
    )


# ============================================================
# HOST ONLINE
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.text == "🟢 GO ONLINE"
)
def host_online(message):

    host = get_host(
        message.from_user.id
    )

    if not host:

        bot.send_message(
            message.chat.id,
            "❌ You are not an approved host."
        )

        return

    set_host_status(
        message.from_user.id,
        "ONLINE"
    )

    bot.send_message(
        message.chat.id,
        f"""
🟢 *YOU ARE ONLINE*

👑 Host:
*{host["host_name"]}*

Users can now see your profile and book you.
""",
        reply_markup=host_keyboard()
    )


# ============================================================
# HOST OFFLINE
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.text == "🔴 GO OFFLINE"
)
def host_offline(message):

    host = get_host(
        message.from_user.id
    )

    if not host:

        bot.send_message(
            message.chat.id,
            "❌ You are not an approved host."
        )

        return

    set_host_status(
        message.from_user.id,
        "OFFLINE"
    )

    bot.send_message(
        message.chat.id,
        f"""
🔴 *YOU ARE OFFLINE*

👑 Host:
*{host["host_name"]}*

New users cannot book you while you are offline.
""",
        reply_markup=host_keyboard()
    )


# ============================================================
# HOST EARNINGS
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.text == "💰 My Earnings"
)
def host_earnings(message):

    host = get_host(
        message.from_user.id
    )

    if not host:

        bot.send_message(
            message.chat.id,
            "❌ Host account not found."
        )

        return

    bot.send_message(
        message.chat.id,
        f"""
💰 *MY HOST WALLET*

👑 Host:
*{host["host_name"]}*

⏱ Total Worked:
*{host["total_minutes"]} Minutes*

💵 Customer Gross:
₹{host["total_gross"]}

➖ Platform Charge:
₹{host["total_platform_charge"]}

💰 *Your Wallet:*
*₹{host["wallet"]}*

━━━━━━━━━━━━━━

Platform charge:
*30%*

Host share:
*70%*
"""
    )


# ============================================================
# HOST STATS
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.text == "📊 My Stats"
)
def host_stats(message):

    host = get_host(
        message.from_user.id
    )

    if not host:

        bot.send_message(
            message.chat.id,
            "❌ Host account not found."
        )

        return

    bot.send_message(
        message.chat.id,
        f"""
📊 *HOST STATISTICS*

👑 Host:
*{host["host_name"]}*

📡 Status:
*{host["status"]}*

⏱ Total Minutes:
*{host["total_minutes"]}*

💵 Gross Sales:
₹{host["total_gross"]}

➖ Platform Charge:
₹{host["total_platform_charge"]}

💰 Net Wallet:
*₹{host["wallet"]}*
"""
    )


# ============================================================
# ADMIN ADD HOST
# ============================================================

@bot.message_handler(
    commands=["addhost"]
)
def admin_add_host(message):

    if message.chat.id != \
            ADMIN_GROUP_ID:

        return

    parts = message.text.split()

    if len(parts) < 4:

        bot.reply_to(
            message,
            """
❌ *FORMAT*

`/addhost HOST_ID HOST_NAME GROUP_ID`

Example:

`/addhost 123456789 Priya -1004312344325`
"""
        )

        return

    try:

        host_user_id = int(
            parts[1]
        )

        group_id = int(
            parts[-1]
        )

        host_name = " ".join(
            parts[2:-1]
        )

        if group_id not in \
                HOST_GROUPS.values():

            bot.reply_to(
                message,
                "❌ This group ID is not registered."
            )

            return

        add_host(
            host_user_id,
            host_name,
            group_id
        )

        bot.reply_to(
            message,
            f"""
✅ *HOST ADDED & APPROVED*

👑 Host:
*{host_name}*

🆔 Host ID:
`{host_user_id}`

👥 Group:
`{group_id}`

🔴 Initial Status:
*OFFLINE*

Host should open the bot and press:

🟢 GO ONLINE
"""
        )

        try:

            bot.send_message(
                host_user_id,
                f"""
🎉 *HOST ACCOUNT APPROVED*

👑 Host:
*{host_name}*

Your host account has been approved.

Open the bot and send:

`/start`

Then press 🟢 *GO ONLINE*.
"""
            )

        except Exception as e:

            print(
                "Host DM error:",
                e
            )

    except Exception as e:

        bot.reply_to(
            message,
            f"❌ Error: {e}"
        )


# ============================================================
# ADMIN REMOVE HOST
# ============================================================

@bot.message_handler(
    commands=["removehost"]
)
def admin_remove_host(message):

    if message.chat.id != \
            ADMIN_GROUP_ID:

        return

    parts = message.text.split()

    if len(parts) != 2:

        bot.reply_to(
            message,
            "`/removehost HOST_ID`"
        )

        return

    try:

        host_id = int(
            parts[1]
        )

        host = get_host(
            host_id
        )

        if not host:

            bot.reply_to(
                message,
                "❌ Host not found."
            )

            return

        remove_host(
            host_id
        )

        bot.reply_to(
            message,
            f"""
✅ *HOST REMOVED*

👑 {host["host_name"]}

🆔 `{host_id}`
"""
        )

    except Exception as e:

        bot.reply_to(
            message,
            f"❌ Error: {e}"
        )


# ============================================================
# ADMIN HOST LIST
# ============================================================

@bot.message_handler(
    commands=["hosts"]
)
def admin_hosts(message):

    if message.chat.id != \
            ADMIN_GROUP_ID:

        return

    hosts = get_all_hosts()

    if not hosts:

        bot.reply_to(
            message,
            "No hosts added yet."
        )

        return

    text = "👑 *HOST MANAGEMENT*\n\n"

    for host in hosts:

        text += (
            f"👑 *{host['host_name']}*\n"
            f"🆔 `{host['user_id']}`\n"
            f"👥 `{host['group_id']}`\n"
            f"📡 {host['status']}\n"
            f"⏱ {host['total_minutes']} min\n"
            f"💰 ₹{host['wallet']}\n"
            f"──────────────\n"
        )

    bot.reply_to(
        message,
        text
    )


# ============================================================
# ADMIN ADD MINUTES
# ============================================================

@bot.message_handler(
    commands=["addmins", "givemins"]
)
def admin_add_minutes(message):

    if message.chat.id != \
            ADMIN_GROUP_ID:

        return

    parts = message.text.split()

    if len(parts) != 3:

        bot.reply_to(
            message,
            "`/addmins USER_ID MINUTES`"
        )

        return

    try:

        user_id = int(
            parts[1]
        )

        mins = int(
            parts[2]
        )

        if mins <= 0:

            bot.reply_to(
                message,
                "❌ Minutes must be greater than 0."
            )

            return

        if not get_user(
            user_id
        ):

            bot.reply_to(
                message,
                "❌ User not found."
            )

            return

        add_balance(
            user_id,
            mins
        )

        bot.reply_to(
            message,
            f"""
✅ *MINUTES ADDED*

👤 User:
`{user_id}`

➕ Added:
*{mins} Minutes*

💳 Balance:
*{get_balance(user_id)} Minutes*
"""
        )

        try:

            bot.send_message(
                user_id,
                f"""
🎁 *ADMIN CREDIT*

➕ Added:
*{mins} Minutes*

💳 Wallet:
*{get_balance(user_id)} Minutes*
"""
            )

        except Exception:
            pass

    except Exception as e:

        bot.reply_to(
            message,
            f"❌ {e}"
        )


# ============================================================
# ADMIN DEDUCT MINUTES
# ============================================================

@bot.message_handler(
    commands=["deductmins", "removemins"]
)
def admin_deduct_minutes(message):

    if message.chat.id != \
            ADMIN_GROUP_ID:

        return

    parts = message.text.split()

    if len(parts) != 3:

        bot.reply_to(
            message,
            "`/deductmins USER_ID MINUTES`"
        )

        return

    try:

        user_id = int(
            parts[1]
        )

        mins = int(
            parts[2]
        )

        if mins <= 0:

            bot.reply_to(
                message,
                "❌ Minutes must be greater than 0."
            )

            return

        if not deduct_balance(
            user_id,
            mins
        ):

            bot.reply_to(
                message,
                "❌ Insufficient balance."
            )

            return

        bot.reply_to(
            message,
            f"""
✅ *MINUTES DEDUCTED*

👤 User:
`{user_id}`

➖ Deducted:
*{mins} Minutes*

💳 Balance:
*{get_balance(user_id)} Minutes*
"""
        )

    except Exception as e:

        bot.reply_to(
            message,
            f"❌ {e}"
        )


# ============================================================
# ADMIN USER LOOKUP
# ============================================================

@bot.message_handler(
    commands=["user"]
)
def admin_user_lookup(message):

    if message.chat.id != \
            ADMIN_GROUP_ID:

        return

    parts = message.text.split()

    if len(parts) != 2:

        bot.reply_to(
            message,
            "`/user USER_ID`"
        )

        return

    try:

        user_id = int(
            parts[1]
        )

        user = get_user(
            user_id
        )

        if not user:

            bot.reply_to(
                message,
                "❌ User not found."
            )

            return

        bot.reply_to(
            message,
            f"""
👤 *USER DETAILS*

Name:
*{user["name"]}*

Username:
@{user["username"] or "N/A"}

User ID:
`{user["user_id"]}`

Registered:
{user["registered_at"]}

Last Seen:
{user["last_seen"]}

Wallet:
*{user["balance"]} Minutes*
"""
        )

    except Exception as e:

        bot.reply_to(
            message,
            f"❌ {e}"
        )


# ============================================================
# BROADCAST
# ============================================================

@bot.message_handler(
    commands=["broadcast"]
)
def broadcast_handler(message):

    if message.chat.id != \
            ADMIN_GROUP_ID:

        return

    text = message.text[






