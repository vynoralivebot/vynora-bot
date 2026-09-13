import os
import time
import logging
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
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "7001825467"))
GROUP_1_ID = int(os.getenv("GROUP_1_ID", "-1001234567890"))

app = FastAPI()
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=10000)
db = client.get_database("vynora_live_db")

users_col = db.users
recharges_col = db.recharges
hosts_col = db.hosts
bookings_col = db.bookings

# --- Request Models ---
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

# --- APIs ---

@app.get("/")
async def serve_home():
    return FileResponse("static/index.html")

@app.get("/api/user/{user_id}")
async def get_user_profile(user_id: int):
    user = await users_col.find_one({"_id": user_id})
    if not user:
        new_user = {"_id": user_id, "tokens": 0, "credits": 0, "role": "user", "created_at": datetime.utcnow()}
        await users_col.insert_one(new_user)
        return {"user_id": user_id, "tokens": 0, "credits": 0}
    return {"user_id": user_id, "tokens": user.get("tokens", 0), "credits": user.get("credits", 0)}

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

# --- SLOT BOOKING API ---
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
    
    # Deduct tokens temporarily
    await users_col.update_one({"_id": req.user_id}, {"$inc": {"tokens": -req.token_cost}})

    # Notify Admin Group 1
    if bot:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Host Accept", callback_data=f"accbk_{booking_id}"),
            InlineKeyboardButton(text="❌ Cancel Booking", callback_data=f"canbk_{booking_id}")
        ]])
        msg = (
            f"📅 **NEW 1v1 SLOT BOOKING REQUEST**\n\n"
            f"👤 **User ID:** `{req.user_id}`\n"
            f"👩 **Host:** {req.host_name}\n"
            f"⏱️ **Duration:** {req.duration_mins} Minutes\n"
            f"🪙 **Token Amount:** {req.token_cost} Tokens"
        )
        try:
            await bot.send_message(chat_id=GROUP_1_ID, text=msg, reply_markup=kb, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Booking notify error: {e}")

    return {"status": "success", "message": f"Slot Booking Request of {req.duration_mins} mins sent to {req.host_name}!"}

@app.get("/api/hosts")
async def get_online_hosts():
    try:
        cursor = hosts_col.find({"status": "approved", "isOnline": True})
        hosts_list = []
        async for doc in cursor:
            hosts_list.append({
                "id": str(doc["_id"]),
                "name": doc.get("name", "Host"),
                "age": doc.get("age", 22),
                "rate": doc.get("rate", 50),
                "lang": doc.get("lang", "Hindi"),
                "loc": doc.get("loc", "India 🇮🇳"),
                "isPrivate": doc.get("isPrivate", False),
                "entryGiftCost": doc.get("entryGiftCost", 0),
                "isReal": True,
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
            "isReal": True,
            "isOnline": False,
            "isPrivate": False,
            "created_at": datetime.utcnow()
        }
        await hosts_col.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)

        if bot:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Approve Host", callback_data=f"apphost_{req.user_id}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"rejhost_{req.user_id}")
            ]])
            msg = f"👩 **NEW HOST REGISTRATION**\n\n👤 **User ID:** `{req.user_id}`\n📛 **Name:** {req.name}\n🪙 **Rate:** {req.rate}/min"
            try:
                await bot.send_photo(chat_id=GROUP_1_ID, photo=req.img, caption=msg, reply_markup=kb, parse_mode="Markdown")
            except:
                await bot.send_message(chat_id=GROUP_1_ID, text=msg, reply_markup=kb, parse_mode="Markdown")

        return {"status": "success", "message": "Host Application submitted for Admin approval!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/host-info/{user_id}")
async def get_host_info(user_id: int):
    doc = await hosts_col.find_one({"_id": f"host_{user_id}"})
    if not doc:
        return {"status": "none", "isOnline": False, "credits": 0}
    return {
        "status": doc.get("status", "none"),
        "isOnline": doc.get("isOnline", False),
        "isPrivate": doc.get("isPrivate", False),
        "entryGiftCost": doc.get("entryGiftCost", 0),
        "credits": doc.get("credits", 0)
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

# Callback Handlers
@dp.callback_query(F.data.startswith("appr_"))
async def approve_recharge(call: types.CallbackQuery):
    if call.from_user.id != SUPER_ADMIN_ID: return
    tx_id = call.data.split("_")[1]
    tx = await recharges_col.find_one({"_id": tx_id})
    if tx and tx.get("status") == "pending":
        await recharges_col.update_one({"_id": tx_id}, {"$set": {"status": "approved"}})
        await users_col.update_one({"_id": tx["user_id"]}, {"$inc": {"tokens": tx["tokens"]}}, upsert=True)
        await call.message.edit_text(call.message.text + "\n\n✅ **APPROVED BY ADMIN**", parse_mode="Markdown")

@dp.callback_query(F.data.startswith("rejc_"))
async def reject_recharge(call: types.CallbackQuery):
    if call.from_user.id != SUPER_ADMIN_ID: return
    tx_id = call.data.split("_")[1]
    await recharges_col.update_one({"_id": tx_id}, {"$set": {"status": "rejected"}})
    await call.message.edit_text(call.message.text + "\n\n❌ **REJECTED BY ADMIN**", parse_mode="Markdown")

@dp.callback_query(F.data.startswith("apphost_"))
async def approve_host_cb(call: types.CallbackQuery):
    if call.from_user.id != SUPER_ADMIN_ID: return
    host_u_id = int(call.data.split("_")[1])
    await hosts_col.update_one({"_id": f"host_{host_u_id}"}, {"$set": {"status": "approved", "isOnline": True}})
    await call.answer("Host Approved!")

@dp.callback_query(F.data.startswith("accbk_"))
async def accept_booking(call: types.CallbackQuery):
    bk_id = call.data.split("_")[1]
    await bookings_col.update_one({"_id": bk_id}, {"$set": {"status": "accepted"}})
    await call.message.edit_text(call.message.text + "\n\n✅ **BOOKING ACCEPTED BY HOST/ADMIN**", parse_mode="Markdown")
