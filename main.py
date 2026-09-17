import os
import time
import uuid
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests
from agora_token_builder import RtcTokenBuilder
from database import users_col, hosts_col, bookings_col, recharges_col, withdrawals_col, chats_col

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
GROUP_1_ID = os.getenv("GROUP_1_ID", "-100XXXXXXXXXX")
GROUP_2_ID = os.getenv("GROUP_2_ID", "-100XXXXXXXXXX")
GROUP_3_ID = os.getenv("GROUP_3_ID", "-100XXXXXXXXXX")
AGORA_APP_ID = os.getenv("AGORA_APP_ID", "YOUR_AGORA_APP_ID")
AGORA_APP_CERTIFICATE = os.getenv("AGORA_APP_CERTIFICATE", "YOUR_AGORA_CERTIFICATE")

# Admin IDs (Added Admin ID 1108685585 and primary admin)
ADMIN_IDS = [1108685585, 999999999]

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send_telegram_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": int(chat_id), "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        res = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
        return res.json()
    except Exception as e:
        print("Telegram Error:", e)

@app.on_event("startup")
def set_webhook_on_startup():
    render_url = "https://vynora-bot.onrender.com/telegram-webhook"
    webhook_api = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={render_url}"
    try:
        requests.get(webhook_api)
    except Exception as e:
        print("Webhook setup error:", e)

class HostRegisterModel(BaseModel):
    user_id: int
    name: str
    age: int
    rate: int
    lang: str
    loc: str
    bio: str

class UpdateRateModel(BaseModel):
    user_id: int
    rate: int

class BookingModel(BaseModel):
    user_id: int
    host_id: str
    host_name: str
    duration_mins: int
    token_cost: int

class ActionBookingModel(BaseModel):
    booking_id: str

class CompleteBookingModel(BaseModel):
    booking_id: str
    duration_secs: int = 0

class GiftModel(BaseModel):
    user_id: int
    host_id: str
    gift_cost: int
    gift_name: str
    channel: str
    sender_name: str

class ChatModel(BaseModel):
    channel: str
    sender: str
    text: str
    type: str = "chat"

class WithdrawModel(BaseModel):
    user_id: int
    upi_id: str
    tokens: int

@app.get("/api/user/{user_id}")
def get_user(user_id: int):
    user = users_col.find_one({"user_id": int(user_id)})
    if user and user.get("is_banned", False):
        return {"tokens": 0, "earnings": 0, "avatar": "", "is_banned": True}
    if not user:
        user = {"user_id": int(user_id), "tokens": 0, "earnings": 0, "avatar": "", "is_banned": False}
        users_col.insert_one(user)
        send_telegram_message(GROUP_2_ID, f"👤 <b>New User Started Bot!</b>\nID: <code>{user_id}</code>")
    return {
        "tokens": user.get("tokens", 0),
        "earnings": user.get("earnings", 0),
        "avatar": user.get("avatar", ""),
        "is_banned": False
    }

@app.get("/api/host/status/{user_id}")
def get_host_status(user_id: int):
    host = hosts_col.find_one({"$or": [{"user_id": int(user_id)}, {"id": str(user_id)}, {"id": f"h_{user_id}"}, {"_id": f"host_{user_id}"}]})
    if host:
        return {"is_host": True, "status": host.get("status", "pending"), "is_online": host.get("is_online", False)}
    return {"is_host": False, "status": "none", "is_online": False}

@app.post("/api/host/toggle-live/{user_id}")
def toggle_host_live(user_id: int):
    host = hosts_col.find_one({"$or": [{"user_id": int(user_id)}, {"id": str(user_id)}, {"id": f"h_{user_id}"}, {"_id": f"host_{user_id}"}]})
    if not host or host.get("status") != "approved":
        return {"status": "error", "message": "Host not found or not approved"}
    new_status = not host.get("is_online", False)
    hosts_col.update_one({"_id": host["_id"]}, {"$set": {"is_online": new_status}})
    return {"status": "success", "is_online": new_status}

@app.get("/api/hosts")
def get_hosts():
    db_hosts = list(hosts_col.find({"status": "approved"}, {"_id": 0}))
    dummy_hosts = [
        {"id": "dummy_1", "user_id": 9991, "name": "Sophia 💎", "age": 22, "rate": 40, "lang": "English", "loc": "UK", "img": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=400&auto=format&fit=crop", "bio": "International VIP Model ✨", "is_online": True, "is_dummy": True},
        {"id": "dummy_2", "user_id": 9992, "name": "Ananya 🔥", "age": 21, "rate": 50, "lang": "Hindi", "loc": "Mumbai", "img": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=400&auto=format&fit=crop", "bio": "Bollywood dancer & host 💃", "is_online": True, "is_dummy": True},
    ]
    all_hosts = db_hosts + dummy_hosts
    for h in all_hosts:
        if not h.get("id"):
            h["id"] = f"h_{h.get('user_id')}"
    return {"hosts": all_hosts}

@app.get("/api/agora-token")
def get_agora_token(channelName: str, uid: int, role: str):
    privilege_expired_ts = int(time.time()) + 3600
    rtc_role = 1 if role == "publisher" else 2
    token = RtcTokenBuilder.buildTokenWithUid(
        AGORA_APP_ID, AGORA_APP_CERTIFICATE, channelName, int(uid), rtc_role, privilege_expired_ts
    )
    return {"status": "success", "token": token, "appId": AGORA_APP_ID, "channel": channelName, "uid": int(uid)}

@app.post("/api/book-slot")
def book_slot(data: BookingModel):
    if str(data.host_id).startswith("dummy_"):
        return {"status": "error", "message": "✨ Host is currently busy in a private international session. Please try another host!"}
    user = users_col.find_one({"user_id": int(data.user_id)})
    if not user or user.get("tokens", 0) < data.token_cost:
        return {"status": "error", "message": f"Insufficient tokens! You need {data.token_cost} tokens. Please recharge."}
    
    users_col.update_one({"user_id": int(data.user_id)}, {"$inc": {"tokens": -data.token_cost}})
    booking_id = str(uuid.uuid4())[:8]
    clean_host_id = str(data.host_id).replace("h_", "").replace("host_", "")
    channel_name = f"private_call_{clean_host_id}_{data.user_id}"
    current_time = time.time()
    
    booking_doc = {
        "booking_id": booking_id,
        "user_id": int(data.user_id),
        "host_id": data.host_id,
        "host_name": data.host_name,
        "duration_mins": data.duration_mins,
        "token_cost": data.token_cost,
        "channel_name": channel_name,
        "status": "pending",
        "time": current_time,
        "call_started_at": 0
    }
    bookings_col.insert_one(booking_doc)
    
    host = hosts_col.find_one({"$or": [{"id": data.host_id}, {"_id": f"host_{clean_host_id}"}, {"user_id": int(clean_host_id) if clean_host_id.isdigit() else 0}]})
    if host and "user_id" in host:
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ Accept & Join", "callback_data": f"accept_bk_{booking_id}"},
                    {"text": "❌ Reject", "callback_data": f"reject_bk_{booking_id}"}
                ]
            ]
        }
        msg = f"🔔 <b>New Private Booking Request!</b>\n\n👤 User ID: <code>{data.user_id}</code>\n⏱️ Duration: {data.duration_mins} Mins\n🪙 Cost: {data.token_cost} Tokens"
        send_telegram_message(host["user_id"], msg, reply_markup=keyboard)
        
    group_msg = f"📌 <b>New Booking Received!</b>\nHost: {data.host_name}\nUser ID: <code>{data.user_id}</code>\nDuration: {data.duration_mins} Mins\nTokens: {data.token_cost}"
    send_telegram_message(GROUP_1_ID, group_msg)
    send_telegram_message(GROUP_3_ID, group_msg)
    return {"status": "success", "booking_id": booking_id}

@app.post("/api/host/accept-booking")
def accept_booking(data: ActionBookingModel):
    booking = bookings_col.find_one({"$or": [{"booking_id": data.booking_id}, {"_id": data.booking_id}]})
    if not booking or booking.get("status") != "pending":
        return {"status": "error", "message": "Booking not found or already processed"}
    
    current_time = time.time()
    bookings_col.update_one({"_id": booking["_id"]}, {"$set": {"status": "approved", "call_started_at": current_time}})
    
    h_val = str(booking["host_id"])
    clean_h = h_val.replace("h_", "").replace("host_", "")
    host = hosts_col.find_one({"$or": [{"id": h_val}, {"_id": f"host_{clean_h}"}, {"user_id": int(clean_h) if clean_h.isdigit() else 0}]})
    if host and "user_id" in host:
        users_col.update_one({"user_id": int(host["user_id"])}, {"$inc": {"earnings": booking["token_cost"]}}, upsert=True)
        
    webapp_url = "https://vynora-bot.onrender.com/static/index.html"
    user_keyboard = {"inline_keyboard": [[{"text": "📞 Answer Call", "web_app": {"url": webapp_url}}]]}
    send_telegram_message(int(booking["user_id"]), "📞 <b>Incoming Video Call!</b> Host accepted your booking. Tap below to pick up.", reply_markup=user_keyboard)
    return {"status": "success", "message": "Booking accepted successfully!", "channel_name": booking.get("channel_name"), "call_started_at": current_time}

@app.post("/api/complete-booking")
def complete_booking(data: CompleteBookingModel):
    booking = bookings_col.find_one({"$or": [{"booking_id": data.booking_id}, {"_id": data.booking_id}]})
    if booking:
        bookings_col.update_one({"_id": booking["_id"]}, {"$set": {"status": "completed"}})
        
        user_id = booking.get("user_id")
        host_name = booking.get("host_name")
        host_id = booking.get("host_id")
        duration_mins = booking.get("duration_mins", 1)
        actual_duration_secs = data.duration_secs if data.duration_secs > 0 else (duration_mins * 60)
        mins = actual_duration_secs // 60
        secs = actual_duration_secs % 60
        duration_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
        
        call_date_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(booking.get("time", time.time())))
        
        history_msg = (
            f"📊 <b>Call History Report (Group 3)</b>\n\n"
            f"📹 <b>Host Name:</b> {host_name} (ID: <code>{host_id}</code>)\n"
            f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
            f"📅 <b>Date & Time:</b> {call_date_time}\n"
            f"⏱️ <b>Call Duration:</b> {duration_str}\n"
            f"🪙 <b>Tokens Spent:</b> {booking.get('token_cost', 0)}\n"
            f"✅ <b>Status:</b> Completed Successfully"
        )
        send_telegram_message(GROUP_3_ID, history_msg)
        return {"status": "success", "message": "Booking completed and history sent"}
    return {"status": "error", "message": "Booking not found"}

@app.post("/telegram-webhook")
async def telegram_webhook(req: Request):
    body = await req.json()
    if "message" in body:
        msg = body["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        text = msg.get("text", "").strip()

        # Admin Commands Authorization Check for ADMIN_IDS (including 1108685585)
        if text.startswith(("/ban ", "/unban ", "/addtokens ", "/cuttokens ", "/userinfo ", "/hostinfo ")):
            if user_id not in ADMIN_IDS:
                send_telegram_message(chat_id, "🚫 You are not authorized to use admin commands.")
                return {"ok": True}

        if text.startswith("/ban "):
            try:
                target_id = int(text.replace("/ban ", "").strip())
                users_col.update_one({"user_id": target_id}, {"$set": {"is_banned": True}}, upsert=True)
                send_telegram_message(chat_id, f"🚫 User <code>{target_id}</code> has been banned.")
            except Exception:
                send_telegram_message(chat_id, "❌ Format: /ban <user_id>")
            return {"ok": True}
        elif text.startswith("/unban "):
            try:
                target_id = int(text.replace("/unban ", "").strip())
                users_col.update_one({"user_id": target_id}, {"$set": {"is_banned": False}}, upsert=True)
                send_telegram_message(chat_id, f"✅ User <code>{target_id}</code> has been unbanned.")
            except Exception:
                send_telegram_message(chat_id, "❌ Format: /unban <user_id>")
            return {"ok": True}
        elif text.startswith("/addtokens "):
            try:
                parts = text.replace("/addtokens ", "").strip().split()
                target_id = int(parts[0])
                amt = int(parts[1])
                users_col.update_one({"user_id": target_id}, {"$inc": {"tokens": amt}}, upsert=True)
                send_telegram_message(chat_id, f"🪙 Added {amt} tokens to User <code>{target_id}</code>.")
            except Exception:
                send_telegram_message(chat_id, "❌ Format: /addtokens <user_id> <amount>")
            return {"ok": True}
        elif text.startswith("/cuttokens "):
            try:
                parts = text.replace("/cuttokens ", "").strip().split()
                target_id = int(parts[0])
                amt = int(parts[1])
                users_col.update_one({"user_id": target_id}, {"$inc": {"tokens": -amt}}, upsert=True)
                send_telegram_message(chat_id, f"✂️ Cut {amt} tokens from User <code>{target_id}</code>.")
            except Exception:
                send_telegram_message(chat_id, "❌ Format: /cuttokens <user_id> <amount>")
            return {"ok": True}
        elif text.startswith("/start"):
            user = users_col.find_one({"user_id": int(user_id)})
            if not user:
                users_col.insert_one({"user_id": int(user_id), "tokens": 0, "earnings": 0, "avatar": "", "is_banned": False})
                send_telegram_message(GROUP_2_ID, f"👤 <b>New User Started Bot!</b>\nID: <code>{user_id}</code>")
            webapp_url = "https://vynora-bot.onrender.com/static/index.html"
            keyboard = {"inline_keyboard": [[{"text": "🚀 Open Vynora Live App", "web_app": {"url": webapp_url}}]]}
            send_telegram_message(chat_id, "✨ <b>Welcome to Vynora Live 1v1!</b>", reply_markup=keyboard)
    return {"ok": True}
