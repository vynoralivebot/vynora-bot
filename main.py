import os
import time
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient

# Environment Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEB_APP_URL = os.getenv("WEB_APP_URL", "")
MONGO_URI = os.getenv("MONGO_URI", "")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "7001825467"))
GROUP_1_ID = os.getenv("GROUP_1_ID", "")
GROUP_2_ID = os.getenv("GROUP_2_ID", "")
GROUP_3_ID = os.getenv("GROUP_3_ID", "")
AGORA_APP_ID = os.getenv("AGORA_APP_ID", "demo_app_id")
AGORA_APP_CERTIFICATE = os.getenv("AGORA_APP_CERTIFICATE", "demo_cert")

# MongoDB Client Setup with Increased 10s Timeout for Cloud Handshake
mongo_client = AsyncIOMotorClient(
    MONGO_URI,
    tls=True,
    tlsAllowInvalidCertificates=True,
    serverSelectionTimeoutMS=10000,
    connectTimeoutMS=10000
)
db = mongo_client["vynora_live_db"]
users_col = db["users"]
hosts_col = db["hosts"]
transactions_col = db["transactions"]
gifts_col = db["gifts"]

app = FastAPI()

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Request Schemas
class RechargeRequest(BaseModel):
    user_id: int
    amount_inr: float
    utr_number: str

class GiftRequest(BaseModel):
    user_id: int
    host_id: str
    gift_type: str
    token_price: int

class AgoraTokenRequest(BaseModel):
    channel_name: str
    user_id: int

# --- TELEGRAM BOT HANDLERS ---

@dp.message(F.text == "/id")
async def get_group_id(message: types.Message):
    await message.reply(f"📌 **Chat ID:** `{message.chat.id}`", parse_mode="Markdown")

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    user = message.from_user
    user_id = user.id
    username = f"@{user.username}" if user.username else "No Username"
    first_name = user.first_name or "User"

    try:
        await asyncio.wait_for(
            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"first_name": first_name, "username": username}, "$setOnInsert": {"tokens": 0, "created_at": datetime.utcnow()}},
                upsert=True
            ),
            timeout=8.0
        )
    except Exception as db_err:
        print(f"DB Start Log Warning: {db_err}")

    if GROUP_2_ID:
        try:
            gid2 = int(GROUP_2_ID) if str(GROUP_2_ID).replace("-", "").isdigit() else GROUP_2_ID
            log_text = f"👤 **New User Registered!**\n\n🔹 **Name:** {first_name}\n🔹 **Username:** {username}\n🆔 **ID:** `{user_id}`"
            await bot.send_message(chat_id=gid2, text=log_text, parse_mode="Markdown")
        except Exception as err:
            print(f"Group 2 Log Error: {err}")

    markup = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🚀 Launch Vynora Live 1v1", web_app=types.WebAppInfo(url=WEB_APP_URL))
        ]]
    )
    await message.answer(f"👋 **Vynora Live 1v1** me aapka swagat hai!", reply_markup=markup, parse_mode="Markdown")

# --- ADMIN APPROVAL HANDLERS ---

@dp.callback_query(F.data.startswith("approve_tx_"))
async def approve_payment_callback(callback: types.CallbackQuery):
    clicker_id = callback.from_user.id
    
    if clicker_id != SUPER_ADMIN_ID:
        await callback.answer(f"❌ Keval Super Admin (ID: {SUPER_ADMIN_ID}) approve kar sakte hain!", show_alert=True)
        return

    tx_id = callback.data.replace("approve_tx_", "")
    
    try:
        tx = await asyncio.wait_for(transactions_col.find_one({"_id": tx_id}), timeout=8.0)
    except Exception:
        tx = None

    if not tx:
        await callback.answer("❌ Transaction record database me nahi mila!", show_alert=True)
        return

    if tx.get("status") == "approved":
        await callback.answer("⚠️ Transaction pehle hi approve ho gaya hai!", show_alert=True)
        return

    user_id = tx["user_id"]
    amount = tx["amount_inr"]
    tokens_to_add = int(amount * 1)

    try:
        await users_col.update_one({"user_id": user_id}, {"$inc": {"tokens": tokens_to_add}}, upsert=True)
        await transactions_col.update_one({"_id": tx_id}, {"$set": {"status": "approved", "approved_at": datetime.utcnow()}})
    except Exception as e:
        print(f"Approval DB Error: {e}")

    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"✅ **Payment Approved!**\n\nAapke wallet me `{tokens_to_add}` Tokens add ho gaye hain! 🚀",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    if GROUP_3_ID:
        try:
            gid3 = int(GROUP_3_ID) if str(GROUP_3_ID).replace("-", "").isdigit() else GROUP_3_ID
            audit_text = (
                f"🧾 **FINANCIAL AUDIT RECORD**\n\n"
                f"✅ **Approved**\n"
                f"👤 **User ID:** `{user_id}`\n"
                f"💰 **Amount:** ₹{amount}\n"
                f"🪙 **Tokens Credited:** {tokens_to_add}\n"
                f"📌 **UTR:** `{tx['utr_number']}`\n"
                f"👨‍💼 **Approved By:** `{clicker_id}`"
            )
            await bot.send_message(chat_id=gid3, text=audit_text, parse_mode="Markdown")
        except Exception as e:
            print(f"Group 3 Audit Error: {e}")

    await callback.message.edit_text(f"{callback.message.text}\n\n✅ **APPROVED BY ADMIN**")
    await callback.answer("Payment Approved Successfully!", show_alert=True)

@dp.callback_query(F.data.startswith("reject_tx_"))
async def reject_payment_callback(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        await callback.answer("❌ Keval Super Admin hi reject kar sakte hain!", show_alert=True)
        return

    tx_id = callback.data.replace("reject_tx_", "")
    try:
        await transactions_col.update_one({"_id": tx_id}, {"$set": {"status": "rejected"}})
    except Exception as e:
        print(f"Reject Error: {e}")

    await callback.message.edit_text(f"{callback.message.text}\n\n❌ **REJECTED BY ADMIN**")
    await callback.answer("Payment Rejected")

# --- FASTAPI ENDPOINTS ---

@app.get("/api/user/{user_id}")
async def get_user_data(user_id: int):
    try:
        user = await asyncio.wait_for(users_col.find_one({"user_id": user_id}), timeout=4.0)
        if not user:
            return {"user_id": user_id, "tokens": 0, "first_name": "Guest"}
        return {"user_id": user["user_id"], "first_name": user.get("first_name", "User"), "tokens": user.get("tokens", 0)}
    except Exception:
        return {"user_id": user_id, "tokens": 0, "first_name": "Guest"}

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

    try:
        await asyncio.wait_for(transactions_col.insert_one(tx_doc), timeout=8.0)
    except Exception as e:
        print(f"Recharge DB Save Error: {e}")
        return {"status": "error", "message": f"Database Error: {str(e)[:50]}"}

    if GROUP_1_ID:
        try:
            gid1 = int(GROUP_1_ID) if str(GROUP_1_ID).replace("-", "").isdigit() else GROUP_1_ID
            card_text = (
                f"💳 **NEW RECHARGE REQUEST**\n\n"
                f"👤 **User ID:** `{req.user_id}`\n"
                f"💵 **Amount:** ₹{req.amount_inr}\n"
                f"📌 **UTR:** `{req.utr_number}`"
            )
            markup = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_tx_{tx_id}"),
                    InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_tx_{tx_id}")
                ]]
            )
            await bot.send_message(chat_id=gid1, text=card_text, reply_markup=markup, parse_mode="Markdown")
        except Exception as e:
            print(f"Group 1 Card Send Error: {e}")

    return {"status": "submitted", "message": "UTR Super Admin ko verification ke liye bhej diya gaya hai."}

@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = types.Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception as e:
        print(f"Webhook Execution Error: {e}")
    return {"status": "ok"}

@app.get("/")
async def root():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return {"message": "Vynora Live Backend Active"}

@app.on_event("startup")
async def on_startup():
    if WEB_APP_URL:
        webhook_url = f"{WEB_APP_URL.rstrip('/')}/webhook"
        await bot.set_webhook(webhook_url)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
