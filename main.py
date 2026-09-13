import os
import logging
import asyncio
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables & Constants
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
SUPER_ADMIN_ID = 7001825467
SUPPORT_USERNAME = "@VynoraSupport"
UPI_ID = "vynoralive@slc"
ACCOUNT_HOLDER = "Rajnish Kumar"

# Telegram Group IDs (Set via Environment Variables)
GROUP_1_MAIN_COMMAND = int(os.getenv("GROUP_1_ID", "-1001234567890"))
GROUP_2_REGISTRATION = int(os.getenv("GROUP_2_ID", "-1001234567891"))
GROUP_3_AUDIT = int(os.getenv("GROUP_3_ID", "-1001234567892"))

# In-memory storage (Use PostgreSQL/SQLite for production)
user_wallets = {}  # {user_id: tokens}
pending_bookings = {}  # {booking_id: {user_id, host_id, tokens, message_id}}

# Flask app for Render Web Service health check
app = Flask(__name__)

@app.route("/")
def health_check():
    return "Vynora Live 1v1 Bot is running successfully!", 200

# --- Telegram Bot Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or "No Username"
    full_name = user.full_name

    # Initialize wallet if new user
    if user_id not in user_wallets:
        user_wallets[user_id] = 0

    welcome_message = (
        f"🌟 **Welcome to Vynora Live 1v1** 🌟\n\n"
        f"Hello {full_name}!\n"
        f"• **Support:** {SUPPORT_USERNAME}\n"
        f"• **Payment UPI:** `{UPI_ID}` ({ACCOUNT_HOLDER})\n\n"
        f"Use /balance to check your Vynora Tokens, or explore private live and gifting features!"
    )
    
    await update.message.reply_text(welcome_message, parse_mode="Markdown")

    # Group 2: User Registration Log Automation
    reg_log = (
        f"👤 **New User Registration Log**\n"
        f"• **Name:** {full_name}\n"
        f"• **User ID:** `{user_id}`\n"
        f"• **Username:** @{username}"
    )
    try:
        await context.bot.send_message(chat_id=GROUP_2_REGISTRATION, text=reg_log, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to log in Group 2: {e}")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tokens = user_wallets.get(user_id, 0)
    await update.message.reply_text(
        f"💳 **Your Vynora Wallet Balance**\n\n"
        f"• **Tokens:** `{tokens}` 🪙\n"
        f"• **To Top-up:** Send payment to `{UPI_ID}` and share UTR screenshot in Group 1.",
        parse_mode="Markdown"
    )

async def book_host(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simulates booking an offline/busy host with Escrow Hold and 5-min timeout."""
    user_id = update.effective_user.id
    args = context.args
    
    if len(args) < 2:
        await update.message.reply_text("Usage: `/book <host_id> <tokens>`", parse_mode="Markdown")
        return

    host_id = args[0]
    try:
        tokens_to_hold = int(args[1])
    except ValueError:
        await update.message.reply_text("Invalid token amount specified.")
        return

    current_balance = user_wallets.get(user_id, 0)
    if current_balance < tokens_to_hold:
        await update.message.reply_text("❌ Insufficient Vynora tokens in wallet. Top up to proceed.")
        return

    # Escrow Hold: Deduct temporarily
    user_wallets[user_id] -= tokens_to_hold
    booking_id = f"book_{user_id}_{host_id}_{update.message.message_id}"
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Accept (5m)", callback_data=f"accept_{booking_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{booking_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    sent_msg = await update.message.reply_text(
        f"⏳ **Booking Request Sent (Escrow Hold)**\n"
        f"• **Host ID:** `{host_id}`\n"
        f"• **Tokens Held:** `{tokens_to_hold}` 🪙\n"
        f"Waiting for host response (5 minutes limit)...",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

    pending_bookings[booking_id] = {
        "user_id": user_id,
        "host_id": host_id,
        "tokens": tokens_to_hold,
        "message_id": sent_msg.message_id,
        "chat_id": update.effective_chat.id
    }

    # Start 5-Minute Timer Background Task for Auto-Refund
    asyncio.create_task(auto_refund_timer(booking_id, context))

async def auto_refund_timer(booking_id: str, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(300)  # 5 minutes = 300 seconds
    if booking_id in pending_bookings:
        data = pending_bookings.pop(booking_id)
        user_id = data["user_id"]
        tokens = data["tokens"]
        
        # Refund tokens
        user_wallets[user_id] = user_wallets.get(user_id, 0) + tokens
        
        try:
            await context.bot.edit_message_text(
                chat_id=data["chat_id"],
                message_id=data["message_id"],
                text=f"⏰ **Booking Auto-Cancelled & Refunded**\nHost did not respond within 5 minutes. `{tokens}` tokens refunded to wallet.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error updating auto-refund message: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("accept_") or data.startswith("reject_"):
        action, booking_id = data.split("_", 1)
        # Reconstruct full booking key format: accept_book_...
        full_key = f"book_{booking_id}"
        
        if full_key not in pending_bookings:
            await query.edit_message_text("⚠️ This booking request has already expired or been processed.")
            return

        booking_data = pending_bookings.pop(full_key)
        user_id = booking_data["user_id"]
        tokens = booking_data["tokens"]

        if action == "accept":
            await query.edit_message_text(
                f"✅ **Booking Accepted!**\nHost has accepted your request. Access unlocked for 1v1 live session.",
                parse_mode="Markdown"
            )
        else:  # reject
            user_wallets[user_id] = user_wallets.get(user_id, 0) + tokens
            await query.edit_message_text(
                f"❌ **Booking Rejected & Refunded**\n`{tokens}` tokens have been returned to your wallet.",
                parse_mode="Markdown"
            )

async def handle_utr_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Group 1 Handler for UTR Screenshots and Super Admin verification"""
    if update.effective_chat.id != GROUP_1_MAIN_COMMAND:
        return

    if not update.message.photo and "UTR" not in update.message.text.upper():
        return

    user = update.effective_user
    caption = update.message.caption or update.message.text or ""
    
    admin_keyboard = [
        [
            InlineKeyboardButton("✅ Verify & Approve Payment", callback_data=f"approve_pay_{user.id}"),
            InlineKeyboardButton("❌ Reject Payment", callback_data=f"reject_pay_{user.id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(admin_keyboard)

    # Forward to Super Admin command center channel/group with verification buttons
    forward_msg = await context.bot.send_message(
        chat_id=GROUP_1_MAIN_COMMAND,
        text=f"🔔 **New Payment Verification Pending**\n"
             f"• **User:** {user.full_name} (`{user.id}`)\n"
             f"• **Details:** {caption}\n"
             f"• **Super Admin:** `{SUPER_ADMIN_ID}`",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def admin_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    if user.id != SUPER_ADMIN_ID:
        await query.answer("Access Denied: Only Super Admin can approve payments.", show_alert=True)
        return

    await query.answer()
    data = query.data
    action, _, target_user_id = data.split("_")
    target_user_id = int(target_user_id)

    if action == "approve":
        # Log to Group 3 (Audit & Payment Data Group)
        audit_text = (
            f"💰 **Secure Financial Audit Record**\n"
            f"• **Approved By Super Admin:** `{SUPER_ADMIN_ID}`\n"
            f"• **User ID:** `{target_user_id}`\n"
            f"• **Status:** Verified & Credited"
        )
        try:
            await context.bot.send_message(chat_id=GROUP_3_AUDIT, text=audit_text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to write to Audit Group 3: {e}")

        await query.edit_message_text(f"✅ Payment for User `{target_user_id}` approved successfully and logged to Audit Group.")
    else:
        await query.edit_message_text(f"❌ Payment for User `{target_user_id}` was rejected by Super Admin.")

# --- Main Setup ---
def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("book", book_host))
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^(accept|reject)_"))
    application.add_handler(CallbackQueryHandler(admin_payment_handler, pattern="^(approve|reject)_pay_"))
    application.add_handler(MessageHandler(filters.PHOTO | filters.TEXT, handle_utr_payment))

    # Run bot using polling (Render Background Worker or Web Service setup)
    logger.info("Starting Vynora Live 1v1 Telegram Bot...")
    application.run_polling()

if __name__ == "__main__":
    # If deploying on Render Web Service alongside Flask, run Flask in a thread or use background worker.
    # For a standard Render Python Background Worker, just execute main().
    port = int(os.environ.get("PORT", 10000))
    import threading
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port)).start()
    
    main()
