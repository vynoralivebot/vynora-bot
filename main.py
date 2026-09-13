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

# Logging setup
logging.basicConfig(level=logging.INFO)

# Environment Variables
MONGO_URI = os.getenv("MONGO_URI", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "7001825467"))
GROUP_1_ID = int(os.getenv("GROUP_1_ID", "-1001234567890"))
GROUP_2_ID = int(os.getenv("GROUP_2_ID", "-1001234567891"))
GROUP_3_ID = int(os.getenv("GROUP_3_ID", "-1001234567892"))

# FastAPI App & Bot Init
app = FastAPI()
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()

# MongoDB Connection
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=10000)
db = client.get_database("vynora_live_db")

users_col = db.users
recharges_col = db.recharges
hosts_col = db.hosts
transactions_col = db.transactions

# --- Request Models ---
class RechargeReq(BaseModel):
    user_id: int
    amount_inr: float
    utr_number: str

class GiftReq(BaseModel):
    user_id: int
    host_id: str
    gift_type: str
    token_price: int

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

# --- API Endpoints ---

@app.get("/")
async def serve_home():
    return FileResponse("static/index.html")

@app.get("/api/user/{user_id}")
async def get_user_profile(user_id: int):
    user = await users_col.find_one({"_id": user_id})
    if not user:
        new_user = {"_id": user_id, "tokens": 0, "role": "user", "created_at": datetime.utcnow()}
        await users_col.insert_one(new_user)
        return {"user_id": user_id, "tokens": 0}
    return {"user_id": user_id, "tokens": user.get("tokens", 0)}

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
            logging.error(f"Bot notification error: {e}")

    return {"status": "success", "message": "UTR submitted for Admin approval!"}

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
                "rating": doc.get("rating", "5.0"),
                "calls": doc.get("calls", "10+"),
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
            "isVerified": False,
            "isOnline": False,
            "created_at": datetime.utcnow()
        }
        await hosts_col.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)

        if bot:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Approve Host", callback_data=f"apphost_{req.user_id}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"rejhost_{req.user_id}")
            ]])
            msg = (
                f"👩 **NEW HOST REGISTRATION REQUEST**\n\n"
                f"👤 **User ID:** `{req.user_id}`\n"
                f"📛 **Name:** {req.name}\n"
                f"🎂 **Age:** {req.age}\n"
                f"🪙 **Rate:** {req.rate} Tokens/min\n"
                f"🗣️ **Languages:** {req.lang}\n"
                f"📍 **Location:** {req.loc}\n"
                f"📝 **Bio:** {req.bio}"
            )
            try:
                await bot.send_photo(chat_id=GROUP_1_ID, photo=req.img, caption=msg, reply_markup=kb, parse_mode="Markdown")
            except Exception as photo_err:
                await bot.send_message(chat_id=GROUP_1_ID, text=msg, reply_markup=kb, parse_mode="Markdown")

        return {"status": "success", "message": "Host Application submitted for Admin approval!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/host-info/{user_id}")
async def get_host_info(user_id: int):
    doc = await hosts_col.find_one({"_id": f"host_{user_id}"})
    if not doc:
        return {"status": "none", "isOnline": False}
    return {
        "status": doc.get("status", "none"),
        "isOnline": doc.get("isOnline", False),
        "isVerified": doc.get("isVerified", False)
    }

@app.post("/api/host/toggle-live")
async def toggle_live(req: ToggleLiveReq):
    doc = await hosts_col.find_one({"_id": f"host_{req.user_id}"})
    if doc and doc.get("status") == "approved":
        new_online = not doc.get("isOnline", False)
        await hosts_col.update_one({"_id": f"host_{req.user_id}"}, {"$set": {"isOnline": new_online}})
        return {"status": "success", "isOnline": new_online}
    return {"status": "error", "message": "Not an approved host"}

# Static Files Mount
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Telegram Bot Callback Handlers ---

@dp.callback_query(F.data.startswith("appr_"))
async def approve_recharge(call: types.CallbackQuery):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("❌ Only Super Admin can approve!", show_alert=True)
        return
    tx_id = call.data.split("_")[1]
    tx = await recharges_col.find_one({"_id": tx_id})
    if tx and tx.get("status") == "pending":
        await recharges_col.update_one({"_id": tx_id}, {"$set": {"status": "approved"}})
        await users_col.update_one({"_id": tx["user_id"]}, {"$inc": {"tokens": tx["tokens"]}}, upsert=True)
        await call.message.edit_text(call.message.text + "\n\n✅ **APPROVED BY ADMIN**", parse_mode="Markdown")
        await call.answer("Recharge Approved!")

@dp.callback_query(F.data.startswith("rejc_"))
async def reject_recharge(call: types.CallbackQuery):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("❌ Only Super Admin can reject!", show_alert=True)
        return
    tx_id = call.data.split("_")[1]
    await recharges_col.update_one({"_id": tx_id}, {"$set": {"status": "rejected"}})
    await call.message.edit_text(call.message.text + "\n\n❌ **REJECTED BY ADMIN**", parse_mode="Markdown")
    await call.answer("Recharge Rejected!")

@dp.callback_query(F.data.startswith("apphost_"))
async def approve_host_cb(call: types.CallbackQuery):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("❌ Only Super Admin can approve hosts!", show_alert=True)
        return
    host_u_id = int(call.data.split("_")[1])
    await hosts_col.update_one(
        {"_id": f"host_{host_u_id}"},
        {"$set": {"status": "approved", "isVerified": True, "isOnline": True}}
    )
    if call.message.caption:
        await call.message.edit_caption(caption=call.message.caption + "\n\n✅ **APPROVED BY ADMIN (LIVE ACTIVE)**", reply_markup=None)
    else:
        await call.message.edit_text(text=call.message.text + "\n\n✅ **APPROVED BY ADMIN (LIVE ACTIVE)**", reply_markup=None)
    await call.answer("Host Approved!")

@dp.callback_query(F.data.startswith("rejhost_"))
async def reject_host_cb(call: types.CallbackQuery):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("❌ Only Super Admin can reject hosts!", show_alert=True)
        return
    host_u_id = int(call.data.split("_")[1])
    await hosts_col.update_one({"_id": f"host_{host_u_id}"}, {"$set": {"status": "rejected", "isOnline": False}})
    if call.message.caption:
        await call.message.edit_caption(caption=call.message.caption + "\n\n❌ **REJECTED BY ADMIN**", reply_markup=None)
    else:
        await call.message.edit_text(text=call.message.text + "\n\n❌ **REJECTED BY ADMIN**", reply_markup=None)
    await call.answer("Host Rejected!")
