import os
import logging
import asyncio
import httpx
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

# Logging Configuration 📝
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VynoraBackend")

# Environment Variables ⚙️
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "vynora_db")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")  # Primary Admin Chat ID

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

# Hardcoded Dummy Hosts Data 🎭
DUMMY_HOSTS = [
    {
        "_id": "dummy_1",
        "name": "Priya (Demo) 💖",
        "photo": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=500",
        "rate": 10,
        "is_dummy": True,
        "status": "approved",
        "bio": "Demo host profile ✨"
    },
    {
        "_id": "dummy_2",
        "name": "Ananya (Demo) 🌸",
        "photo": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=500",
        "rate": 15,
        "is_dummy": True,
        "status": "approved",
        "bio": "Demo host profile ✨"
    },
    {
        "_id": "dummy_3",
        "name": "Riya (Demo) 🌟",
        "photo": "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=500",
        "rate": 12,
        "is_dummy": True,
        "status": "approved",
        "bio": "Demo host profile ✨"
    },
    {
        "_id": "dummy_4",
        "name": "Sneha (Demo) 🦋",
        "photo": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=500",
        "rate": 18,
        "is_dummy": True,
        "status": "approved",
        "bio": "Demo host profile ✨"
    },
    {
        "_id": "dummy_5",
        "name": "Kavya (Demo) 👑",
        "photo": "https://images.unsplash.com/photo-1508214751196-bcfd4ca60f91?w=500",
        "rate": 20,
        "is_dummy": True,
        "status": "approved",
        "bio": "Demo host profile ✨"
    }
]

# Pydantic Models 📦
class BookingRequest(BaseModel):
    user_id: str
    host_id: str
    duration_minutes: int = 5

class RechargeRequest(BaseModel):
    user_id: str
    amount: float
    utr: str

class HostRegisterModel(BaseModel):
    user_id: str
    name: str
    rate: int
    bio: Optional[str] = ""

class WithdrawRequest(BaseModel):
    host_id: str
    upi_id: str
    amount: float

# --- API ENDPOINTS ---

@app.get("/api/user/{user_id}")
async def get_user_profile(user_id: str):
    """Fetch user info or create new user with 0 initial tokens 🪙"""
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        new_user = {
            "user_id": user_id,
            "tokens": 0,  # Zero Free Tokens 🪙
            "earnings": 0.0,
            "is_banned": False,
            "role": "user"
        }
        await db.users.insert_one(new_user)
        user = new_user

    return {
        "status": "success",
        "user": {
            "user_id": str(user["user_id"]),
            "tokens": user.get("tokens", 0),
            "earnings": user.get("earnings", 0.0),
            "is_banned": user.get("is_banned", False),
            "role": user.get("role", "user")
        }
    }

@app.get("/api/hosts")
async def get_hosts():
    """Fetch all hosts: Real hosts on top, Dummy hosts at the bottom 🔝👇"""
    try:
        # Real/Approved Hosts Database se fetch karein 👑
        real_hosts_cursor = db.hosts.find({"status": "approved"})
        real_hosts = await real_hosts_cursor.to_list(length=100)

        formatted_real_hosts = []
        for h in real_hosts:
            formatted_real_hosts.append({
                "_id": str(h["_id"]),
                "user_id": h.get("user_id"),
                "name": h.get("name", "Unknown Host 🌟"),
                "photo": h.get("photo", "https://via.placeholder.com/150"),
                "rate": h.get("rate", 10),
                "bio": h.get("bio", "Welcome to my live stream! ✨"),
                "is_dummy": False,
                "status": "approved"
            })

        # Combination: Real Hosts Pehle + Dummy Hosts Baad me 🎯
        combined_hosts = formatted_real_hosts + DUMMY_HOSTS
        return {"status": "success", "hosts": combined_hosts}

    except Exception as e:
        logger.error(f"❌ Error fetching hosts: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.post("/api/book-slot")
async def book_slot(req: BookingRequest):
    """Book a call slot 📞"""
    # Dummy host check 🎭
    if req.host_id.startswith("dummy_"):
        return {
            "status": "busy",
            "message": "📞 Host is currently busy on another call. Please try again later! ⏳"
        }

    # Fetch User 👤
    user = await db.users.find_one({"user_id": req.user_id})
    if not user or user.get("is_banned"):
        raise HTTPException(status_code=403, detail="🚫 User account restricted or not found.")

    # Fetch Real Host 👩‍💼
    try:
        host = await db.hosts.find_one({"_id": ObjectId(req.host_id)})
    except Exception:
        host = await db.hosts.find_one({"user_id": req.host_id})

    if not host:
        raise HTTPException(status_code=404, detail="❌ Host not found.")

    total_cost = host.get("rate", 10) * req.duration_minutes
    if user.get("tokens", 0) < total_cost:
        return {"status": "error", "message": "⚠️ Insufficient token balance. Please recharge! 🪙"}

    # Deduct tokens provisionally 🪙
    await db.users.update_one({"user_id": req.user_id}, {"$inc": {"tokens": -total_cost}})

    # Create Booking Record 📝
    booking = {
        "user_id": req.user_id,
        "host_id": str(host["_id"]),
        "host_user_id": host.get("user_id"),
        "duration": req.duration_minutes,
        "cost": total_cost,
        "status": "pending"
    }
    res = await db.bookings.insert_one(booking)
    booking_id = str(res.inserted_id)

    # Notify Host on Telegram 📲
    host_chat_id = host.get("user_id")
    if host_chat_id:
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Accept Call 📞", "callback_data": f"accept_call:{booking_id}"},
                {"text": "❌ Reject 🚫", "callback_data": f"reject_call:{booking_id}"}
            ]]
        }
        msg = f"📞 <b>Incoming Video Call Request!</b> 📲\n\n👤 User ID: <code>{req.user_id}</code>\n⏱️ Duration: {req.duration_minutes} mins\n🪙 Earnings: {total_cost * 0.7:.1f} tokens"
        await send_telegram_message(host_chat_id, msg, reply_markup=keyboard)

    return {"status": "success", "booking_id": booking_id, "message": "📲 Booking request sent to host!"}

@app.post("/api/register-host")
async def register_host(req: HostRegisterModel):
    """Register user as a host 👩‍💼"""
    existing = await db.hosts.find_one({"user_id": req.user_id})
    if existing:
        return {"status": "error", "message": "⚠️ Host profile already exists!"}

    host_data = {
        "user_id": req.user_id,
        "name": req.name,
        "rate": req.rate,
        "bio": req.bio,
        "photo": "https://via.placeholder.com/150",
        "status": "pending"
    }
    await db.hosts.insert_one(host_data)

    # Notify Admin for Approval 👮
    if ADMIN_CHAT_ID:
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Approve Host 👑", "callback_data": f"approve_host:{req.user_id}"},
                {"text": "❌ Reject Host 🚫", "callback_data": f"reject_host:{req.user_id}"}
            ]]
        }
        await send_telegram_message(ADMIN_CHAT_ID, f"👩‍💼 <b>New Host Registration Application</b> 📝\n\n👤 Name: {req.name}\n🆔 User ID: <code>{req.user_id}</code>\n💎 Rate: {req.rate} tokens/min", keyboard)

    return {"status": "success", "message": "📋 Host registration submitted for admin approval."}

@app.post("/api/recharge")
async def submit_recharge(req: RechargeRequest):
    """Submit top-up recharge request 💳"""
    rec = {
        "user_id": req.user_id,
        "amount": req.amount,
        "utr": req.utr,
        "status": "pending"
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
        await send_telegram_message(ADMIN_CHAT_ID, f"💰 <b>New Recharge Request!</b> 💳\n\n👤 User ID: <code>{req.user_id}</code>\n💵 Amount: ₹{req.amount}\n🧾 UTR: <code>{req.utr}</code>", keyboard)

    return {"status": "success", "message": "📥 Recharge request submitted successfully!"}

@app.post("/api/withdraw")
async def request_withdrawal(req: WithdrawRequest):
    """Request host earnings withdrawal 💸"""
    user = await db.users.find_one({"user_id": req.host_id})
    if not user or user.get("earnings", 0) < req.amount:
        return {"status": "error", "message": "⚠️ Insufficient earnings balance."}

    payout = req.amount * 0.7  # 30% platform fee
    w_data = {
        "host_id": req.host_id,
        "upi_id": req.upi_id,
        "requested_amount": req.amount,
        "payout_amount": payout,
        "status": "pending"
    }
    res = await db.withdrawals.insert_one(w_data)
    w_id = str(res.inserted_id)

    # Deduct balance provisionally 📉
    await db.users.update_one({"user_id": req.host_id}, {"$inc": {"earnings": -req.amount}})

    if ADMIN_CHAT_ID:
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Approve Payout 🏦", "callback_data": f"approve_w:{w_id}"},
                {"text": "❌ Reject Payout ❌", "callback_data": f"reject_w:{w_id}"}
            ]]
        }
        await send_telegram_message(ADMIN_CHAT_ID, f"💸 <b>Host Withdrawal Request</b> 🏦\n\n👩‍💼 Host ID: <code>{req.host_id}</code>\n💵 Requested: ₹{req.amount}\n✨ Payout (70%): ₹{payout}\n📲 UPI ID: <code>{req.upi_id}</code>", keyboard)

    return {"status": "success", "message": "📤 Withdrawal request submitted."}

# --- TELEGRAM WEBHOOK & ADMIN COMMANDS 🤖 ---

@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    data = await request.json()

    # Process Inline Keyboard Callbacks 🔘
    if "callback_query" in data:
        cq = data["callback_query"]
        cb_data = cq.get("data", "")

        if cb_data.startswith("approve_rec:"):
            rec_id = cb_data.split(":")[1]
            rec = await db.recharges.find_one({"_id": ObjectId(rec_id)})
            if rec and rec.get("status") == "pending":
                tokens_to_add = int(rec["amount"])  # 1 INR = 1 Token 🪙
                await db.recharges.update_one({"_id": ObjectId(rec_id)}, {"$set": {"status": "approved"}})
                await db.users.update_one({"user_id": rec["user_id"]}, {"$inc": {"tokens": tokens_to_add}})
                await send_telegram_message(rec["user_id"], f"🎉 <b>Recharge Approved!</b>\n\nAdded {tokens_to_add} tokens to your account! 🪙✨")
                await send_telegram_message(cq["from"]["id"], f"✅ Recharge {rec_id} approved successfully.")

        elif cb_data.startswith("approve_host:"):
            host_uid = cb_data.split(":")[1]
            await db.hosts.update_one({"user_id": host_uid}, {"$set": {"status": "approved"}})
            await send_telegram_message(host_uid, "🎉 <b>Congratulations!</b>\n\nYour Host Application has been approved! You are now Live. 👑✨")
            await send_telegram_message(cq["from"]["id"], f"✅ Host {host_uid} approved successfully.")

        elif cb_data.startswith("accept_call:"):
            booking_id = cb_data.split(":")[1]
            bk = await db.bookings.find_one({"_id": ObjectId(booking_id)})
            if bk and bk.get("status") == "pending":
                await db.bookings.update_one({"_id": ObjectId(booking_id)}, {"$set": {"status": "accepted"}})
                host_share = bk["cost"] * 0.7
                await db.users.update_one({"user_id": bk["host_user_id"]}, {"$inc": {"earnings": host_share}})
                await send_telegram_message(bk["user_id"], "✅ <b>Call Connected!</b>\n\nHost accepted your call! Connecting now... 📞✨")
                await send_telegram_message(cq["from"]["id"], "📞 <b>Call Started!</b> You are now connected.")

    # Process Telegram Admin Text Commands 🛠️
    elif "message" in data:
        msg = data["message"]
        text = msg.get("text", "")
        chat_id = str(msg["chat"]["id"])

        # Admin Commands Check 👮
        if str(chat_id) == str(ADMIN_CHAT_ID):
            parts = text.split()
            cmd = parts[0] if parts else ""

            if cmd == "/ban" and len(parts) > 1:
                target_uid = parts[1]
                await db.users.update_one({"user_id": target_uid}, {"$set": {"is_banned": True}})
                await send_telegram_message(chat_id, f"🚫 <b>User Banned:</b> User <code>{target_uid}</code> has been banned.")

            elif cmd == "/unban" and len(parts) > 1:
                target_uid = parts[1]
                await db.users.update_one({"user_id": target_uid}, {"$set": {"is_banned": False}})
                await send_telegram_message(chat_id, f"✅ <b>User Unbanned:</b> User <code>{target_uid}</code> has been unbanned.")

            elif cmd == "/addtokens" and len(parts) > 2:
                target_uid, amt = parts[1], int(parts[2])
                await db.users.update_one({"user_id": target_uid}, {"$inc": {"tokens": amt}})
                await send_telegram_message(chat_id, f"🪙 <b>Tokens Added:</b> Added {amt} tokens to <code>{target_uid}</code>.")

            elif cmd == "/cuttokens" and len(parts) > 2:
                target_uid, amt = parts[1], int(parts[2])
                await db.users.update_one({"user_id": target_uid}, {"$inc": {"tokens": -amt}})
                await send_telegram_message(chat_id, f"📉 <b>Tokens Deducted:</b> Removed {amt} tokens from <code>{target_uid}</code>.")

            elif cmd == "/userinfo" and len(parts) > 1:
                target_uid = parts[1]
                u = await db.users.find_one({"user_id": target_uid})
                if u:
                    await send_telegram_message(chat_id, f"👤 <b>User Details Info:</b>\n\n🆔 User ID: <code>{u['user_id']}</code>\n🪙 Tokens: {u.get('tokens',0)}\n🚫 Is Banned: {u.get('is_banned', False)}")
                else:
                    await send_telegram_message(chat_id, "⚠️ User not found.")

    return {"status": "ok"}
