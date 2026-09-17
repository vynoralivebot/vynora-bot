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

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send_telegram_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": int(chat_id), "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        res = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
        print("Telegram Response:", res.json())
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
        return {
            "tokens": 0,
            "earnings": 0,
            "net_earnings_tokens": 0,
            "net_earnings_inr": 0,
            "avatar": "",
            "is_banned": True
        }
    if not user:
        user = {
            "user_id": int(user_id),
            "tokens": 0,
            "earnings": 0,
            "avatar": "",
            "is_banned": False
        }
        users_col.insert_one(user)
        send_telegram_message(GROUP_2_ID, f"👤 <b>New User Started Bot!</b>\nID: <code>{user_id}</code>")
    
    raw_earnings = user.get("earnings", 0)
    net_earnings_tokens = int(raw_earnings * 0.7)
    net_earnings_inr = net_earnings_tokens
    return {
        "tokens": user.get("tokens", 0),
        "earnings": raw_earnings,
        "net_earnings_tokens": net_earnings_tokens,
        "net_earnings_inr": net_earnings_inr,
        "avatar": user.get("avatar", ""),
        "is_banned": False
    }

@app.get("/api/host/status/{user_id}")
def get_host_status(user_id: int):
    host = hosts_col.find_one({
        "$or": [
            {"user_id": int(user_id)},
            {"id": str(user_id)},
            {"id": f"h_{user_id}"},
            {"_id": f"host_{user_id}"}
        ]
    })
    if host:
        return {"is_host": True, "status": host.get("status", "pending"), "is_online": host.get("is_online", False)}
    return {"is_host": False, "status": "none", "is_online": False}

@app.post("/api/host/toggle-live/{user_id}")
def toggle_host_live(user_id: int):
    host = hosts_col.find_one({
        "$or": [
            {"user_id": int(user_id)},
            {"id": str(user_id)},
            {"id": f"h_{user_id}"},
            {"_id": f"host_{user_id}"}
        ]
    })
    if not host or host.get("status") != "approved":
        return {"status": "error", "message": "Host not found or not approved"}
    new_status = not host.get("is_online", False)
    hosts_col.update_one({"_id": host["_id"]}, {"$set": {"is_online": new_status}})
    return {"status": "success", "is_online": new_status}

@app.post("/api/host/update-rate")
def update_host_rate(data: UpdateRateModel):
    host = hosts_col.find_one({"user_id": int(data.user_id), "status": "approved"})
    if not host:
        return {"status": "error", "message": "Approved host not found"}
    hosts_col.update_one({"user_id": int(data.user_id)}, {"$set": {"rate": data.rate}})
    return {"status": "success", "message": "Call rate updated successfully!"}

@app.get("/api/hosts")
def get_hosts():
    db_hosts = list(hosts_col.find({"status": "approved"}, {"_id": 0}))
    dummy_hosts = [
        {"id": "dummy_1", "user_id": 9991, "name": "Sophia", "age": 22, "rate": 40, "lang": "English", "loc": "UK", "img": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=400&auto=format&fit=crop", "bio": "International VIP Model", "is_online": True, "is_dummy": True},
        {"id": "dummy_2", "user_id": 9992, "name": "Ananya", "age": 21, "rate": 50, "lang": "Hindi", "loc": "Mumbai", "img": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=400&auto=format&fit=crop", "bio": "Bollywood dancer & host", "is_online": True, "is_dummy": True},
        {"id": "dummy_3", "user_id": 9993, "name": "Elena", "age": 23, "rate": 60, "lang": "French", "loc": "France", "img": "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=400&auto=format&fit=crop", "bio": "Parisian fashion enthusiast", "is_online": True, "is_dummy": True},
        {"id": "dummy_4", "user_id": 9994, "name": "Natasha", "age": 20, "rate": 45, "lang": "Russian", "loc": "Russia", "img": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400&auto=format&fit=crop", "bio": "Professional singer & artist", "is_online": True, "is_dummy": True},
        {"id": "dummy_5", "user_id": 9995, "name": "Priya", "age": 22, "rate": 35, "lang": "Hindi", "loc": "Delhi", "img": "https://images.unsplash.com/photo-1529626455594-4ff0802cfb7e?w=400&auto=format&fit=crop", "bio": "Friendly companion & gamer", "is_online": True, "is_dummy": True}
    ]
    all_hosts = dummy_hosts + db_hosts
    for h in all_hosts:
        if not h.get("id"):
            h["id"] = f"h_{h.get('user_id')}"
    return {"hosts": all_hosts}

@app.get("/api/agora-token")
def get_agora_token(channelName: str, uid: int, role: str):
    privilege_expired_ts = int(time.time()) + 3600
    rtc_role = 1 if role == "publisher" else 2
    token = RtcTokenBuilder.buildTokenWithUid(AGORA_APP_ID, AGORA_APP_CERTIFICATE, channelName, int(uid), rtc_role, privilege_expired_ts)
    return {"status": "success", "token": token, "appId": AGORA_APP_ID, "channel": channelName, "uid": int(uid)}

@app.post("/api/book-slot")
def book_slot(data: BookingModel):
    if str(data.host_id).startswith("dummy_"):
        return {"status": "error", "message": "Host is currently busy in a private international session. Please try another host!"}
    
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
        "call_started_at": current_time
    }
    bookings_col.insert_one(booking_doc)
    
    host = hosts_col.find_one({
        "$or": [
            {"id": data.host_id},
            {"_id": f"host_{clean_host_id}"},
            {"user_id": int(clean_host_id) if clean_host_id.isdigit() else 0}
        ]
    })
    if host:
        host_telegram_id = host.get("user_id") or (int(clean_host_id) if clean_host_id.isdigit() else None)
        if host_telegram_id:
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "✅ Accept & Join", "callback_data": f"accept_bk_{booking_id}"},
                        {"text": "❌ Reject", "callback_data": f"reject_bk_{booking_id}"}
                    ]
                ]
            }
            msg = f"🔔 <b>New Private Booking Request!</b>\n\n👤 User ID: <code>{data.user_id}</code>\n⏱️ Duration: {data.duration_mins} Mins\n💎 Cost: {data.token_cost} Tokens"
            send_telegram_message(host_telegram_id, msg, reply_markup=keyboard)
            
    group_msg = f"📌 <b>New Booking Received!</b>\nHost: {data.host_name}\nUser ID: <code>{data.user_id}</code>\nDuration: {data.duration_mins} Mins\nTokens: {data.token_cost}"
    send_telegram_message(GROUP_1_ID, group_msg)
    send_telegram_message(GROUP_3_ID, group_msg)
    
    return {"status": "success", "booking_id": booking_id}

@app.get("/api/host/bookings/{user_id}")
def get_host_bookings(user_id: int):
    try:
        host = hosts_col.find_one({
            "$or": [
                {"user_id": int(user_id)},
                {"id": str(user_id)},
                {"id": f"h_{user_id}"},
                {"_id": f"host_{user_id}"}
            ]
        })
        if not host:
            return {"bookings": []}
        
        h_ids = [str(user_id), f"h_{user_id}", f"host_{user_id}"]
        if host.get("id"):
            h_ids.append(str(host.get("id")))
        if host.get("user_id"):
            h_ids.append(str(host.get("user_id")))
            h_ids.append(f"h_{host.get('user_id')}")
            
        now = time.time()
        all_host_bookings = list(bookings_col.find({"host_id": {"$in": list(set(h_ids))}}))
        
        for b in all_host_bookings:
            start_time = b.get("time") or 0
            if b.get("status") == "pending" and start_time > 0 and (now - start_time) > 600:
                bookings_col.update_one({"_id": b["_id"]}, {"$set": {"status": "expired"}})
                users_col.update_one({"user_id": int(b["user_id"])}, {"$inc": {"tokens": b["token_cost"]}})
                send_telegram_message(int(b["user_id"]), f"⚠️ Booking expired. Host did not accept within 10 minutes. {b['token_cost']} tokens refunded.")
                host_tg_id = host.get("user_id") or (int(user_id) if str(user_id).isdigit() else None)
                if host_tg_id:
                    send_telegram_message(host_tg_id, f"⚠️ Booking request from User {b['user_id']} expired because you didn't accept it within 10 minutes.")
            elif b.get("status") == "approved":
                duration_secs = b.get("duration_mins", 1) * 60
                call_start = b.get("call_started_at", start_time)
                if call_start == 0 or now > (call_start + duration_secs + 120):
                    bookings_col.update_one({"_id": b["_id"]}, {"$set": {"status": "completed"}})
                    
        bookings_cursor = bookings_col.find({"host_id": {"$in": list(set(h_ids))}}).sort("time", -1)
        host_bookings = []
        for b in bookings_cursor:
            b_id = str(b.get("booking_id") or b.get("_id"))
            call_time_formatted = time.strftime('%Y-%m-%d %H:%M', time.localtime(b.get("time", time.time())))
            host_bookings.append({
                "booking_id": b_id,
                "user_id": b.get("user_id"),
                "host_id": b.get("host_id"),
                "host_name": b.get("host_name"),
                "duration_mins": b.get("duration_mins"),
                "token_cost": b.get("token_cost"),
                "channel_name": b.get("channel_name", f"private_call_{user_id}_{b.get('user_id')}"),
                "status": b.get("status", "pending"),
                "call_started_at": b.get("call_started_at", b.get("time", time.time())),
                "formatted_time": call_time_formatted,
                "time": b.get("time", 0)
            })
        return {"bookings": host_bookings}
    except Exception as e:
        print("Error in host bookings:", str(e))
        return {"bookings": []}

@app.post("/api/host/accept-booking")
def accept_booking(data: ActionBookingModel):
    booking = bookings_col.find_one({
        "$or": [
            {"booking_id": data.booking_id},
            {"_id": data.booking_id}
        ]
    })
    if not booking or booking.get("status") != "pending":
        return {"status": "error", "message": "Booking not found or already processed"}
    
    current_time = time.time()
    bookings_col.update_one({"_id": booking["_id"]}, {"$set": {"status": "approved", "call_started_at": current_time}})
    
    h_val = str(booking["host_id"])
    clean_h = h_val.replace("h_", "").replace("host_", "")
    host = hosts_col.find_one({
        "$or": [
            {"id": h_val},
            {"_id": f"host_{clean_h}"},
            {"user_id": int(clean_h) if clean_h.isdigit() else 0}
        ]
    })
    if host and "user_id" in host:
        users_col.update_one({"user_id": int(host["user_id"])}, {"$inc": {"earnings": booking["token_cost"]}}, upsert=True)
        
    webapp_url = "https://vynora-bot.onrender.com/static/index.html"
    user_keyboard = {"inline_keyboard": [[{"text": "📞 Answer Call", "web_app": {"url": webapp_url}}]]}
    send_telegram_message(int(booking["user_id"]), f"📹 <b>Incoming Video Call!</b> Host accepted your booking. Tap below to pick up.", reply_markup=user_keyboard)
    return {"status": "success", "message": "Booking accepted successfully!", "channel_name": booking.get("channel_name"), "call_started_at": current_time}

@app.post("/api/host/reject-booking")
def reject_booking(data: ActionBookingModel):
    booking = bookings_col.find_one({
        "$or": [
            {"booking_id": data.booking_id},
            {"_id": data.booking_id}
        ]
    })
    if not booking:
        return {"status": "error", "message": "Booking not found"}
    
    bookings_col.update_one({"_id": booking["_id"]}, {"$set": {"status": "rejected"}})
    users_col.update_one({"user_id": int(booking["user_id"])}, {"$inc": {"tokens": booking["token_cost"]}})
    send_telegram_message(int(booking["user_id"]), f"❌ Booking rejected. {booking['token_cost']} tokens refunded.")
    return {"status": "success", "message": "Booking rejected and tokens refunded!"}

@app.post("/api/complete-booking")
def complete_booking(data: CompleteBookingModel):
    booking = bookings_col.find_one({
        "$or": [
            {"booking_id": data.booking_id},
            {"_id": data.booking_id}
        ]
    })
    if booking:
        bookings_col.update_one({"_id": booking["_id"]}, {"$set": {"status": "completed"}})
        return {"status": "success", "message": "Booking marked as completed"}
    return {"status": "error", "message": "Booking not found"}

@app.get("/api/user/bookings/{user_id}")
def get_user_bookings(user_id: int):
    try:
        now = time.time()
        user_raw_bookings = list(bookings_col.find({"user_id": int(user_id)}))
        for b in user_raw_bookings:
            start_time = b.get("time") or 0
            if b.get("status") == "pending" and start_time > 0 and (now - start_time) > 600:
                bookings_col.update_one({"_id": b["_id"]}, {"$set": {"status": "expired"}})
                users_col.update_one({"user_id": int(b["user_id"])}, {"$inc": {"tokens": b["token_cost"]}})
            elif b.get("status") == "approved":
                duration_secs = b.get("duration_mins", 1) * 60
                call_start = b.get("call_started_at", start_time)
                if call_start == 0 or now > (call_start + duration_secs + 120):
                    bookings_col.update_one({"_id": b["_id"]}, {"$set": {"status": "completed"}})
                    
        user_bookings_cursor = bookings_col.find({"user_id": int(user_id)}, {"_id": 0}).sort("time", -1)
        user_bookings = []
        for b in user_bookings_cursor:
            call_time_formatted = time.strftime('%Y-%m-%d %H:%M', time.localtime(b.get("time", time.time())))
            h_val = str(b.get("host_id"))
            clean_h = h_val.replace("h_", "").replace("host_", "")
            host = hosts_col.find_one({
                "$or": [
                    {"id": h_val},
                    {"_id": f"host_{clean_h}"},
                    {"user_id": int(clean_h) if clean_h.isdigit() else 0}
                ]
            })
            if host:
                b["host_user_id"] = host.get("user_id") or (int(clean_h) if clean_h.isdigit() else 0)
                b["host_img"] = host.get("img")
            if not b.get("channel_name"):
                b["channel_name"] = f"private_call_{clean_h}_{user_id}"
            b["call_started_at"] = b.get("call_started_at", b.get("time", time.time()))
            b["formatted_time"] = call_time_formatted
            user_bookings.append(b)
        return {"bookings": user_bookings}
    except Exception as e:
        print("Error in user bookings:", str(e))
        return {"bookings": []}

@app.post("/api/register-host")
def register_host(data: HostRegisterModel):
    host_data = data.dict()
    host_data["status"] = "pending"
    host_data["id"] = f"h_{data.user_id}"
    host_data["_id"] = f"host_{data.user_id}"
    host_data["user_id"] = int(data.user_id)
    host_data["is_online"] = False
    host_data["img"] = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400&auto=format&fit=crop"
    
    hosts_col.update_one({"user_id": int(data.user_id)}, {"$set": host_data}, upsert=True)
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve Host", "callback_data": f"approve_host_{data.user_id}"},
                {"text": "❌ Reject Host", "callback_data": f"reject_host_{data.user_id}"}
            ]
        ]
    }
    send_telegram_message(GROUP_1_ID, f"⭐ <b>New Host Application!</b>\nName: {data.name}\nAge: {data.age}\nRate: {data.rate} Tokens/min\nID: <code>{data.user_id}</code>", reply_markup=keyboard)
    return {"status": "success", "message": "Host registered successfully! Waiting for admin approval."}

@app.post("/api/recharge")
async def recharge(user_id: int = Form(...), amount_inr: int = Form(...), utr_number: str = Form(...), screenshot: UploadFile = File(...)):
    tokens_expected = amount_inr if amount_inr < 500 else amount_inr + 50
    recharge_id = str(int(time.time()))
    recharges_col.insert_one({
        "recharge_id": recharge_id,
        "user_id": int(user_id),
        "amount_inr": amount_inr,
        "tokens_expected": tokens_expected,
        "utr_number": utr_number,
        "status": "pending"
    })
    keyboard = {
        "inline_keyboard": [
            [
                {"text": f"✅ Approve (+{tokens_expected})", "callback_data": f"approve_rc_{recharge_id}"},
                {"text": "❌ Reject", "callback_data": f"reject_rc_{recharge_id}"}
            ]
        ]
    }
    send_telegram_message(GROUP_1_ID, f"💳 <b>New Recharge Request!</b>\nUser ID: <code>{user_id}</code>\nAmount: {amount_inr}\nUTR: <code>{utr_number}</code>", reply_markup=keyboard)
    return {"status": "success", "message": "Recharge submitted! Waiting for admin approval."}

@app.post("/api/withdraw")
def withdraw_earnings(data: WithdrawModel):
    host = hosts_col.find_one({"user_id": int(data.user_id), "status": "approved"})
    if not host:
        return {"status": "error", "message": "Withdrawal option is only available for approved hosts!"}
    
    user = users_col.find_one({"user_id": int(data.user_id)})
    net_earnings = int(user.get("earnings", 0) * 0.7)
    if not user or net_earnings < data.tokens:
        return {"status": "error", "message": "Insufficient net earnings balance (after 30% fee)!"}
    
    users_col.update_one({"user_id": int(data.user_id)}, {"$inc": {"earnings": -int(data.tokens / 0.7)}})
    withdrawals_col.insert_one({
        "user_id": int(data.user_id),
        "upi_id": data.upi_id,
        "tokens": data.tokens,
        "status": "pending"
    })
    send_telegram_message(GROUP_3_ID, f"🏦 <b>New Withdrawal Request!</b>\nHost ID: <code>{data.user_id}</code>\nTokens: {data.tokens}\nUPI: <code>{data.upi_id}</code>")
    return {"status": "success", "message": "Withdrawal request sent successfully!"}

@app.post("/api/update-profile-photo")
async def update_profile_photo(user_id: int = Form(...), avatar: UploadFile = File(...)):
    upload_dir = "static/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, avatar.filename)
    with open(file_path, "wb") as buffer:
        buffer.write(await avatar.read())
    avatar_url = f"https://vynora-bot.onrender.com/static/uploads/{avatar.filename}"
    users_col.update_one({"user_id": int(user_id)}, {"$set": {"avatar": avatar_url}}, upsert=True)
    hosts_col.update_one({"user_id": int(user_id)}, {"$set": {"img": avatar_url}}, upsert=True)
    return {"status": "success", "avatar_url": avatar_url}

@app.post("/api/send-gift")
def send_gift(data: GiftModel):
    user = users_col.find_one({"user_id": int(data.user_id)})
    if not user or user.get("tokens", 0) < data.gift_cost:
        return {"status": "error", "message": "Not enough tokens"}
    
    users_col.update_one({"user_id": int(data.user_id)}, {"$inc": {"tokens": -data.gift_cost}})
    clean_h = str(data.host_id).replace("h_", "").replace("host_", "")
    host = hosts_col.find_one({
        "$or": [
            {"id": data.host_id},
            {"_id": f"host_{clean_h}"},
            {"user_id": int(clean_h) if clean_h.isdigit() else 0}
        ]
    })
    if host and "user_id" in host:
        users_col.update_one({"user_id": int(host["user_id"])}, {"$inc": {"earnings": data.gift_cost}}, upsert=True)
        
    chats_col.insert_one({
        "channel": data.channel,
        "sender": data.sender_name,
        "text": f"sent gift 🎁 {data.gift_name} ({data.gift_cost} 💎)",
        "type": "gift",
        "time": time.time()
    })
    return {"status": "success"}

@app.post("/api/send-chat")
def send_chat(data: ChatModel):
    chats_col.insert_one({
        "channel": data.channel,
        "sender": data.sender,
        "text": data.text,
        "type": data.type,
        "time": time.time()
    })
    return {"status": "success"}

@app.get("/api/get-chat/{channel}")
def get_chat(channel: str):
    messages = list(chats_col.find({"channel": channel}, {"_id": 0}).sort("time", 1).limit(50))
    return {"messages": messages}

@app.post("/telegram-webhook")
async def telegram_webhook(req: Request):
    body = await req.json()
    if "message" in body:
        msg = body["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        text = msg.get("text", "").strip()
        
        if text.startswith("/ban "):
            try:
                target_id = int(text.replace("/ban ", "").strip())
                users_col.update_one({"user_id": target_id}, {"$set": {"is_banned": True}}, upsert=True)
                send_telegram_message(chat_id, f"🔨 User <code>{target_id}</code> has been banned successfully.")
            except Exception as e:
                send_telegram_message(chat_id, "⚠️ Error. Format: /ban <user_id>")
            return {"ok": True}
        elif text.startswith("/unban "):
            try:
                target_id = int(text.replace("/unban ", "").strip())
                users_col.update_one({"user_id": target_id}, {"$set": {"is_banned": False}}, upsert=True)
                send_telegram_message(chat_id, f"🔓 User <code>{target_id}</code> has been unbanned.")
            except Exception as e:
                send_telegram_message(chat_id, "⚠️ Error. Format: /unban <user_id>")
            return {"ok": True}
        elif text.startswith("/addtokens "):
            try:
                parts = text.replace("/addtokens ", "").strip().split()
                target_id = int(parts[0])
                amt = int(parts[1])
                users_col.update_one({"user_id": target_id}, {"$inc": {"tokens": amt}}, upsert=True)
                send_telegram_message(chat_id, f"💎 Added {amt} tokens to User <code>{target_id}</code>.")
                send_telegram_message(target_id, f"🎁 Admin added +{amt} Tokens to your wallet!")
            except Exception as e:
                send_telegram_message(chat_id, "⚠️ Error. Format: /addtokens <user_id> <amount>")
            return {"ok": True}
        elif text.startswith("/cuttokens "):
            try:
                parts = text.replace("/cuttokens ", "").strip().split()
                target_id = int(parts[0])
                amt = int(parts[1])
                users_col.update_one({"user_id": target_id}, {"$inc": {"tokens": -amt}}, upsert=True)
                send_telegram_message(chat_id, f"🔻 Cut {amt} tokens from User <code>{target_id}</code>.")
                send_telegram_message(target_id, f"⚠️ Admin deducted {amt} Tokens from your wallet.")
            except Exception as e:
                send_telegram_message(chat_id, "⚠️ Error. Format: /cuttokens <user_id> <amount>")
            return {"ok": True}
        elif text.startswith("/userinfo "):
            try:
                target_id = int(text.replace("/userinfo ", "").strip())
                user = users_col.find_one({"user_id": target_id})
                host = hosts_col.find_one({"user_id": target_id})
                if user:
                    msg = (f"👤 <b>User Data & Info:</b>\n\n"
                           f"🆔 ID: <code>{target_id}</code>\n"
                           f"💎 Tokens: {user.get('tokens', 0)}\n"
                           f"💰 Earnings: {user.get('earnings', 0)}\n"
                           f"🚫 Banned: {user.get('is_banned', False)}\n"
                           f"🎙️ Host Status: {host.get('status', 'None') if host else 'Not a Host'}")
                else:
                    msg = f"❌ User ID <code>{target_id}</code> database mein nahi mila!"
                send_telegram_message(chat_id, msg)
            except Exception as e:
                send_telegram_message(chat_id, "⚠️ Format: /userinfo <user_id>")
            return {"ok": True}
        elif text.startswith("/hostinfo "):
            try:
                target_id = int(text.replace("/hostinfo ", "").strip())
                host = hosts_col.find_one({
                    "$or": [
                        {"user_id": target_id},
                        {"id": str(target_id)},
                        {"id": f"h_{target_id}"},
                        {"_id": f"host_{target_id}"}
                    ]
                })
                user = users_col.find_one({"user_id": target_id})
                if host:
                    raw_earnings = user.get("earnings", 0) if user else 0
                    net_payout = int(raw_earnings * 0.7)
                    msg = (f"⭐ <b>Host Profile & Status Info:</b>\n\n"
                           f"🆔 ID: <code>{target_id}</code>\n"
                           f"👤 Name: {host.get('name', 'N/A')}\n"
                           f"📌 Status: <b>{str(host.get('status', 'pending')).upper()}</b>\n"
                           f"🟢 Live Online: {host.get('is_online', False)}\n"
                           f"💎 Call Rate: {host.get('rate', 50)} Tokens/min\n"
                           f"💰 Total Earnings: {raw_earnings} Tokens\n"
                           f"🏦 Net Payout (70%): {net_payout}")
                else:
                    msg = f"❌ Host ID <code>{target_id}</code> approved ya registered nahi mila!"
                send_telegram_message(chat_id, msg)
            except Exception as e:
                send_telegram_message(chat_id, "⚠️ Format: /hostinfo <user_id>")
            return {"ok": True}
        
        if text.startswith("/start"):
            user = users_col.find_one({"user_id": int(user_id)})
            if user and user.get("is_banned", False):
                send_telegram_message(chat_id, "🚫 Your account has been suspended by the admin.")
                return {"ok": True}
            if not user:
                users_col.insert_one({"user_id": int(user_id), "tokens": 0, "earnings": 0, "avatar": "", "is_banned": False})
                send_telegram_message(GROUP_2_ID, f"👤 <b>New User Started Bot!</b>\nID: <code>{user_id}</code>")
            
            webapp_url = "https://vynora-bot.onrender.com/static/index.html"
            keyboard = {"inline_keyboard": [[{"text": "🚀 Open Vynora Live App", "web_app": {"url": webapp_url}}]]}
            send_telegram_message(chat_id, "✨ <b>Welcome to Vynora Live 1v1!</b>", reply_markup=keyboard)
            
    elif "callback_query" in body:
        callback = body["callback_query"]
        data_str = callback["data"]
        message_id = callback["message"]["message_id"]
        chat_id = callback["message"]["chat"]["id"]
        
        if data_str.startswith("approve_host_"):
            host_user_id = int(data_str.replace("approve_host_", ""))
            hosts_col.update_one({"user_id": host_user_id}, {"$set": {"status": "approved", "is_online": True}})
            send_telegram_message(host_user_id, "🎉 <b>Congratulations!</b> Your host application has been approved by the admin.")
            send_telegram_message(GROUP_3_ID, f"✅ <b>Host Approved!</b> Host ID: <code>{host_user_id}</code> is now active.")
            requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": "✅ Host Approved Successfully"})
        elif data_str.startswith("reject_host_"):
            host_user_id = int(data_str.replace("reject_host_", ""))
            hosts_col.update_one({"user_id": host_user_id}, {"$set": {"status": "rejected"}})
            send_telegram_message(host_user_id, "❌ Your host application was rejected by the admin.")
            requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": "❌ Host Application Rejected"})
        elif data_str.startswith("approve_rc_"):
            recharge_id = data_str.replace("approve_rc_", "")
            rc = recharges_col.find_one({"recharge_id": recharge_id})
            if rc and rc["status"] == "pending":
                recharges_col.update_one({"recharge_id": recharge_id}, {"$set": {"status": "approved"}})
                u_id = int(rc["user_id"])
                tokens = rc["tokens_expected"]
                users_col.update_one({"user_id": u_id}, {"$inc": {"tokens": tokens}}, upsert=True)
                send_telegram_message(u_id, f"✅ <b>Recharge Approved!</b> +{tokens} Tokens added.")
                send_telegram_message(GROUP_3_ID, f"✅ <b>Recharge Approved & Verified!</b>\nUser ID: <code>{u_id}</code>\nAmount: {rc.get('amount_inr')}\nTokens: +{tokens}\nUTR: <code>{rc.get('utr_number')}</code>")
                requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": "✅ Recharge Approved Successfully"})
        elif data_str.startswith("reject_rc_"):
            recharge_id = data_str.replace("reject_rc_", "")
            recharges_col.update_one({"recharge_id": recharge_id}, {"$set": {"status": "rejected"}})
            requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": "❌ Recharge Rejected"})
        elif data_str.startswith("accept_bk_"):
            booking_id = data_str.replace("accept_bk_", "")
            booking = bookings_col.find_one({"booking_id": booking_id})
            if booking and booking.get("status") == "pending":
                current_time = time.time()
                bookings_col.update_one({"booking_id": booking_id}, {"$set": {"status": "approved", "call_started_at": current_time}})
                h_val = str(booking["host_id"])
                clean_h = h_val.replace("h_", "").replace("host_", "")
                host = hosts_col.find_one({
                    "$or": [
                        {"id": h_val},
                        {"_id": f"host_{clean_h}"},
                        {"user_id": int(clean_h) if clean_h.isdigit() else 0}
                    ]
                })
                if host and "user_id" in host:
                    users_col.update_one({"user_id": int(host["user_id"])}, {"$inc": {"earnings": booking["token_cost"]}}, upsert=True)
                webapp_url = "https://vynora-bot.onrender.com/static/index.html"
                user_keyboard = {"inline_keyboard": [[{"text": "📞 Answer Call", "web_app": {"url": webapp_url}}]]}
                send_telegram_message(int(booking["user_id"]), f"📹 <b>Incoming Video Call!</b> Host accepted your booking. Tap below to pick up.", reply_markup=user_keyboard)
                requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": "☑ Booking Accepted & Call Ready"})
        elif data_str.startswith("reject_bk_"):
            booking_id = data_str.replace("reject_bk_", "")
            booking = bookings_col.find_one({"booking_id": booking_id})
            if booking:
                bookings_col.update_one({"booking_id": booking_id}, {"$set": {"status": "rejected"}})
                users_col.update_one({"user_id": int(booking["user_id"])}, {"$inc": {"tokens": booking["token_cost"]}})
                send_telegram_message(int(booking["user_id"]), f"❌ Booking rejected. {booking['token_cost']} tokens refunded.")
                requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": "❌ Booking Rejected"})
    return {"ok": True}
