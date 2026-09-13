import os
import time
import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient

# Agora Token Generator Import (with fallback)
try:
    from agora_token_builder import RtcTokenBuilder
except ImportError:
    RtcTokenBuilder = None

# Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "7001825467"))
GROUP_1_ID = os.getenv("GROUP_1_ID")  # Command Center (Approvals & Logs)
GROUP_2_ID = os.getenv("GROUP_2_ID")  # User Registration Logs
GROUP_3_ID = os.getenv("GROUP_3_ID")  # Audit & Financial Backup Logs
AGORA_APP_ID = os.getenv("AGORA_APP_ID", "demo_agora_app_id")
AGORA_APP_CERTIFICATE = os.getenv("AGORA_APP_CERTIFICATE", "demo_agora_cert")
UPI_ID = os.getenv("UPI_ID", "vynoralive@slc")
UPI_NAME = os.getenv("UPI_NAME", "Rajnish Kumar")

# MongoDB Connections
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["vynora_live_db"]
users_col = db["users"]
hosts_col = db["hosts"]
bookings_col = db["bookings"]
transactions_col = db["transactions"]
gifts_col = db["gifts"]

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Pydantic Request Models ---
class RechargeRequest(BaseModel):
    user_id: int
    amount_inr: float
    utr_number: str

class BookingRequest(BaseModel):
    user_id: int
    host_id: str
    token_amount: int

class GiftRequest(BaseModel):
    user_id: int
    host_id: str
    gift_type: str  # 'rose', 'diamond', 'crown'
    token_price: int

class AgoraTokenRequest(BaseModel):
    channel_name: str
    user_id: int

# --- 1. TELEGRAM BOT HANDLERS & LOGGING ---
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    user = message.from_user
    user_id = user.id
    username = f"@{user.username}" if user.username else "No Username"
    first_name = user.first_name or "User"

    existing_user = await users_col.find_one({"user_id": user_id})
    if not existing_user:
        new_user = {
            "user_id": user_id,
            "first_name": first_name,
            "username": username,
            "tokens": 0,
            "created_at": datetime.utcnow()
        }
        await users_col.insert_one(new_user)

        # Log to Group 2 (Registration Group)
        if GROUP_2_ID:
            log_text = (
                f"👤 **New User Registered!**\n\n"
                f"🔹 **Name:** {first_name}\n"
                f"🔹 **Username:** {username}\n"
                f"🆔 **User ID:** `{user_id}`\n"
                f"⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            try:
                await bot.send_message(chat_id=GROUP_2_ID, text=log_text, parse_mode="Markdown")
            except Exception as e:
                print(f"Group 2 Log Error: {e}")

    markup = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🚀 Launch Vynora Live 1v1", web_app=types.WebAppInfo(url=WEB_APP_URL))
        ]]
    )
    await message.answer(
        f"👋 **Vynora Live 1v1** me aapka swagat hai!\n\nNeeche button par click karke Mini App kholne ke liye launch karein.",
        reply_markup=markup,
        parse_mode="Markdown"
    )

# --- 2. ADMIN APPROVAL CALLBACK HANDLER (Group 1) ---
@dp.callback_query(F.data.startswith("approve_tx_"))
async def approve_payment_callback(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        await callback.answer("❌ Keval Super Admin (7001825467) ye action le sakte hain!", show_alert=True)
        return

    tx_id = callback.data.replace("approve_tx_", "")
    tx = await transactions_col.find_one({"_id": tx_id, "status": "pending"})
    
    if not tx:
        await callback.answer("Transaction missing ya pehle se processed hai!", show_alert=True)
        return

    user_id = tx["user_id"]
    amount = tx["amount_inr"]
    tokens_to_add = int(amount * 1)  # 1 INR = 1 Vynora Token (Customizable)

    # Credit Tokens to User
    await users_col.update_one({"user_id": user_id}, {"$inc": {"tokens": tokens_to_add}}, upsert=True)
    await transactions_col.update_one({"_id": tx_id}, {"$set": {"status": "approved", "approved_at": datetime.utcnow()}})

    # Notify User via Bot
    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"✅ **Payment Approved!**\n\nAapke wallet me `{tokens_to_add}` Vynora Tokens add kar diye gaye hain. Ab aap Live Chat & Calls enjoy kar sakte hain! 🚀",
            parse_mode="Markdown"
        )
    except:
        pass

    # Log to Group 3 (Audit Ledger)
    if GROUP_3_ID:
        audit_text = (
            f"🧾 **FINANCIAL AUDIT RECORD**\n\n"
            f"✅ **Status:** Approved\n"
            f"👤 **User ID:** `{user_id}`\n"
            f"💰 **Amount:** ₹{amount}\n"
            f"🪙 **Tokens Credited:** {tokens_to_add}\n"
            f"📌 **UTR:** `{tx['utr_number']}`\n"
            f"👨‍💼 **Approved By Admin:** `{SUPER_ADMIN_ID}`\n"
            f"⏰ **Timestamp:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        try:
            await bot.send_message(chat_id=GROUP_3_ID, text=audit_text, parse_mode="Markdown")
        except Exception as e:
            print(f"Group 3 Audit Log Error: {e}")

    await callback.message.edit_text(f"{callback.message.text}\n\n✅ **APPROVED BY ADMIN**")
    await callback.answer("Payment Approved Successfully!")

@dp.callback_query(F.data.startswith("reject_tx_"))
async def reject_payment_callback(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        await callback.answer("❌ Keval Super Admin hi reject kar sakte hain!", show_alert=True)
        return

    tx_id = callback.data.replace("reject_tx_", "")
    await transactions_col.update_one({"_id": tx_id}, {"$set": {"status": "rejected"}})
    
    await callback.message.edit_text(f"{callback.message.text}\n\n❌ **REJECTED BY ADMIN**")
    await callback.answer("Payment Rejected")

# --- 3. FASTAPI BACKEND API ENDPOINTS ---

@app.get("/api/user/{user_id}")
async def get_user_data(user_id: int):
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        return {"user_id": user_id, "tokens": 0, "first_name": "Guest"}
    return {
        "user_id": user["user_id"],
        "first_name": user.get("first_name", "User"),
        "tokens": user.get("tokens", 0)
    }

@app.post("/api/recharge")
async def submit_recharge(req: RechargeRequest):
    tx_id = f"TXN_{int(time.time())}_{req.user_id}"
    tx_doc = {
        "_id": tx_id,
        "user_id": req.user_id,
        "amount_inr": req.amount_inr,
        "utr_number": req.utr_number,
        "status": "pending",
        "created_at": datetime.utcnow()
    }
    await transactions_col.insert_one(tx_doc)

    # Send Approval Request Card to Group 1 (Command Center)
    if GROUP_1_ID:
        card_text = (
            f"💳 **NEW RECHARGE REQUEST**\n\n"
            f"👤 **User ID:** `{req.user_id}`\n"
            f"💵 **Amount:** ₹{req.amount_inr}\n"
            f"📌 **UTR / Ref:** `{req.utr_number}`\n"
            f"🏦 **UPI Receiver:** `{UPI_ID}` ({UPI_NAME})\n"
            f"⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_tx_{tx_id}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_tx_{tx_id}")
            ]]
        )
        try:
            await bot.send_message(chat_id=GROUP_1_ID, text=card_text, reply_markup=markup, parse_mode="Markdown")
        except Exception as e:
            print(f"Group 1 Card Send Error: {e}")

    return {"status": "submitted", "message": "UTR Super Admin ko verification ke liye bhej diya gaya hai."}

@app.post("/api/send-gift")
async def send_gift(req: GiftRequest):
    user = await users_col.find_one({"user_id": req.user_id})
    if not user or user.get("tokens", 0) < req.token_price:
        raise HTTPException(status_code=400, detail="Insufficient Tokens! Recharge karein.")

    # Deduct Tokens from User
    await users_col.update_one({"user_id": req.user_id}, {"$inc": {"tokens": -req.token_price}})

    # 50-50 Split Engine
    platform_commission = req.token_price * 0.50
    host_earning = req.token_price * 0.50

    # Credit Host Wallet
    await hosts_col.update_one(
        {"host_id": req.host_id},
        {"$inc": {"earnings_tokens": host_earning}},
        upsert=True
    )

    # Log Gift Audit
    gift_log = {
        "user_id": req.user_id,
        "host_id": req.host_id,
        "gift_type": req.gift_type,
        "total_tokens": req.token_price,
        "platform_commission": platform_commission,
        "host_earning": host_earning,
        "created_at": datetime.utcnow()
    }
    await gifts_col.insert_one(gift_log)

    return {
        "status": "success",
        "message": f"{req.gift_type.capitalize()} 🎁 sent successfully!",
        "remaining_tokens": user.get("tokens", 0) - req.token_price
    }

@app.post("/api/get-agora-token")
async def get_agora_token(req: AgoraTokenRequest):
    if not RtcTokenBuilder:
        return {"token": "mock_agora_token_for_testing", "channel": req.channel_name}
    
    expiration_time_in_seconds = 3600
    current_timestamp = int(time.time())
    privilege_expired_ts = current_timestamp + expiration_time_in_seconds

    try:
        token = RtcTokenBuilder.buildTokenWithUid(
            AGORA_APP_ID,
            AGORA_APP_CERTIFICATE,
            req.channel_name,
            req.user_id,
            1, # Role_Publisher
            privilege_expired_ts
        )
        return {"token": token, "channel": req.channel_name, "app_id": AGORA_APP_ID}
    except Exception as e:
        return {"token": "sample_token", "error": str(e)}

# --- 4. 5-MINUTE AUTO-REFUND ESCROW BACKGROUND TASK ---
async def check_pending_bookings():
    while True:
        try:
            five_mins_ago = datetime.utcnow() - timedelta(minutes=5)
            expired_bookings = bookings_col.find({
                "status": "pending",
                "created_at": {"$lte": five_mins_ago}
            })

            async for booking in expired_bookings:
                # Auto Refund Tokens
                await users_col.update_one(
                    {"user_id": booking["user_id"]},
                    {"$inc": {"tokens": booking["token_amount"]}}
                )
                await bookings_col.update_one(
                    {"_id": booking["_id"]},
                    {"$set": {"status": "auto_refunded", "refunded_at": datetime.utcnow()}}
                )
                try:
                    await bot.send_message(
                        chat_id=booking["user_id"],
                        text=f"🔄 Host ne 5 minute me respond nahi kiya. `{booking['token_amount']}` Vynora Tokens 100% refund ho gaye hain."
                    )
                except:
                    pass
        except Exception as e:
            print(f"Escrow Refund Loop Error: {e}")
        
        await asyncio.sleep(30)

# --- 5. WEBHOOK & ROUTING ---
@app.post("/webhook")
async def webhook(request: Request):
    update = types.Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"status": "ok"}

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.on_event("startup")
async def on_startup():
    if WEB_APP_URL:
        webhook_url = f"{WEB_APP_URL.rstrip('/')}/webhook"
        await bot.set_webhook(webhook_url)
    asyncio.create_task(check_pending_bookings())

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
