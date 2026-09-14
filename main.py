import os
import time
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import motor.motor_asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Update, WebAppInfo

try:
    from agora_token_builder import RtcTokenBuilder
except ImportError:
    RtcTokenBuilder = None

logging.basicConfig(level=logging.INFO)

MONGO_URI = os.getenv("MONGO_URI", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
RENDER_URL = os.getenv("RENDER_URL", "https://vynora-bot.onrender.com")

GROUP_1_ID = int(os.getenv("GROUP_1_ID", "0"))
GROUP_2_ID = int(os.getenv("GROUP_2_ID", "0"))
GROUP_3_ID = int(os.getenv("GROUP_3_ID", "0"))
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "7001825467"))

AGORA_APP_ID = os.getenv("AGORA_APP_ID", "")
AGORA_APP_CERTIFICATE = os.getenv("AGORA_APP_CERTIFICATE", "")

app = FastAPI()
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=10000)
db = client.get_database("vynora_live_db")

users_col = db.users
recharges_col = db.recharges
hosts_col = db.hosts
bookings_col = db.bookings

async def notify_all_groups(text, reply_markup=None, photo=None):
    if not bot:
        return
    group_ids = [GROUP_1_ID, GROUP_2_ID, GROUP_3_ID]
    for g_id in group_ids:
        if g_id != 0:
            try:
                if photo:
                    await bot.send_photo(chat_id=g_id, photo=photo, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
                else:
                    await bot.send_message(chat_id=g_id, text=text, reply_markup=reply_markup, parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Error sending to group {g_id}: {e}")

@app.on_event("startup")
async def startup_event():
    if bot:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            webhook_url = f"{RENDER_URL}/webhook"
            await bot.set_webhook(webhook_url, drop_pending_updates=True)
            logging.info(f"🔗 Telegram Webhook Successfully Set to: {webhook_url}")
        except Exception as e:
            logging.error(f"Webhook setup error: {e}")

@app.post("/webhook")
async def telegram_webhook(request: Request):
    if not bot:
        return {"ok": False}
    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_webhook_update(bot, update)
    return {"ok": True}

@dp.message(F.text == "/start")
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚀 Launch Vynora Live 1v1", web_app=WebAppInfo(url=RENDER_URL))
    ]])
    await message.answer(
        "✨ **Vynora Live 1v1 me aapka swagat hai!**\n\nNeeche button par click karke Mini App launch karein:",
        reply_markup=kb,
        parse_mode="Markdown"
    )

class RechargeReq(BaseModel):
    user_id: int
    amount_inr: float
    utr_number: str

class BookingReq(BaseModel):
    user_id: int
    host_id: str
    host_name: str
    duration_mins: int
    token_cost: int

class RegisterHostReq(BaseModel):
    user_id: int
    name: str
    age: int
    rate: int
    lang: str
    loc: str
    img: str
    bio: str

@app.get("/")
async def serve_home():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return JSONResponse({"status": "error", "message": "Frontend index.html not found in static folder!"}, status_code=404)

@app.get("/api/agora-token")
async def get_agora_token(channelName: str, uid: int, role: str = "publisher"):
    if not AGORA_APP_ID or not AGORA_APP_CERTIFICATE or not RtcTokenBuilder:
        return JSONResponse({"status": "error", "message": "Agora credentials or package missing on server."}, status_code=500)
    
    expiration_time_in_seconds = 7200
    current_timestamp = int(time.time())
    privilege_expired_ts = current_timestamp + expiration_time_in_seconds
    agora_role = 1 if role == "publisher" else 2

    token = RtcTokenBuilder.buildTokenWithUid(
        AGORA_APP_ID,
        AGORA_APP_CERTIFICATE,
        channelName,
        uid,
        agora_role,
        privilege_expired_ts
    )
    return {"status": "success", "token": token, "appId": AGORA_APP_ID, "channel": channelName, "uid": uid}

@app.get("/api/user/{user_id}")
async def get_user_profile(user_id: int):
    user = await users_col.find_one({"_id": user_id})
    if not user:
        new_user = {"_id": user_id, "tokens": 0, "earnings": 0, "role": "user", "created_at": datetime.utcnow()}
        await users_col.insert_one(new_user)
        return {"user_id": user_id, "tokens": 0, "earnings": 0}
    return {"user_id": user_id, "tokens": user.get("tokens", 0), "earnings": user.get("earnings", 0)}

@app.get("/api/host/status/{user_id}")
async def get_host_status(user_id: int):
    if user_id == SUPER_ADMIN_ID:
        return {"is_host": True, "status": "approved", "isVerified": True, "role": "admin"}
    
    host = await hosts_col.find_one({"user_id": user_id}) or await hosts_col.find_one({"_id": f"host_{user_id}"})
    if host and host.get("status") == "approved":
        return {"is_host": True, "status": "approved", "isVerified": True, "role": "host"}
    
    return {"is_host": False, "status": host.get("status", "none") if host else "none", "role": "user"}

@app.post("/api/recharge")
async def process_recharge(req: RechargeReq):
    tx_id = f"tx_{int(time.time())}"
    doc = {
        "_id": tx_id,
        "user_id": req.user_id,
        "amount_inr": req.amount_inr,
        "utr_number": req.utr_number,
        "tokens": int(req.amount_inr),
        "status": "pending",
        "timestamp": datetime.utcnow()
    }
    await recharges_col.insert_one(doc)

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Approve", callback_data=f"appr_{tx_id}"),
        InlineKeyboardButton(text="❌ Reject", callback_data=f"rejc_{tx_id}")
    ]])
    msg = f"💳 **NEW RECHARGE REQUEST**\n\n👤 **User ID:** `{req.user_id}`\n💵 **Amount:** ₹{req.amount_inr}\n📌 **UTR:** `{req.utr_number}`"
    await notify_all_groups(msg, reply_markup=kb)

    return {"status": "success", "message": "UTR submitted for Admin approval!"}

@app.post("/api/book-slot")
async def book_slot(req: BookingReq):
    user = await users_col.find_one({"_id": req.user_id})
    if not user or user.get("tokens", 0) < req.token_cost:
        return {"status": "error", "message": "Insufficient Token Balance!"}

    booking_id = f"bk_{int(time.time())}"
    doc = {
        "_id": booking_id,
        "user_id": req.user_id,
        "host_id": req.host_id,
        "host_name": req.host_name,
        "duration_mins": req.duration_mins,
        "token_cost": req.token_cost,
        "status": "pending",
        "timestamp": datetime.utcnow()
    }
    await bookings_col.insert_one(doc)
    await users_col.update_one({"_id": req.user_id}, {"$inc": {"tokens": -req.token_cost}})

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Accept Call", callback_data=f"accbk_{booking_id}"),
        InlineKeyboardButton(text="❌ Decline", callback_data=f"canbk_{booking_id}")
    ]])
    msg = (
        f"📅 **NEW 1v1 SLOT BOOKING**\n\n"
        f"👤 **User ID:** `{req.user_id}`\n"
        f"👩 **Host:** {req.host_name}\n"
        f"⏱️ **Duration:** {req.duration_mins} Mins\n"
        f"🪙 **Tokens Paid:** {req.token_cost}"
    )
    await notify_all_groups(msg, reply_markup=kb)

    return {"status": "success", "booking_id": booking_id, "message": f"Booking request sent for {req.host_name}!"}

DUMMY_HOSTS = [
    { "id": "h1", "name": "Anu ❤️", "rate": 50, "isVerified": True, "isPrivate": False, "bio": "Friendly 1v1 chats & music lovers 💖", "img": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=600&auto=format&fit=crop" },
    { "id": "h2", "name": "Sophia Rose", "rate": 80, "isVerified": True, "isPrivate": True, "entryGiftCost": 100, "bio": "High quality 1v1 experience 👑", "img": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=600&auto=format&fit=crop" }
]

@app.get("/api/hosts")
async def get_online_hosts():
    try:
        cursor = hosts_col.find({"status": "approved"})
        hosts_list = []
        async for doc in cursor:
            hosts_list.append({
                "id": str(doc["_id"]),
                "user_id": doc.get("user_id"),
                "name": doc.get("name", "Host"),
                "rate": doc.get("rate", 50),
                "isVerified": True,
                "isPrivate": doc.get("isPrivate", False),
                "entryGiftCost": doc.get("entryGiftCost", 0),
                "bio": doc.get("bio", "Verified Host"),
                "img": doc.get("img", "")
            })
        return {"status": "success", "hosts": hosts_list + DUMMY_HOSTS}
    except Exception as e:
        return {"status": "success", "hosts": DUMMY_HOSTS}

@app.post("/api/register-host")
async def register_host(req: RegisterHostReq):
    try:
        doc = {
            "_id": f"host_{req.user_id}",
            "user_id": req.user_id,
            "name": req.name,
            "age": req.age,
            "rate": req.rate,
            "lang": req.lang,
            "loc": req.loc,
            "img": req.img,
            "bio": req.bio,
            "status": "pending",
            "isVerified": False,
            "isPrivate": False,
            "entryGiftCost": 0,
            "earnings": 0,
            "created_at": datetime.utcnow()
        }
        await hosts_col.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)

        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Approve Host", callback_data=f"apphost_{req.user_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"rejhost_{req.user_id}")
        ]])
        msg = f"🟡 **HOST REGISTRATION REQUEST**\n\n👤 **User ID:** `{req.user_id}`\n📛 **Name:** {req.name}\n🪙 **Rate:** {req.rate}/min"
        await notify_all_groups(msg, reply_markup=kb, photo=req.img)

        return {"status": "success", "message": "Submitted! Waiting for Admin Approval."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@dp.callback_query(F.data.startswith("appr_"))
async def approve_recharge(call: types.CallbackQuery):
    await call.answer("Processing...")
    tx_id = call.data.split("_")[1]
    tx = await recharges_col.find_one({"_id": tx_id})
    if tx and tx.get("status") == "pending":
        await recharges_col.update_one({"_id": tx_id}, {"$set": {"status": "approved"}})
        await users_col.update_one({"_id": tx["user_id"]}, {"$inc": {"tokens": tx["tokens"]}}, upsert=True)
        if call.message and call.message.text:
            await call.message.edit_text(call.message.text + "\n\n✅ **APPROVED BY ADMIN**", parse_mode="Markdown")

@dp.callback_query(F.data.startswith("rejc_"))
async def reject_recharge(call: types.CallbackQuery):
    await call.answer("Rejected")
    tx_id = call.data.split("_")[1]
    await recharges_col.update_one({"_id": tx_id}, {"$set": {"status": "rejected"}})
    if call.message and call.message.text:
        await call.message.edit_text(call.message.text + "\n\n❌ **REJECTED BY ADMIN**", parse_mode="Markdown")

@dp.callback_query(F.data.startswith("apphost_"))
async def approve_host_cb(call: types.CallbackQuery):
    try:
        host_u_id = int(call.data.split("_")[1])
        await hosts_col.update_one({"user_id": host_u_id}, {"$set": {"status": "approved", "isVerified": True}}, upsert=True)
        await hosts_col.update_one({"_id": f"host_{host_u_id}"}, {"$set": {"status": "approved", "isVerified": True}}, upsert=True)

        if call.message and call.message.caption:
            await call.message.edit_caption(caption=call.message.caption + "\n\n✅ **APPROVED BY ADMIN (VERIFIED HOST)**", reply_markup=None, parse_mode="Markdown")
        elif call.message and call.message.text:
            await call.message.edit_text(text=call.message.text + "\n\n✅ **APPROVED BY ADMIN (VERIFIED HOST)**", reply_markup=None, parse_mode="Markdown")
        
        if bot:
            try:
                await bot.send_message(
                    chat_id=host_u_id,
                    text="🎉 **Badhaai ho!** Aapki host verification admin dwara **Approved** kar di gayi hai. Ab aap Vynora Live Mini App khol kar Live ja sakte hain!",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"Could not send DM to host {host_u_id}: {e}")

        await call.answer("Host Approved & Verified Successfully!", show_alert=True)
    except Exception as e:
        logging.error(f"Host approval error: {e}")
        await call.answer(f"Error: {e}", show_alert=True)

@dp.callback_query(F.data.startswith("rejhost_"))
async def reject_host_cb(call: types.CallbackQuery):
    host_u_id = int(call.data.split("_")[1])
    await hosts_col.update_one({"user_id": host_u_id}, {"$set": {"status": "rejected", "isVerified": False}})
    await hosts_col.update_one({"_id": f"host_{host_u_id}"}, {"$set": {"status": "rejected", "isVerified": False}})
    if call.message and call.message.caption:
        await call.message.edit_caption(caption=call.message.caption + "\n\n❌ **REJECTED BY ADMIN**", reply_markup=None, parse_mode="Markdown")
    elif call.message and call.message.text:
        await call.message.edit_text(text=call.message.text + "\n\n❌ **REJECTED BY ADMIN**", reply_markup=None, parse_mode="Markdown")
    await call.answer("Host Rejected")
