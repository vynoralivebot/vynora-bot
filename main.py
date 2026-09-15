import os
import time
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Form, UploadFile, File
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

app = FastAPI()
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=10000)
db = client.get_database("vynora_live_db")

users_col = db.users
recharges_col = db.recharges
hosts_col = db.hosts
bookings_col = db.bookings
chats_col = db.chats

# Ensure uploads folder exists
os.makedirs("static/uploads", exist_ok=True)

@app.on_event("startup")
async def startup_event():
    if bot:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            webhook_url = f"{RENDER_URL}/webhook"
            await bot.set_webhook(webhook_url, drop_pending_updates=True)
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
    await message.answer("✨ **Vynora Live 1v1 me aapka swagat hai!**", reply_markup=kb, parse_mode="Markdown")

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

class GiftReq(BaseModel):
    user_id: int
    host_id: str
    gift_cost: int
    gift_name: str
    channel: Optional[str] = None

class ChatReq(BaseModel):
    channel: str
    sender: str
    text: str
    type: str = "chat"

@app.get("/")
async def serve_home():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return JSONResponse({"status": "error", "message": "index.html not found"}, status_code=404)

@app.get("/api/agora-token")
async def get_agora_token(channelName: str, uid: int, role: str = "publisher"):
    app_id = os.getenv("AGORA_APP_ID", "")
    app_cert = os.getenv("AGORA_APP_CERTIFICATE", "")
    
    if not app_id or not app_cert or not RtcTokenBuilder:
        return JSONResponse({"status": "error", "message": "Agora credentials missing"}, status_code=500)
    
    token = RtcTokenBuilder.buildTokenWithUid(
        app_id, app_cert, channelName, uid, 
        1 if role == "publisher" else 2, int(time.time()) + 7200
    )
    return {"status": "success", "token": token, "appId": app_id, "channel": channelName, "uid": uid}

@app.get("/api/user/{user_id}")
async def get_user_profile(user_id: int):
    user = await users_col.find_one({"_id": user_id})
    if not user:
        new_user = {"_id": user_id, "tokens": 0, "earnings": 0, "avatar": "", "created_at": datetime.utcnow()}
        await users_col.insert_one(new_user)
        return {"user_id": user_id, "tokens": 0, "earnings": 0, "avatar": ""}
    return {"user_id": user_id, "tokens": user.get("tokens", 0), "earnings": user.get("earnings", 0), "avatar": user.get("avatar", "")}

# UPDATED PROFILE PHOTO FILE UPLOAD ROUTE
@app.post("/api/update-profile-photo")
async def update_profile_photo(user_id: int = Form(...), avatar: UploadFile = File(...)):
    try:
        filename = f"avatar_{user_id}_{int(time.time())}_{avatar.filename}"
        filepath = os.path.join("static/uploads", filename)
        with open(filepath, "wb") as buffer:
            buffer.write(await avatar.read())
        
        avatar_url = f"{RENDER_URL}/static/uploads/{filename}"
        await users_col.update_one({"_id": user_id}, {"$set": {"avatar": avatar_url}}, upsert=True)
        return {"status": "success", "message": "Profile picture updated successfully!", "avatar_url": avatar_url}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.get("/api/host/status/{user_id}")
async def get_host_status(user_id: int):
    if user_id == SUPER_ADMIN_ID:
        return {"is_host": True, "status": "approved", "isVerified": True, "role": "admin"}
    host = await hosts_col.find_one({"user_id": user_id}) or await hosts_col.find_one({"_id": f"host_{user_id}"})
    if host and host.get("status") == "approved":
        return {"is_host": True, "status": "approved", "isVerified": True, "role": "host"}
    return {"is_host": False, "status": host.get("status", "none") if host else "none", "role": "user"}

# UPDATED RECHARGE ROUTE WITH FILE UPLOAD
@app.post("/api/recharge")
async def process_recharge(
    user_id: int = Form(...),
    amount_inr: float = Form(...),
    utr_number: str = Form(...),
    screenshot: UploadFile = File(...)
):
    try:
        filename = f"recharge_{user_id}_{int(time.time())}_{screenshot.filename}"
        filepath = os.path.join("static/uploads", filename)
        with open(filepath, "wb") as buffer:
            buffer.write(await screenshot.read())
            
        screenshot_url = f"{RENDER_URL}/static/uploads/{filename}"
        tx_id = f"tx_{int(time.time())}"
        
        await recharges_col.insert_one({
            "_id": tx_id, "user_id": user_id, "amount_inr": amount_inr, 
            "utr_number": utr_number, "screenshot_url": screenshot_url,
            "tokens": int(amount_inr), "status": "pending", "timestamp": datetime.utcnow()
        })
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Approve", callback_data=f"appr_{tx_id}"), 
            InlineKeyboardButton(text="❌ Reject", callback_data=f"rejc_{tx_id}")
        ]])
        
        if bot and GROUP_1_ID != 0:
            try:
                caption = f"💳 **NEW RECHARGE APPROVAL**\n👤 User ID: `{user_id}`\n💵 Amount: ₹{amount_inr}\n📌 UTR: `{utr_number}`"
                await bot.send_photo(chat_id=GROUP_1_ID, photo=screenshot_url, caption=caption, reply_markup=kb, parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Error sending recharge to group 1: {e}")
                
        return {"status": "success", "message": "UTR & Screenshot submitted for approval!"}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.post("/api/book-slot")
async def book_slot(req: BookingReq):
    user = await users_col.find_one({"_id": req.user_id})
    if not user or user.get("tokens", 0) < req.token_cost:
        return {"status": "error", "message": "Insufficient Token Balance!"}
    booking_id = f"bk_{int(time.time())}"
    await bookings_col.insert_one({"_id": booking_id, "user_id": req.user_id, "host_id": req.host_id, "host_name": req.host_name, "duration_mins": req.duration_mins, "token_cost": req.token_cost, "status": "pending", "timestamp": datetime.utcnow()})
    await users_col.update_one({"_id": req.user_id}, {"$inc": {"tokens": -req.token_cost}})
    return {"status": "success", "booking_id": booking_id, "message": "Slot booked successfully!"}

@app.post("/api/send-gift")
async def send_gift(req: GiftReq):
    user = await users_col.find_one({"_id": req.user_id})
    if not user or user.get("tokens", 0) < req.gift_cost:
        return {"status": "error", "message": "Insufficient tokens to send gift!"}
    await users_col.update_one({"_id": req.user_id}, {"$inc": {"tokens": -req.gift_cost}})
    await hosts_col.update_one({"_id": req.host_id}, {"$inc": {"earnings": req.gift_cost}}, upsert=True)
    
    if req.channel:
        await chats_col.insert_one({
            "channel": req.channel,
            "sender": "Gift Alert 🎁",
            "text": f"sent {req.gift_name}!",
            "type": "gift",
            "timestamp": datetime.utcnow()
        })
        
    return {"status": "success", "message": f"Successfully sent {req.gift_name}! 🎁"}

@app.post("/api/send-chat")
async def send_chat(req: ChatReq):
    await chats_col.insert_one({
        "channel": req.channel,
        "sender": req.sender,
        "text": req.text,
        "type": req.type,
        "timestamp": datetime.utcnow()
    })
    return {"status": "success"}

@app.get("/api/get-chat/{channel}")
async def get_chat(channel: str):
    cursor = chats_col.find({"channel": channel}).sort("timestamp", 1).limit(50)
    messages = []
    async for doc in cursor:
        messages.append({
            "sender": doc.get("sender"),
            "text": doc.get("text"),
            "type": doc.get("type", "chat")
        })
    return {"status": "success", "messages": messages}

DUMMY_HOSTS = [
    { "id": "h1", "name": "Anu ❤️", "rate": 50, "isVerified": True, "isPrivate": False, "bio": "Friendly 1v1 chats 💖", "img": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=600&auto=format&fit=crop" },
    { "id": "h2", "name": "Sophia Rose", "rate": 80, "isVerified": True, "isPrivate": True, "bio": "High quality 1v1 👑", "img": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=600&auto=format&fit=crop" }
]

@app.get("/api/hosts")
async def get_online_hosts():
    try:
        cursor = hosts_col.find({"status": "approved"})
        hosts_list = []
        async for doc in cursor:
            hosts_list.append({
                "id": str(doc["_id"]), "user_id": doc.get("user_id"), "name": doc.get("name", "Host"),
                "rate": doc.get("rate", 50), "isVerified": True, "isPrivate": doc.get("isPrivate", False),
                "bio": doc.get("bio", "Verified Host"), "img": doc.get("img", "")
            })
        return {"status": "success", "hosts": hosts_list + DUMMY_HOSTS}
    except Exception as e:
        return {"status": "success", "hosts": DUMMY_HOSTS}

@app.post("/api/register-host")
async def register_host(req: RegisterHostReq):
    try:
        doc = {"_id": f"host_{req.user_id}", "user_id": req.user_id, "name": req.name, "age": req.age, "rate": req.rate, "lang": req.lang, "loc": req.loc, "img": req.img, "bio": req.bio, "status": "pending", "isVerified": False, "isPrivate": False, "created_at": datetime.utcnow()}
        await hosts_col.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Approve", callback_data=f"apphost_{req.user_id}"), InlineKeyboardButton(text="❌ Reject", callback_data=f"rejhost_{req.user_id}")]])
        
        if bot and GROUP_1_ID != 0:
            if req.img and req.img.startswith("http"):
                await bot.send_photo(chat_id=GROUP_1_ID, photo=req.img, caption=f"🟡 **HOST REGISTRATION**\n👤 User ID: `{req.user_id}`\n📛 Name: {req.name}\n🪙 Rate: {req.rate}/min", reply_markup=kb, parse_mode="Markdown")
            else:
                await bot.send_message(chat_id=GROUP_1_ID, text=f"🟡 **HOST REGISTRATION**\n👤 User ID: `{req.user_id}`\n📛 Name: {req.name}\n🪙 Rate: {req.rate}/min", reply_markup=kb, parse_mode="Markdown")
        return {"status": "success", "message": "Submitted for approval!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# FIXED CALLBACK QUERY FOR RECHARGE APPROVAL
@dp.callback_query(F.data.startswith("appr_"))
async def approve_recharge(call: types.CallbackQuery):
    await call.answer("Processing...")
    tx_id = call.data.replace("appr_", "", 1)  # Fixed split bug!
    tx = await recharges_col.find_one({"_id": tx_id})
    if tx and tx.get("status") == "pending":
        await recharges_col.update_one({"_id": tx_id}, {"$set": {"status": "approved"}})
        await users_col.update_one({"_id": tx["user_id"]}, {"$inc": {"tokens": tx["tokens"]}}, upsert=True)
        
        if bot:
            try:
                await bot.send_message(chat_id=tx["user_id"], text=f"🎉 **Badhaai ho!** Aapka ₹{tx['amount_inr']} ka recharge approve ho gaya hai aur `{tx['tokens']} Tokens` add ho gaye hain! 🪙", parse_mode="Markdown")
            except:
                pass
                
        if call.message:
            try:
                if call.message.caption:
                    await call.message.edit_caption(caption=call.message.caption + "\n\n✅ **APPROVED BY ADMIN**", reply_markup=None, parse_mode="Markdown")
                elif call.message.text:
                    await call.message.edit_text(call.message.text + "\n\n✅ **APPROVED BY ADMIN**", reply_markup=None, parse_mode="Markdown")
            except:
                pass
                
        if bot and GROUP_3_ID != 0:
            try:
                await bot.send_message(chat_id=GROUP_3_ID, text=f"✅ **RECHARGE APPROVED LOG**\n👤 User ID: `{tx['user_id']}`\n💵 Amount: ₹{tx['amount_inr']}\n📌 UTR: `{tx['utr_number']}`\n🪙 Tokens Added: {tx['tokens']}", parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Error sending approval log to group 3: {e}")

@dp.callback_query(F.data.startswith("apphost_"))
async def approve_host_cb(call: types.CallbackQuery):
    try:
        host_u_id = int(call.data.split("_")[1])
        await hosts_col.update_one({"user_id": host_u_id}, {"$set": {"status": "approved", "isVerified": True}}, upsert=True)
        await hosts_col.update_one({"_id": f"host_{host_u_id}"}, {"$set": {"status": "approved", "isVerified": True}}, upsert=True)
        if call.message:
            try:
                if call.message.caption:
                    await call.message.edit_caption(caption=call.message.caption + "\n\n✅ **APPROVED**", reply_markup=None, parse_mode="Markdown")
                elif call.message.text:
                    await call.message.edit_text(call.message.text + "\n\n✅ **APPROVED**", reply_markup=None, parse_mode="Markdown")
            except:
                pass
        if bot:
            try:
                await bot.send_message(chat_id=host_u_id, text="🎉 Aapka host account approve ho gaya hai! Ab app khol kar Live jayein.", parse_mode="Markdown")
            except:
                pass
        await call.answer("Approved successfully!", show_alert=True)
    except Exception as e:
        await call.answer(f"Error: {e}", show_alert=True)
