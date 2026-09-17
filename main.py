import os
import time
import uuid
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests
import razorpay  # <-- Razorpay imported
from agora_token_builder import RtcTokenBuilder
from database import users_col, hosts_col, bookings_col, recharges_col, withdrawals_col, chats_col

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
GROUP_1_ID = os.getenv("GROUP_1_ID", "-100XXXXXXXXXX") 
GROUP_2_ID = os.getenv("GROUP_2_ID", "-100XXXXXXXXXX") 
GROUP_3_ID = os.getenv("GROUP_3_ID", "-100XXXXXXXXXX") 

# Razorpay Keys (Render Environment Variables mein set karein)
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "YOUR_RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "YOUR_RAZORPAY_KEY_SECRET")

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

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
        return {"tokens": 0, "earnings": 0, "net_earnings_tokens": 0, "net_earnings_inr": 0, "avatar": "", "is_banned": True}
        
    if not user:
        user = {"user_id": int(user_id), "tokens": 0, "earnings": 0, "avatar": "", "is_banned": False}
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
        {"id": "dummy_1", "user_id": 9991, "name": "Sophia 💎", "age": 22, "rate": 40, "lang": "English", "loc": "UK", "img": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=400&auto=format&fit=crop", "bio": "International VIP Model ✨", "is_online": True, "is_dummy": True},
        {"id": "dummy_2", "user_id": 9992, "name": "Ananya 🔥", "age": 21, "rate": 50, "lang": "Hindi", "loc": "Mumbai", "img": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=400&auto=format&fit=crop", "bio": "Bollywood dancer & host 💃", "is_online": True, "is_dummy": True},
        {"id": "dummy_3", "user_id": 9993, "name": "Elena 👑", "age": 23, "rate": 60, "lang": "French", "loc": "France", "img": "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=400&auto=format&fit=crop", "bio": "Parisian fashion enthusiast 🌸", "is_online": True, "is_dummy": True},
        {"id": "dummy_4", "user_id": 9994, "name": "Natasha ✨", "age": 20, "rate": 45, "lang": "Russian", "loc": "Russia", "img": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400&auto=format&fit=crop", "bio": "Professional singer & artist 🎶", "is_online": True, "is_dummy": True},
        {"id": "dummy_5", "user_id": 9995, "name": "Priya 💫", "age": 22, "rate": 35, "lang": "Hindi", "loc": "Delhi", "img": "https://images.unsplash.com/photo-1529626455594-4ff0802cfb7e?w=400&auto=format&fit=crop", "bio": "Friendly companion & gamer 🎮", "is_online": True, "is_dummy": True}
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
    token = RtcTokenBuilder.buildTokenWithUid(
        AGORA_APP_ID, AGORA_APP_CERTIFICATE, channelName, int(uid), rtc_role, privilege_expired_ts
    )
    return {"status": "success", "token": token, "appId": AGORA_APP_ID, "channel": channelName, "uid": int(uid)}

# --- RAZORPAY ORDER CREATION ---
@app.post("/api/create-razorpay-order")
def create_razorpay_order(data: dict):
    amount_inr = int(data.get("amount_inr", 50))
    tokens_expected = amount_inr if amount_inr < 500 else amount_inr + 50
    amount_paise = amount_inr * 100  # Razorpay accepts amount in paise

    try:
        order_data = {
            "amount": amount_paise,
            "currency": "INR",
            "payment_capture": 1
        }
        order = razorpay_client.order.create(data=order_data)
        return {
            "status": "success",
            "order_id": order["id"],
            "amount": amount_paise,
            "key_id": RAZORPAY_KEY_ID,
            "tokens": tokens_expected
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- RAZORPAY PAYMENT VERIFICATION & TOKEN ADDING ---
@app.post("/api/verify-razorpay-payment")
def verify_razorpay_payment(data: dict):
    user_id = int(data.get("user_id"))
    tokens = int(data.get("tokens"))
    payment_id = data.get("payment_id")
    order_id = data.get("order_id")

    # Add tokens automatically to user account
    users_col.update_one({"user_id": user_id}, {"$inc": {"tokens": tokens}}, upsert=True)
    
    # Log recharge in recharges collection
    recharges_col.insert_one({
        "recharge_id": order_id,
        "user_id": user_id,
        "tokens_expected": tokens,
        "payment_id": payment_id,
        "status": "approved_razorpay"
    })

    # Send success notification to user & group 3
    send_telegram_message(user_id, f"🎉 <b>Recharge Successful!</b> +{tokens} Tokens added to your wallet automatically via Razorpay.")
    send_telegram_message(GROUP_3_ID, f"💳 <b>Razorpay Auto-Recharge Verified!</b>\nUser ID: <code>{user_id}</code>\nTokens Added: +{tokens}\nPayment ID: <code>{payment_id}</code>")

    return {"status": "success", "message": "Payment verified and tokens added!"}

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
        "call_started_at": current_time
    }
    bookings_col.insert_one(booking_doc)
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
        bookings_cursor = bookings_col.find({"host_id": {"$in": list(set(h_ids))}}).sort("time", -1)
        host_bookings = []
        for b in bookings_cursor:
            host_bookings.append({
                "booking_id": str(b.get("booking_id") or b.get("_id")),
                "user_id": b.get("user_id"),
                "host_id": b.get("host_id"),
                "host_name": b.get("host_name"),
                "duration_mins": b.get("duration_mins"),
                "token_cost": b.get("token_cost"),
                "channel_name": b.get("channel_name"),
                "status": b.get("status", "pending"),
                "call_started_at": b.get("call_started_at", b.get("time", time.time())),
                "formatted_time": time.strftime('%Y-%m-%d %H:%M', time.localtime(b.get("time", time.time())))
            })
        return {"bookings": host_bookings}
    except Exception:
        return {"bookings": []}

@app.post("/api/host/accept-booking")
def accept_booking(data: ActionBookingModel):
    booking = bookings_col.find_one({"booking_id": data.booking_id})
    if not booking or booking.get("status") != "pending":
        return {"status": "error", "message": "Booking not found"}
    current_time = time.time()
    bookings_col.update_one({"_id": booking["_id"]}, {"$set": {"status": "approved", "call_started_at": current_time}})
    return {"status": "success", "channel_name": booking.get("channel_name"), "call_started_at": current_time}

@app.post("/api/host/reject-booking")
def reject_booking(data: ActionBookingModel):
    booking = bookings_col.find_one({"booking_id": data.booking_id})
    if booking:
        bookings_col.update_one({"_id": booking["_id"]}, {"$set": {"status": "rejected"}})
        users_col.update_one({"user_id": int(booking["user_id"])}, {"$inc": {"tokens": booking["token_cost"]}})
    return {"status": "success"}

@app.post("/api/complete-booking")
def complete_booking(data: CompleteBookingModel):
    bookings_col.update_one({"booking_id": data.booking_id}, {"$set": {"status": "completed"}})
    return {"status": "success"}

@app.get("/api/user/bookings/{user_id}")
def get_user_bookings(user_id: int):
    cursor = bookings_col.find({"user_id": int(user_id)}, {"_id": 0}).sort("time", -1)
    return {"bookings": list(cursor)}

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
    send_telegram_message(GROUP_1_ID, f"📹 <b>New Host Application!</b>\nName: {data.name}\nID: <code>{data.user_id}</code>")
    return {"status": "success", "message": "Registered successfully!"}

@app.post("/api/withdraw")
def withdraw_earnings(data: WithdrawModel):
    host = hosts_col.find_one({"user_id": int(data.user_id), "status": "approved"})
    if not host:
        return {"status": "error", "message": "Only approved hosts can withdraw!"}
    users_col.update_one({"user_id": int(data.user_id)}, {"$inc": {"earnings": -int(data.tokens / 0.7)}})
    withdrawals_col.insert_one({"user_id": int(data.user_id), "upi_id": data.upi_id, "tokens": data.tokens, "status": "pending"})
    send_telegram_message(GROUP_3_ID, f"💸 <b>Withdrawal Request!</b> Host ID: <code>{data.user_id}</code> | Tokens: {data.tokens}")
    return {"status": "success", "message": "Withdrawal requested!"}

@app.post("/api/update-profile-photo")
async def update_profile_photo(user_id: int = Form(...), avatar: UploadFile = File(...)):
    os.makedirs("static/uploads", exist_ok=True)
    file_path = os.path.join("static/uploads", avatar.filename)
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
    chats_col.insert_one({"channel": data.channel, "sender": data.sender_name, "text": f"sent gift {data.gift_name} (🪙 {data.gift_cost})", "type": "gift", "time": time.time()})
    return {"status": "success"}

@app.post("/api/send-chat")
def send_chat(data: ChatModel):
    chats_col.insert_one({"channel": data.channel, "sender": data.sender, "text": data.text, "type": data.type, "time": time.time()})
    return {"status": "success"}

@app.get("/api/get-chat/{channel}")
def get_chat(channel: str):
    return {"messages": list(chats_col.find({"channel": channel}, {"_id": 0}).sort("time", 1).limit(50))}

@app.post("/telegram-webhook")
async def telegram_webhook(req: Request):
    body = await req.json()
    if "message" in body:
        msg = body["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        text = msg.get("text", "").strip()

        if text.startswith("/ban "):
            target_id = int(text.replace("/ban ", "").strip())
            users_col.update_one({"user_id": target_id}, {"$set": {"is_banned": True}}, upsert=True)
            send_telegram_message(chat_id, f"🚫 User <code>{target_id}</code> banned.")
            return {"ok": True}
        elif text.startswith("/unban "):
            target_id = int(text.replace("/unban ", "").strip())
            users_col.update_one({"user_id": target_id}, {"$set": {"is_banned": False}}, upsert=True)
            send_telegram_message(chat_id, f"✅ User <code>{target_id}</code> unbanned.")
            return {"ok": True}
        elif text.startswith("/addtokens "):
            parts = text.replace("/addtokens ", "").strip().split()
            users_col.update_one({"user_id": int(parts[0])}, {"$inc": {"tokens": int(parts[1])}}, upsert=True)
            send_telegram_message(chat_id, f"🪙 Added tokens.")
            return {"ok": True}
        elif text.startswith("/cuttokens "):
            parts = text.replace("/cuttokens ", "").strip().split()
            users_col.update_one({"user_id": int(parts[0])}, {"$inc": {"tokens": -int(parts[1])}}, upsert=True)
            send_telegram_message(chat_id, f"✂️ Deducted tokens.")
            return {"ok": True}
        elif text.startswith("/start"):
            user = users_col.find_one({"user_id": int(user_id)})
            if user and user.get("is_banned", False):
                send_telegram_message(chat_id, "🚫 Account suspended.")
                return {"ok": True}
            if not user:
                users_col.insert_one({"user_id": int(user_id), "tokens": 0, "earnings": 0, "avatar": "", "is_banned": False})
            webapp_url = "https://vynora-bot.onrender.com/static/index.html"
            send_telegram_message(chat_id, "✨ <b>Welcome to Vynora Live 1v1!</b>", reply_markup={"inline_keyboard": [[{"text": "🚀 Open Vynora Live App", "web_app": {"url": webapp_url}}]]})

    elif "callback_query" in body:
        callback = body["callback_query"]
        data_str = callback["data"]
        message_id = callback["message"]["message_id"]
        chat_id = callback["message"]["chat"]["id"]
        if data_str.startswith("approve_host_"):
            host_user_id = int(data_str.replace("approve_host_", ""))
            hosts_col.update_one({"user_id": host_user_id}, {"$set": {"status": "approved", "is_online": True}})
            send_telegram_message(host_user_id, "🎉 Host approved!")
            requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": "✅ Host Approved"})
        elif data_str.startswith("accept_bk_"):
            booking_id = data_str.replace("accept_bk_", "")
            booking = bookings_col.find_one({"booking_id": booking_id})
            if booking:
                bookings_col.update_one({"booking_id": booking_id}, {"$set": {"status": "approved", "call_started_at": time.time()}})
                send_telegram_message(int(booking["user_id"]), "📞 Call accepted! Open app to join.", reply_markup={"inline_keyboard": [[{"text": "📞 Answer Call", "web_app": {"url": "https://vynora-bot.onrender.com/static/index.html"}}]]})
                requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": "✅ Accepted"})

    return {"ok": True}
