import os
import time
import logging
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import motor.motor_asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logging.basicConfig(level=logging.INFO)

MONGO_URI = os.getenv("MONGO_URI", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROUP_1_ID = int(os.getenv("GROUP_1_ID", "-1001234567890"))

app = FastAPI()
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()

# MongoDB Connection
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=10000)
db = client.get_database("vynora_live_db")

users_col = db.users
recharges_col = db.recharges
hosts_col = db.hosts
bookings_col = db.bookings

# Startup Event: Clear Webhook & Start Telegram Polling
@app.on_event("startup")
async def startup_event():
    if bot:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            asyncio.create_task(dp.start_polling(bot))
            logging.info("🚀 Telegram Bot Polling Started Successfully!")
        except Exception as e:
            logging.error(f"Polling startup error: {e}")

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
    return FileResponse("static/index.html")

@app.get("/api/user/{user_id}")
async def get_user_profile(user_id: int):
    user = await users_col.find_one({"_id": user_id})
    if not user:
        new_user = {"_id": user_id, "tokens": 0, "earnings": 0, "role": "user", "created_at": datetime.utcnow()}
        await users_col.insert_one(new_user)
        return {"user_id": user_id, "tokens": 0, "earnings": 0}
    return {"user_id": user_id, "tokens": user.get("tokens", 0), "earnings": user.get("earnings", 0)}

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

    if bot:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Approve", callback_data=f"appr_{tx_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"rejc_{tx_id}")
        ]])
        msg = f"💳 **NEW RECHARGE REQUEST**\n\n👤 **User ID:** `{req.user_id}`\n💵 **Amount:** ₹{req.amount_inr}\n📌 **UTR:** `{req.utr_number}`"
        try:
            await bot.send_message(chat_id=GROUP_1_ID, text=msg, reply_markup=kb, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Error notifying group: {e}")

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

    if bot:
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
        try:
            await bot.send_message(chat_id=GROUP_1_ID, text=msg, reply_markup=kb, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Booking error: {e}")

    return {"status": "success", "message": f"Booking request sent for {req.host_name}!"}

# Dummy hosts list to always display alongside approved real hosts
DUMMY_HOSTS = [
    { "id": "h1", "name": "Anu ❤️", "rate": 50, "isVerified": True, "bio": "Friendly 1v1 chats & music lovers 💖", "img": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=600&auto=format&fit=crop" },
    { "id": "h2", "name": "Sophia Rose", "rate": 80, "isVerified": True, "bio": "High quality 1v1 experience 👑", "img": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=600&auto=format&fit=crop" },
    { "id": "h3", "name": "Priya Roy", "rate": 40, "isVerified": True, "bio": "Late night casual talks ✨", "img": "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=600&auto=format&fit=crop" },
    { "id": "h4", "name": "Elena Rostova", "rate": 100, "isVerified": True, "bio": "Available for private video calls 🚀", "img": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=600&auto=format&fit=crop" },
    { "id": "h5", "name": "Kavya Sharma", "rate": 55, "isVerified": True, "bio": "Let's talk and vibe together 🎶", "img": "https://images.unsplash.com/photo-1529626455594-4ff0802cfb7e?w=600&auto=format&fit=crop" }
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
            "earnings": 0,
            "created_at": datetime.utcnow()
        }
        await hosts_col.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)

        if bot:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Approve Host", callback_data=f"apphost_{req.user_id}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"rejhost_{req.user_id}")
            ]])
            msg = f"🟡 **HOST REGISTRATION REQUEST**\n\n👤 **User ID:** `{req.user_id}`\n📛 **Name:** {req.name}\n🪙 **Rate:** {req.rate}/min"
            try:
                await bot.send_photo(chat_id=GROUP_1_ID, photo=req.img, caption=msg, reply_markup=kb, parse_mode="Markdown")
            except:
                await bot.send_message(chat_id=GROUP_1_ID, text=msg, reply_markup=kb, parse_mode="Markdown")

        return {"status": "success", "message": "Submitted! Waiting for Admin Approval."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/host-info/{user_id}")
async def get_host_info(user_id: int):
    doc = await hosts_col.find_one({"_id": f"host_{user_id}"})
    if not doc:
        return {"status": "none", "isVerified": False, "earnings": 0}
    return {
        "status": doc.get("status", "none"),
        "isVerified": doc.get("isVerified", False),
        "earnings": doc.get("earnings", 0)
    }

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Telegram Bot Callback Handlers (Instant Approval Enabled)
@dp.callback_query(F.data.startswith("appr_"))
async def approve_recharge(call: types.CallbackQuery):
    tx_id = call.data.split("_")[1]
    tx = await recharges_col.find_one({"_id": tx_id})
    if tx and tx.get("status") == "pending":
        await recharges_col.update_one({"_id": tx_id}, {"$set": {"status": "approved"}})
        await users_col.update_one({"_id": tx["user_id"]}, {"$inc": {"tokens": tx["tokens"]}}, upsert=True)
        if call.message.text:
            await call.message.edit_text(call.message.text + "\n\n✅ **APPROVED BY ADMIN**", parse_mode="Markdown")
        await call.answer("Recharge Approved!")

@dp.callback_query(F.data.startswith("rejc_"))
async def reject_recharge(call: types.CallbackQuery):
    tx_id = call.data.split("_")[1]
    await recharges_col.update_one({"_id": tx_id}, {"$set": {"status": "rejected"}})
    if call.message.text:
        await call.message.edit_text(call.message.text + "\n\n❌ **REJECTED BY ADMIN**", parse_mode="Markdown")
    await call.answer("Recharge Rejected!")

@dp.callback_query(F.data.startswith("apphost_"))
async def approve_host_cb(call: types.CallbackQuery):
    host_u_id = int(call.data.split("_")[1])
    await hosts_col.update_one(
        {"_id": f"host_{host_u_id}"},
        {"$set": {"status": "approved", "isVerified": True}}
    )
    if call.message.caption:
        await call.message.edit_caption(caption=call.message.caption + "\n\n✅ **APPROVED BY ADMIN (VERIFIED HOST)**", reply_markup=None, parse_mode="Markdown")
    elif call.message.text:
        await call.message.edit_text(text=call.message.text + "\n\n✅ **APPROVED BY ADMIN (VERIFIED HOST)**", reply_markup=None, parse_mode="Markdown")
    await call.answer("Host Approved & Verified Successfully!")

@dp.callback_query(F.data.startswith("rejhost_"))
async def reject_host_cb(call: types.CallbackQuery):
    host_u_id = int(call.data.split("_")[1])
    await hosts_col.update_one({"_id": f"host_{host_u_id}"}, {"$set": {"status": "rejected", "isVerified": False}})
    if call.message.caption:
        await call.message.edit_caption(caption=call.message.caption + "\n\n❌ **REJECTED BY ADMIN**", reply_markup=None, parse_mode="Markdown")
    elif call.message.text:
        await call.message.edit_text(text=call.message.text + "\n\n❌ **REJECTED BY ADMIN**", reply_markup=None, parse_mode="Markdown")
    await call.answer("Host Rejected")
