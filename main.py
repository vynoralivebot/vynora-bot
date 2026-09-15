import os
import time
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import requests
from agora_token_builder import RtcTokenBuilder
from database import users_col, hosts_col, bookings_col, recharges_col, withdrawals_col, chats_col

app = FastAPI()

# Mount static files for frontend (index.html)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Telegram Bot Credentials
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
GROUP_1_ID = os.getenv("GROUP_1_ID", "-100XXXXXXXXXX") # Recharge & Host Approvals Group
GROUP_2_ID = os.getenv("GROUP_2_ID", "-100XXXXXXXXXX") # New Users Group
GROUP_3_ID = os.getenv("GROUP_3_ID", "-100XXXXXXXXXX") # Team / Withdrawals Group

AGORA_APP_ID = os.getenv("AGORA_APP_ID", "YOUR_AGORA_APP_ID")
AGORA_APP_CERTIFICATE = os.getenv("AGORA_APP_CERTIFICATE", "YOUR_AGORA_CERTIFICATE")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send_telegram_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
    except Exception as e:
        print("Telegram Error:", e)

# --- Pydantic Models ---
class HostRegisterModel(BaseModel):
    user_id: int
    name: str
    age: int
    rate: int
    lang: str
    loc: str
    img: str
    bio: str

class BookingModel(BaseModel):
    user_id: int
    host_id: str
    host_name: str
    duration_mins: int
    token_cost: int

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


# --- API Endpoints for Frontend ---

@app.get("/api/user/{user_id}")
def get_user(user_id: int):
    user = users_col.find_one({"user_id": user_id})
    if not user:
        user = {"user_id": user_id, "tokens": 100, "earnings": 0, "avatar": ""}
        users_col.insert_one(user)
        # Notify Group 2 about new user
        send_telegram_message(GROUP_2_ID, f"👤 <b>New User Started Bot!</b>\nID: <code>{user_id}</code>")
    return {"tokens": user.get("tokens", 100), "earnings": user.get("earnings", 0), "avatar": user.get("avatar", "")}

@app.get("/api/host/status/{user_id}")
def get_host_status(user_id: int):
    host = hosts_col.find_one({"user_id": user_id})
    if host:
        return {"is_host": True, "status": host.get("status", "pending")}
    return {"is_host": False, "status": "none"}

@app.get("/api/hosts")
def get_hosts():
    hosts = list(hosts_col.find({"status": "approved"}, {"_id": 0}))
    return {"hosts": hosts}

@app.get("/api/agora-token")
def get_agora_token(channelName: str, uid: int, role: str):
    privilege_expired_ts = int(time.time()) + 3600
    rtc_role = 1 if role == "publisher" else 2
    token = RtcTokenBuilder.buildTokenWithUid(
        AGORA_APP_ID, AGORA_APP_CERTIFICATE, channelName, uid, rtc_role, privilege_expired_ts
    )
    return {"status": "success", "token": token, "appId": AGORA_APP_ID, "channel": channelName, "uid": uid}

@app.post("/api/book-slot")
def book_slot(data: BookingModel):
    user = users_col.find_one({"user_id": data.user_id})
    if not user or user.get("tokens", 0) < data.token_cost:
        return {"status": "error", "message": "Insufficient tokens!"}

    # Deduct tokens from user
    users_col.update_one({"user_id": data.user_id}, {"$inc": {"tokens": -data.token_cost}})

    # Create booking request
    booking_id = str(int(time.time()))
    booking_doc = {
        "booking_id": booking_id,
        "user_id": data.user_id,
        "host_id": data.host_id,
        "host_name": data.host_name,
        "duration_mins": data.duration_mins,
        "token_cost": data.token_cost,
        "status": "pending"
    }
    bookings_col.insert_one(booking_doc)

    # Find host telegram id
    host = hosts_col.find_one({"id": data.host_id})
    if host and "user_id" in host:
        host_telegram_id = host["user_id"]
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ Accept Request", "callback_data": f"accept_bk_{booking_id}"},
                    {"text": "❌ Reject Request", "callback_data": f"reject_bk_{booking_id}"}
                ]
            ]
        }
        msg = f"🔔 <b>New Private Booking Request!</b>\n\n👤 User ID: <code>{data.user_id}</code>\n⏱️ Duration: {data.duration_mins} Mins\n🪙 Cost: {data.token_cost} Tokens"
        send_telegram_message(host_telegram_id, msg, reply_markup=keyboard)
        # Also notify Group 1
        send_telegram_message(GROUP_1_ID, f"📋 <b>Booking Created</b>\nHost: {data.host_name}\nUser: {data.user_id}\nCost: {data.token_cost} Tokens")

    return {"status": "success", "booking_id": booking_id}

@app.get("/api/host/bookings/{user_id}")
def get_host_bookings(user_id: int):
    host = hosts_col.find_one({"user_id": user_id})
    if not host:
        return {"bookings": []}
    host_bookings = list(bookings_col.find({"host_id": host["id"]}, {"_id": 0}))
    return {"bookings": host_bookings}

@app.post("/api/register-host")
def register_host(data: HostRegisterModel):
    host_data = data.dict()
    host_data["status"] = "approved" # Aap chahe toh 'pending' karke manual approve kar sakte hain
    host_data["id"] = f"h_{data.user_id}"
    hosts_col.update_one({"user_id": data.user_id}, {"$set": host_data}, upsert=True)
    
    # Notify Group 1
    send_telegram_message(GROUP_1_ID, f"📹 <b>New Host Registered!</b>\nName: {data.name}\nRate: {data.rate} Tokens/min\nID: <code>{data.user_id}</code>")
    return {"status": "success", "message": "Host registered successfully and approved!"}

@app.post("/api/recharge")
async def recharge(user_id: int = Form(...), amount_inr: int = Form(...), utr_number: str = Form(...), screenshot: UploadFile = File(...)):
    # Save recharge request in DB
    recharges_col.insert_one({
        "user_id": user_id,
        "amount_inr": amount_inr,
        "utr_number": utr_number,
        "status": "pending"
    })
    
    # Give tokens instantly or notify Group 1 for manual approval
    tokens_to_add = amount_inr if amount_inr < 500 else amount_inr + 50
    users_col.update_one({"user_id": user_id}, {"$inc": {"tokens": tokens_to_add}}, upsert=True)

    # Notify Group 1
    send_telegram_message(GROUP_1_ID, f"💳 <b>New Recharge Request!</b>\nUser ID: <code>{user_id}</code>\nAmount: ₹{amount_inr}\nUTR: <code>{utr_number}</code>\n✅ Added {tokens_to_add} Tokens automatically.")
    return {"status": "success", "message": f"Recharge submitted! {tokens_to_add} tokens added."}

@app.post("/api/withdraw")
def withdraw_earnings(data: WithdrawModel):
    user = users_col.find_one({"user_id": data.user_id})
    if not user or user.get("earnings", 0) < data.tokens:
        return {"status": "error", "message": "Insufficient earnings balance!"}

    # Deduct from earnings & log withdrawal
    users_col.update_one({"user_id": data.user_id}, {"$inc": {"earnings": -data.tokens}})
    withdrawals_col.insert_one({
        "user_id": data.user_id,
        "upi_id": data.upi_id,
        "tokens": data.tokens,
        "status": "pending"
    })

    # Notify Team Group 3
    send_telegram_message(GROUP_3_ID, f"💸 <b>New Withdrawal Request!</b>\n\n👤 Host ID: <code>{data.user_id}</code>\n🪙 Tokens: {data.tokens}\n📱 UPI ID: <code>{data.upi_id}</code>")
    return {"status": "success", "message": "Withdrawal request sent to team successfully!"}

@app.post("/api/send-gift")
def send_gift(data: GiftModel):
    user = users_col.find_one({"user_id": data.user_id})
    if not user or user.get("tokens", 0) < data.gift_cost:
        return {"status": "error", "message": "Not enough tokens"}

    # Deduct from user
    users_col.update_one({"user_id": data.user_id}, {"$inc": {"tokens": -data.gift_cost}})
    
    # Add to host earnings (Find host by host_id)
    host = hosts_col.find_one({"id": data.host_id})
    if host and "user_id" in host:
        users_col.update_one({"user_id": host["user_id"]}, {"$inc": {"earnings": data.gift_cost}}, upsert=True)

    # Log gift in chat
    chats_col.insert_one({
        "channel": data.channel,
        "sender": data.sender_name,
        "text": f"sent gift {data.gift_name} (🪙 {data.gift_cost})",
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


# --- Telegram Webhook for Inline Button Accept/Reject Actions ---
@app.post("/telegram-webhook")
async def telegram_webhook(req: Request):
    body = await req.json()
    if "callback_query" in body:
        callback = body["callback_query"]
        data_str = callback["data"]
        from_user = callback["from"]["id"]
        message_id = callback["message"]["message_id"]
        chat_id = callback["message"]["chat"]["id"]

        if data_str.startswith("accept_bk_"):
            booking_id = data_str.replace("accept_bk_", "")
            booking = bookings_col.find_one({"booking_id": booking_id})
            if booking:
                bookings_col.update_one({"booking_id": booking_id}, {"$set": {"status": "approved"}})
                user_id = booking["user_id"]
                # Notify User via Telegram
                send_telegram_message(user_id, "🎉 <b>Badhai ho!</b> Host ne aapki booking request accept kar li hai. Ab aap session join kar sakte hain!")
                requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": f"✅ Booking Approved Successfully for User {user_id}"
                })

        elif data_str.startswith("reject_bk_"):
            booking_id = data_str.replace("reject_bk_", "")
            booking = bookings_col.find_one({"booking_id": booking_id})
            if booking:
                bookings_col.update_one({"booking_id": booking_id}, {"$set": {"status": "rejected"}})
                user_id = booking["user_id"]
                token_cost = booking["token_cost"]
                # Refund tokens to user
                users_col.update_one({"user_id": user_id}, {"$inc": {"tokens": token_cost}})
                # Notify User
                send_telegram_message(user_id, f"❌ Aapki booking request host dwara reject kar di gayi hai. Aapke {token_cost} tokens refund kar diye gaye hain.")
                requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": f"❌ Booking Rejected. {token_cost} tokens refunded to user {user_id}."
                })

    return {"status": "ok"}
