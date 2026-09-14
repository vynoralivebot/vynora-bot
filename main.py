import os
import time
import logging
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import motor.motor_asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logging.basicConfig(level=logging.INFO)

MONGO_URI = os.getenv("MONGO_URI", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "7001825467"))
GROUP_1_ID = int(os.getenv("GROUP_1_ID", "-1001234567890"))

app = FastAPI(title="Vynora Live Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=10000)
db = client.get_database("vynora_live_db")

users_col = db.users
recharges_col = db.recharges
hosts_col = db.hosts
bookings_col = db.bookings

@app.on_event("startup")
async def startup_event():
    if bot and BOT_TOKEN:
        asyncio.create_task(dp.start_polling(bot))
        logging.info("🤖 Telegram Bot polling started successfully!")

@app.on_event("shutdown")
async def shutdown_event():
    if bot:
        await bot.session.close()
        logging.info("🤖 Telegram Bot session closed.")

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

class ToggleLiveReq(BaseModel):
    user_id: int
    is_private: Optional[bool] = False
    entry_gift_cost: Optional[int] = 0

@app.get("/")
async def serve_home():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return FileResponse("index.html") if os.path.exists("index.html") else "<h3>Frontend file not found!</h3>"

@app.get("/api/user/{user_id}")
async def get_user_profile(user_id: int):
    user = await users_col.find_one({"_id": user_id})
    if not user:
        new_user = {"_id": user_id, "tokens": 100, "earnings": 0, "role": "user", "created_at": datetime.utcnow()}
        await users_col.insert_one(new_user)
        return {"user_id": user_id, "tokens": 100, "earnings": 0}
    return {"user_id": user_id, "tokens": user.get("tokens", 0), "earnings": user.get("earnings", 0)}

@app.post("/api/recharge")
async def process_recharge(req: RechargeReq):
    tx_id = f"tx_{int(time.time())}"
    tokens_mapping = {100: 100, 200: 200, 300: 320, 400: 430, 500: 550, 1000: 1150, 1500: 1800}
    allocated_tokens = tokens_mapping.get(int(req.amount_inr), int(req.amount_inr))

    doc = {
        "_id": tx_id,
        "user_id": req.user_id,
        "amount_inr": req.amount_inr,
        "utr_number": req.utr_number,
        "tokens": allocated_tokens,
        "status": "pending",
        "timestamp": datetime.utcnow()
    }
    await recharges_col.insert_one(doc)

    if bot:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Approve", callback_data=f"appr_{tx_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"rejc_{tx_id}")
        ]])
        msg = f"💳 **NEW RECHARGE REQUEST**\n\n👤 **User ID:** `{req.user_id}`\n💵 **Amount:** ₹{req.amount_inr}\n🪙 **Tokens:** {allocated_tokens}\n📌 **UTR:** `{req.utr_number}`"
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

    return {"status": "success", "message": f"✨ Slot booked successfully with {req.host_name} for {req.duration_mins} mins!"}

@app.get("/api/hosts")
async def get_online_hosts():
    try:
        cursor = hosts_col.find({"status": "approved"})
        hosts_list = []
        async for doc in cursor:
            hosts_list.append({
                "id": str(doc.get("user_id")),
                "user_id": doc.get("user_id"),
                "name": doc.get("name", "Host"),
                "age": doc.get("age", 22),
                "rate": doc.get("rate", 50),
                "lang": doc.get("lang", "Hindi"),
                "loc": doc.get("loc", "India 🇮🇳"),
                "isPrivate": doc.get("isPrivate", False),
                "entryGiftCost": doc.get("entryGiftCost", 0),
                "isVerified": doc.get("isVerified", True),
                "earnings": doc.get("earnings", 0),
                "img": doc.get("img", ""),
                "bio": doc.get("bio", "")
            })
        return {"status": "success", "hosts": hosts_list}
    except Exception as e:
        return {"status": "error", "hosts": []}

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
            "isOnline": False,
            "isPrivate": False,
            "earnings": 0,
            "created_at": datetime.utcnow()
        }
        await hosts_col.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)

        if bot:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Approve Host", callback_data=f"apphost_{req.user_id}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"rejhost_{req.user_id}")
            ]])
            msg = f"👩 **HOST REGISTRATION REQUEST**\n\n👤 **User ID:** `{req.user_id}`\n📛 **Name:** {req.name}\n🪙 **Rate:** {req.rate}/min"
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
        return {"status": "none", "isOnline": False, "isVerified": False, "earnings": 0}
    return {
        "status": doc.get("status", "none"),
        "isOnline": doc.get("isOnline", False),
        "isPrivate": doc.get("isPrivate", False),
        "isVerified": doc.get("isVerified", False),
        "entryGiftCost": doc.get("entryGiftCost", 0),
        "earnings": doc.get("earnings", 0)
    }

@app.post("/api/host/toggle-live")
async def toggle_live(req: ToggleLiveReq):
    doc = await hosts_col.find_one({"_id": f"host_{req.user_id}"})
    if doc and doc.get("status") == "approved":
        new_online = not doc.get("isOnline", False)
        await hosts_col.update_one(
            {"_id": f"host_{req.user_id}"},
            {"$set": {
                "isOnline": new_online,
                "isPrivate": req.is_private,
                "entryGiftCost": req.entry_gift_cost
            }}
        )
        return {"status": "success", "isOnline": new_online, "isPrivate": req.is_private}
    return {"status": "error", "message": "Not an approved host"}

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@dp.callback_query(F.data.startswith("appr_"))
async def approve_recharge(call: types.CallbackQuery):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("You are not authorized!", show_alert=True)
        return
    tx_id = call.data.split("_")[1]
    tx = await recharges_col.find_one({"_id": tx_id})
    if tx and tx.get("status") == "pending":
        await recharges_col.update_one({"_id": tx_id}, {"$set": {"status": "approved"}})
        await users_col.update_one({"_id": tx["user_id"]}, {"$inc": {"tokens": tx["tokens"]}}, upsert=True)
        if call.message.caption:
            await call.message.edit_caption(caption=call.message.caption + "\n\n✅ **APPROVED BY ADMIN**", parse_mode="Markdown")
        else:
            await call.message.edit_text(call.message.text + "\n\n✅ **APPROVED BY ADMIN**", parse_mode="Markdown")
        await call.answer("Recharge Approved & Tokens Credited!")

@dp.callback_query(F.data.startswith("rejc_"))
async def reject_recharge(call: types.CallbackQuery):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("You are not authorized!", show_alert=True)
        return
    tx_id = call.data.split("_")[1]
    await recharges_col.update_one({"_id": tx_id}, {"$set": {"status": "rejected"}})
    if call.message.caption:
        await call.message.edit_caption(caption=call.message.caption + "\n\n❌ **REJECTED BY ADMIN**", parse_mode="Markdown")
    else:
        await call.message.edit_text(call.message.text + "\n\n❌ **REJECTED BY ADMIN**", parse_mode="Markdown")
    await call.answer("Recharge Rejected")

@dp.callback_query(F.data.startswith("apphost_"))
async def approve_host_cb(call: types.CallbackQuery):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("You are not authorized!", show_alert=True)
        return
    host_u_id = int(call.data.split("_")[1])
    await hosts_col.update_one(
        {"_id": f"host_{host_u_id}"},
        {"$set": {"status": "approved", "isVerified": True, "isOnline": True}}
    )
    if call.message.caption:
        await call.message.edit_caption(caption=call.message.caption + "\n\n✅ **APPROVED BY ADMIN (VERIFIED HOST)**", reply_markup=None, parse_mode="Markdown")
    else:
        await call.message.edit_text(text=call.message.text + "\n\n✅ **APPROVED BY ADMIN (VERIFIED HOST)**", reply_markup=None, parse_mode="Markdown")
    await call.answer("Host Approved & Verified!")

@dp.callback_query(F.data.startswith("rejhost_"))
async def reject_host_cb(call: types.CallbackQuery):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("You are not authorized!", show_alert=True)
        return
    host_u_id = int(call.data.split("_")[1])
    await hosts_col.update_one({"_id": f"host_{host_u_id}"}, {"$set": {"status": "rejected", "isVerified": False, "isOnline": False}})
    if call.message.caption:
        await call.message.edit_caption(caption=call.message.caption + "\n\n❌ **REJECTED BY ADMIN**", reply_markup=None, parse_mode="Markdown")
    else:
        await call.message.edit_text(text=call.message.text + "\n\n❌ **REJECTED BY ADMIN**", reply_markup=None, parse_mode="Markdown")
    await call.answer("Host Rejected")
