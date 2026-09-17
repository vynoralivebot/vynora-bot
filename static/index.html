import os
import logging
import asyncio
import httpx
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from agora_token_builder import RtcTokenBuilder
import time

# Logging Configuration 📝
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VynoraBackend")

# Environment Variables ⚙️
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "vynora_db")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
AGORA_APP_ID = os.getenv("AGORA_APP_ID", "")
AGORA_APP_CERTIFICATE = os.getenv("AGORA_APP_CERTIFICATE", "")

# Database Connection 🗄️
client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

app = FastAPI(title="Vynora Live 1v1 Backend 🚀")

# CORS Middleware 🌐
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return {"status": "success", "message": "Vynora Live Backend is running successfully! 🚀"}

# Helper function to send Telegram messages 📩
async def send_telegram_message(chat_id: str, text: str, reply_markup: Optional[dict] = None):
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("⚠️ TELEGRAM_BOT_TOKEN not set. Message skipped.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient() as http_client:
        try:
            res = await http_client.post(url, json=payload)
            return res.json()
        except Exception as e:
            logger.error(f"❌ Error sending Telegram message: {e}")

# Pydantic Models 📦
class BookingRequest(BaseModel):
    user_id: int
    host_id: str
    host_name: str
    duration_mins: int
    token_cost: int

class HostRegisterModel(BaseModel):
    user_id: int
    name: str
    age: int
    rate: int
    lang: str
    loc: str
    bio: Optional[str] = ""

class WithdrawRequest(BaseModel):
    user_id: int
    upi_id: str
    tokens: int

class ChatMessage(BaseModel):
    channel: str
    sender: str
    text: str
    type: str = "chat"

class GiftRequest(BaseModel):
    user_id: int
    host_id: str
    gift_cost: int
    gift_name: str
    channel: str
    sender_name: str

# --- API ENDPOINTS ---

@app.get("/api/user/{user_id}")
async def get_user_profile(user_id: int):
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        new_user = {
            "user_id": user_id,
            "tokens": 0,
            "earnings": 0.0,
            "net_earnings_inr": 0.0,
            "is_banned": False,
            "role": "user",
            "avatar": ""
        }
        await db.users.insert_one(new_user)
        user = new_user

    if user.get("is_banned", False):
        return {"status": "error", "is_banned": True, "message": "Account suspended."}

    return {
        "status": "success",
        "tokens": user.get("tokens", 0),
        "earnings": user.get("earnings", 0.0),
        "net_earnings_inr": user.get("net_earnings_inr", 0.0),
        "is_banned": False,
        "role": user.get("role", "user"),
        "avatar": user.get("avatar", "")
    }

@app.get("/api/hosts")
async def get_hosts():
    try:
        hosts_cursor = db.hosts.find({"status": "approved"})
        hosts_list = await hosts_cursor.to_list(length=100)
        formatted = []
        for h in hosts_list:
            formatted.append({
                "id": str(h["_id"]),
                "user_id": h.get("user_id"),
                "name": h.get("name", "Host"),
                "img": h.get("photo", "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=300&auto=format&fit=crop"),
                "rate": h.get("rate", 50),
                "bio": h.get("bio", "Live Stream"),
                "is_online": h.get("is_online", True),
                "isVerified": True,
                "isPrivate": True
            })
        return {"status": "success", "hosts": formatted}
    except Exception as e:
        logger.error(f"Error fetching hosts: {e}")
        return {"status": "success", "hosts": []}

@app.get("/api/host/status/{user_id}")
async def get_host_status(user_id: int):
    host = await db.hosts.find_one({"user_id": user_id})
    if not host:
        return {"is_host": False}
    return {
        "is_host": True,
        "status": host.get("status", "pending"),
        "is_online": host.get("is_online", True)
    }

@app.post("/api/host/toggle-live/{user_id}")
async def toggle_host_live(user_id: int):
    host = await db.hosts.find_one({"user_id": user_id})
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    new_status = not host.get("is_online", True)
    await db.hosts.update_one({"user_id": user_id}, {"$set": {"is_online": new_status}})
    return {"status": "success", "is_online": new_status}

@app.post("/api/host/update-rate")
async def update_host_rate(data: dict):
    user_id = data.get("user_id")
    rate = data.get("rate")
    if not user_id or not rate:
        return {"status": "error", "message": "Invalid parameters"}
    
    res = await db.hosts.update_one({"user_id": user_id}, {"$set": {"rate": int(rate)}})
    if res.modified_count > 0 or res.matched_count > 0:
        return {"status": "success", "message": "Rate updated successfully"}
    return {"status": "error", "message": "Host profile not found"}

@app.post("/api/register-host")
async def register_host(req: HostRegisterModel):
    existing = await db.hosts.find_one({"user_id": req.user_id})
    if existing:
        return {"status": "error", "message": "⚠️ Host application already submitted!"}

    host_data = {
        "user_id": req.user_id,
        "name": req.name,
        "age": req.age,
        "rate": req.rate,
        "lang": req.lang,
        "loc": req.loc,
        "bio": req.bio,
        "photo": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=300&auto=format&fit=crop",
        "status": "pending",
        "is_online": True
    }
    await db.hosts.insert_one(host_data)

    if ADMIN_CHAT_ID:
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Approve Host 👑", "callback_data": f"approve_host:{req.user_id}"},
                {"text": "❌ Reject Host 🚫", "callback_data": f"reject_host:{req.user_id}"}
            ]]
        }
        await send_telegram_message(ADMIN_CHAT_ID, f"👩‍💼 <b>New Host Registration</b>\n\n👤 Name: {req.name}\n🆔 User ID: <code>{req.user_id}</code>\n💎 Rate: {req.rate} tokens/min\n📝 Bio: {req.bio}", keyboard)

    return {"status": "success", "message": "📋 Host registration submitted for admin approval."}

@app.post("/api/book-slot")
async def book_slot(req: BookingRequest):
    user = await db.users.find_one({"user_id": req.user_id})
    if not user or user.get("tokens", 0) < req.token_cost:
        return {"status": "error", "message": "⚠️ Insufficient token balance. Please recharge!"}

    await db.users.update_one({"user_id": req.user_id}, {"$inc": {"tokens": -req.token_cost}})

    host = await db.hosts.find_one({"_id": ObjectId(req.host_id)})
    if not host:
        host = await db.hosts.find_one({"user_id": int(req.host_id)}) if req.host_id.isdigit() else None

    if not host:
        return {"status": "error", "message": "Host not found."}

    host_telegram_id = host.get("user_id")
    channel_name = f"private_call_{req.user_id}_{int(time.time())}"

    booking = {
        "user_id": req.user_id,
        "host_id": str(host["_id"]),
        "host_user_id": host_telegram_id,
        "host_name": req.host_name,
        "host_img": host.get("photo", ""),
        "duration_mins": req.duration_mins,
        "token_cost": req.token_cost,
        "status": "pending",
        "channel_name": channel_name,
        "time": time.time(),
        "formatted_time": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    res = await db.bookings.insert_one(booking)
    booking_id = str(res.inserted_id)

    if host_telegram_id:
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Accept Call 📞", "callback_data": f"accept_call:{booking_id}"},
                {"text": "❌ Reject 🚫", "callback_data": f"reject_call:{booking_id}"}
            ]]
        }
        msg = f"📞 <b>Incoming Private Call Request!</b>\n\n👤 User ID: <code>{req.user_id}</code>\n⏱️ Duration: {req.duration_mins} mins\n🪙 Cost: {req.token_cost} Tokens"
        await send_telegram_message(str(host_telegram_id), msg, reply_markup=keyboard)

    return {"status": "success", "booking_id": booking_id, "message": "Booking request sent successfully!"}

@app.get("/api/user/bookings/{user_id}")
async def get_user_bookings(user_id: int):
    cursor = db.bookings.find({"user_id": user_id}).sort("time", -1).limit(20)
    bookings = await cursor.to_list(length=20)
    formatted = []
    for b in bookings:
        formatted.append({
            "booking_id": str(b["_id"]),
            "host_name": b.get("host_name", "Host"),
            "host_img": b.get("host_img", ""),
            "duration_mins": b.get("duration_mins", 5),
            "token_cost": b.get("token_cost", 50),
            "status": b.get("status", "pending"),
            "channel_name": b.get("channel_name", ""),
            "call_started_at": b.get("call_started_at", b.get("time")),
            "formatted_time": b.get("formatted_time", "")
        })
    return {"status": "success", "bookings": formatted}

@app.get("/api/host/bookings/{host_user_id}")
async def get_host_bookings(host_user_id: int):
    cursor = db.bookings.find({"host_user_id": host_user_id}).sort("time", -1).limit(20)
    bookings = await cursor.to_list(length=20)
    formatted = []
    for b in bookings:
        formatted.append({
            "booking_id": str(b["_id"]),
            "user_id": b.get("user_id"),
            "duration_mins": b.get("duration_mins", 5),
            "token_cost": b.get("token_cost", 50),
            "status": b.get("status", "pending"),
            "channel_name": b.get("channel_name", ""),
            "call_started_at": b.get("call_started_at", b.get("time")),
            "formatted_time": b.get("formatted_time", "")
        })
    return {"status": "success", "bookings": formatted}

@app.post("/api/host/accept-booking")
async def accept_booking(data: dict):
    booking_id = data.get("booking_id")
    if not booking_id:
        return {"status": "error", "message": "Invalid booking ID"}

    booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
    if not booking:
        return {"status": "error", "message": "Booking not found"}

    call_started_at = time.time()
    await db.bookings.update_one(
        {"_id": ObjectId(booking_id)},
        {"$set": {"status": "approved", "call_started_at": call_started_at}}
    )

    host_share = booking["token_cost"] * 0.7
    host_share_inr = host_share * 1.0
    await db.users.update_one(
        {"user_id": booking["host_user_id"]},
        {"$inc": {"earnings": host_share, "net_earnings_inr": host_share_inr}}
    )

    await send_telegram_message(
        str(booking["user_id"]),
        f"✅ <b>Host Accepted Your Call!</b>\n\nYour private call has been accepted. Tap Rejoin or Accept on your app to connect!"
    )

    return {
        "status": "success",
        "message": "Booking accepted successfully",
        "channel_name": booking["channel_name"],
        "call_started_at": call_started_at
    }

@app.post("/api/host/reject-booking")
async def reject_booking(data: dict):
    booking_id = data.get("booking_id")
    if not booking_id:
        return {"status": "error", "message": "Invalid booking ID"}

    booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
    if not booking:
        return {"status": "error", "message": "Booking not found"}

    await db.bookings.update_one({"_id": ObjectId(booking_id)}, {"$set": {"status": "rejected"}})

    await db.users.update_one(
        {"user_id": booking["user_id"]},
        {"$inc": {"tokens": booking["token_cost"]}}
    )

    await send_telegram_message(
        str(booking["user_id"]),
        f"❌ <b>Call Request Rejected</b>\n\nYour call request was declined by the host. {booking['token_cost']} tokens have been refunded."
    )

    return {"status": "success", "message": "Booking rejected and tokens refunded."}

@app.post("/api/complete-booking")
async def complete_booking(data: dict):
    booking_id = data.get("booking_id")
    if booking_id:
        await db.bookings.update_one({"_id": ObjectId(booking_id)}, {"$set": {"status": "completed"}})
    return {"status": "success"}

@app.post("/api/recharge")
async def submit_recharge(user_id: int = Form(...), amount_inr: float = Form(...), utr_number: str = Form(...), screenshot: UploadFile = File(...)):
    rec = {
        "user_id": user_id,
        "amount": amount_inr,
        "utr": utr_number,
        "status": "pending",
        "time": time.time()
    }
    res = await db.recharges.insert_one(rec)
    rec_id = str(res.inserted_id)

    if ADMIN_CHAT_ID:
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Approve Payment 💵", "callback_data": f"approve_rec:{rec_id}"},
                {"text": "❌ Reject Payment ❌", "callback_data": f"reject_rec:{rec_id}"}
            ]]
        }
        await send_telegram_message(ADMIN_CHAT_ID, f"💰 <b>New Recharge Request!</b>\n\n👤 User ID: <code>{user_id}</code>\n💵 Amount: ₹{amount_inr}\n🧾 UTR: <code>{utr_number}</code>", keyboard)

    return {"status": "success", "message": "📥 Recharge request submitted successfully for approval!"}

@app.post("/api/withdraw")
async def request_withdrawal(req: WithdrawRequest):
    user = await db.users.find_one({"user_id": req.user_id})
    if not user or user.get("earnings", 0) < req.tokens:
        return {"status": "error", "message": "⚠️ Insufficient earnings balance."}

    payout_inr = req.tokens * 1.0
    w_data = {
        "user_id": req.user_id,
        "upi_id": req.upi_id,
        "tokens": req.tokens,
        "payout_inr": payout_inr,
        "status": "pending",
        "time": time.time()
    }
    res = await db.withdrawals.insert_one(w_data)
    w_id = str(res.inserted_id)

    await db.users.update_one({"user_id": req.user_id}, {"$inc": {"earnings": -req.tokens, "net_earnings_inr": -payout_inr}})

    if ADMIN_CHAT_ID:
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Approve Payout 🏦", "callback_data": f"approve_w:{w_id}"},
                {"text": "❌ Reject Payout ❌", "callback_data": f"reject_w:{w_id}"}
            ]]
        }
        await send_telegram_message(ADMIN_CHAT_ID, f"💸 <b>Withdrawal Request</b>\n\n👩‍💼 User ID: <code>{req.user_id}</code>\n💵 Tokens: {req.tokens}\n✨ Payout: ₹{payout_inr}\n📲 UPI: <code>{req.upi_id}</code>", keyboard)

    return {"status": "success", "message": "📤 Withdrawal request submitted successfully."}

@app.post("/api/update-profile-photo")
async def update_profile_photo(user_id: int = Form(...), avatar: UploadFile = File(...)):
    file_location = f"static/avatar_{user_id}_{int(time.time())}.jpg"
    with open(file_location, "wb+") as file_object:
        file_object.write(await avatar.read())

    avatar_url = f"/{file_location}"
    await db.users.update_one({"user_id": user_id}, {"$set": {"avatar": avatar_url}}, upsert=True)
    await db.hosts.update_one({"user_id": user_id}, {"$set": {"photo": avatar_url}})

    return {"status": "success", "avatar_url": avatar_url}

@app.get("/api/agora-token")
async def get_agora_token(channelName: str, uid: int, role: str):
    if not AGORA_APP_ID or not AGORA_APP_CERTIFICATE:
        return {"status": "error", "message": "Agora credentials not configured on server."}

    role_enum = 1 if role == "publisher" else 2
    expiration_time_in_seconds = 3600
    current_timestamp = int(time.time())
    privilege_expired_ts = current_timestamp + expiration_time_in_seconds

    token = RtcTokenBuilder.buildTokenWithUid(
        AGORA_APP_ID,
        AGORA_APP_CERTIFICATE,
        channelName,
        uid,
        role_enum,
        privilege_expired_ts
    )

    return {
        "status": "success",
        "appId": AGORA_APP_ID,
        "token": token,
        "channel": channelName,
        "uid": uid
    }

@app.post("/api/send-chat")
async def send_chat(msg: ChatMessage):
    await db.chats.insert_one(msg.dict())
    return {"status": "success"}

@app.get("/api/get-chat/{channel}")
async def get_chat(channel: str):
    cursor = db.chats.find({"channel": channel}).sort("_id", 1).limit(50)
    messages = await cursor.to_list(length=50)
    formatted = [{"sender": m["sender"], "text": m["text"], "type": m.get("type", "chat")} for m in messages]
    return {"status": "success", "messages": formatted}

@app.post("/api/send-gift")
async def send_gift(req: GiftRequest):
    user = await db.users.find_one({"user_id": req.user_id})
    if not user or user.get("tokens", 0) < req.gift_cost:
        return {"status": "error", "message": "Insufficient tokens"}

    await db.users.update_one({"user_id": req.user_id}, {"$inc": {"tokens": -req.gift_cost}})
    
    gift_msg = {
        "channel": req.channel,
        "sender": req.sender_name,
        "text": f"sent {req.gift_name} (🪙 {req.gift_cost})! 🎁✨",
        "type": "gift"
    }
    await db.chats.insert_one(gift_msg)
    return {"status": "success"}

# --- TELEGRAM WEBHOOK ---
@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    if "callback_query" in data:
        cq = data["callback_query"]
        cb_data = cq.get("data", "")
        chat_id = str(cq["message"]["chat"]["id"])

        if cb_data.startswith("approve_rec:"):
            rec_id = cb_data.split(":")[1]
            rec = await db.recharges.find_one({"_id": ObjectId(rec_id)})
            if rec and rec.get("status") == "pending":
                tokens = int(rec["amount"])
                await db.recharges.update_one({"_id": ObjectId(rec_id)}, {"$set": {"status": "approved"}})
                await db.users.update_one({"user_id": rec["user_id"]}, {"$inc": {"tokens": tokens}})
                await send_telegram_message(str(rec["user_id"]), f"🎉 <b>Recharge Approved!</b>\n\nAdded {tokens} tokens to your wallet! 🪙✨")
                await send_telegram_message(chat_id, f"✅ Recharge {rec_id} approved successfully.")

        elif cb_data.startswith("approve_host:"):
            host_uid = int(cb_data.split(":")[1])
            await db.hosts.update_one({"user_id": host_uid}, {"$set": {"status": "approved"}})
            await send_telegram_message(str(host_uid), "🎉 <b>Congratulations!</b>\n\nYour Host Application has been approved! You are now live on Vynora Live. 👑✨")
            await send_telegram_message(chat_id, f"✅ Host {host_uid} approved successfully.")

        elif cb_data.startswith("reject_host:"):
            host_uid = int(cb_data.split(":")[1])
            await db.hosts.update_one({"user_id": host_uid}, {"$set": {"status": "rejected"}})
            await send_telegram_message(str(host_uid), "❌ <b>Host Application Rejected</b>\n\nSorry, your host application was declined by admin.")
            await send_telegram_message(chat_id, f"❌ Host {host_uid} rejected.")

    elif "message" in data:
        msg = data["message"]
        text = msg.get("text", "")
        chat_id = str(msg["chat"]["id"])

        if str(chat_id) == str(ADMIN_CHAT_ID):
            parts = text.split()
            cmd = parts[0] if parts else ""

            if cmd == "/ban" and len(parts) > 1:
                target_uid = int(parts[1])
                await db.users.update_one({"user_id": target_uid}, {"$set": {"is_banned": True}})
                await send_telegram_message(chat_id, f"🚫 User <code>{target_uid}</code> has been banned.")

            elif cmd == "/unban" and len(parts) > 1:
                target_uid = int(parts[1])
                await db.users.update_one({"user_id": target_uid}, {"$set": {"is_banned": False}})
                await send_telegram_message(chat_id, f"✅ User <code>{target_uid}</code> has been unbanned.")

            elif cmd == "/addtokens" and len(parts) > 2:
                target_uid, amt = int(parts[1]), int(parts[2])
                await db.users.update_one({"user_id": target_uid}, {"$inc": {"tokens": amt}}, upsert=True)
                await send_telegram_message(chat_id, f"🪙 Added {amt} tokens to <code>{target_uid}</code>.")

            elif cmd == "/cuttokens" and len(parts) > 2:
                target_uid, amt = int(parts[1]), int(parts[2])
                await db.users.update_one({"user_id": target_uid}, {"$inc": {"tokens": -amt}})
                await send_telegram_message(chat_id, f"📉 Deducted {amt} tokens from <code>{target_uid}</code>.")

    return {"status": "ok"}
