import os
import time
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests
from agora_token_builder import RtcTokenBuilder
from database import users_col, hosts_col, bookings_col, recharges_col, withdrawals_col, chats_col

app = FastAPI()

# Mount static files for frontend (index.html)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Telegram Bot Credentials & Group IDs
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

# --- Automatic Webhook Setup on Startup ---
@app.on_event("startup")
def set_webhook_on_startup():
    render_url = "https://vynora-bot.onrender.com/telegram-webhook"
    webhook_api = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={render_url}"
    try:
        requests.get(webhook_api)
    except Exception as e:
        print("Webhook setup error:", e)

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


# --- API Endpoints ---

@app.get("/api/user/{user_id}")
def get_user(user_id: int):
    user = users_col.find_one({"user_id": user_id})
    if not user:
        user = {"user_id": user_id, "tokens": 100, "earnings": 0, "avatar": ""}
        users_col.insert_one(user)
        send_telegram_message(GROUP_2_ID, f"👤 <b>New User Started Bot!</b>\nID: <code>{user_id}</code>")
    return {"tokens": user.get("tokens", 100), "earnings": user.get("earnings", 0), "avatar": user.get("avatar", "")}

@app.get("/api/host/status/{user_id}")
def get_host_status(user_id: int):
    host = hosts_col.find_one({"user_id": user_id})
    if host:
        return {"is_host": True, "status": host.get("status", "pending"), "is_online": host.get("is_online", False)}
    return {"is_host": False, "status": "none", "is_online": False}

@app.post("/api/host/toggle-live/{user_id}")
def toggle_host_live(user_id: int):
    host = hosts_col.find_one({"user_id": user_id})
    if not host:
        return {"status": "error", "message": "Host not found"}
    current_status = host.get("is_online", False)
    new_status = not current_status
    hosts_col.update_one({"user_id": user_id}, {"$set": {"is_online": new_status}})
    return {"status": "success", "is_online": new_status}

@app.get("/api/hosts")
def get_hosts():
    # Returns approved hosts (can filter by online status if needed)
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
        return {"status": "error", "message": f"Insufficient tokens! You need {data.token_cost} tokens."}

    # Deduct tokens immediately on booking request
    users_col.update_one({"user_id": data.user_id}, {"$inc": {"tokens": -data.token_cost}})

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

    # Notify Host with Accept/Reject buttons
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
        msg = f"🔔 <b>New Private Slot Booking Request!</b>\n\n👤 User ID: <code>{data.user_id}</code>\n⏱️ Duration: {data.duration_mins} Mins\n🪙 Cost: {data.token_cost} Tokens"
        send_telegram_message(host_telegram_id, msg, reply_markup=keyboard)
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
    host_data["status"] = "approved"
    host_data["id"] = f"h_{data.user_id}"
    host_data["is_online"] = True
    hosts_col.update_one({"user_id": data.user_id}, {"$set": host_data}, upsert=True)
    
    send_telegram_message(GROUP_1_ID, f"📹 <b>New Host Registered!</b>\nName: {data.name}\nRate: {data.rate} Tokens/min\nID: <code>{data.user_id}</code>")
    return {"status": "success", "message": "Host registered successfully and approved!"}

@app.post("/api/recharge")
async def recharge(user_id: int = Form(...), amount_inr: int = Form(...), utr_number: str = Form(...), screenshot: UploadFile = File(...)):
    # FIXED: Do NOT add tokens automatically. Keep status pending until approved in Group 1.
    tokens_expected = amount_inr if amount_inr < 500 else amount_inr + 50
    recharge_id = str(int(time.time()))
    
    recharges_col.insert_one({
        "recharge_id": recharge_id,
        "user_id": user_id,
        "amount_inr": amount_inr,
        "tokens_expected": tokens_expected,
        "utr_number": utr_number,
        "status": "pending"
    })

    # Send Notification to Group 1 with Admin Approval Buttons
    keyboard = {
        "inline_keyboard": [
            [
                {"text": f"✅ Approve (+{tokens_expected} Tokens)", "callback_data": f"approve_rc_{recharge_id}"},
                {"text": "❌ Reject", "callback_data": f"reject_rc_{recharge_id}"}
            ]
        ]
    }
    send_telegram_message(
        GROUP_1_ID, 
        f"💳 <b>New Recharge Request (Pending Approval)!</b>\nUser ID: <code>{user_id}</code>\nAmount: ₹{amount_inr}\nUTR: <code>{utr_number}</code>", 
        reply_markup=keyboard
    )
    
    return {"status": "success", "message": "Recharge submitted successfully! Waiting for admin approval."}

@app.post("/api/withdraw")
def withdraw_earnings(data: WithdrawModel):
    user = users_col.find_one({"user_id": data.user_id})
    if not user or user.get("earnings", 0) < data.tokens:
        return {"status": "error", "message": "Insufficient earnings balance!"}

    users_col.update_one({"user_id": data.user_id}, {"$inc": {"earnings": -data.tokens}})
    withdrawals_col.insert_one({
        "user_id": data.user_id,
        "upi_id": data.upi_id,
        "tokens": data.tokens,
        "status": "pending"
    })

    send_telegram_message(GROUP_3_ID, f"💸 <b>New Withdrawal Request!</b>\n\n👤 Host ID: <code>{data.user_id}</code>\n🪙 Tokens: {data.tokens}\n📱 UPI ID: <code>{data.upi_id}</code>")
    return {"status": "success", "message": "Withdrawal request sent to team successfully!"}

@app.post("/api/update-profile-photo")
async def update_profile_photo(user_id: int = Form(...), avatar: UploadFile = File(...)):
    # Simple direct handling: save file URL or simulate avatar update
    avatar_url = f"https://vynora-bot.onrender.com/static/uploads/{avatar.filename}"
    users_col.update_one({"user_id": user_id}, {"$set": {"avatar": avatar_url}}, upsert=True)
    hosts_col.update_one({"user_id": user_id}, {"$set": {"img": avatar_url}}, upsert=True)
    return {"status": "success", "avatar_url": avatar_url}

@app.post("/api/send-gift")
def send_gift(data: GiftModel):
    user = users_col.find_one({"user_id": data.user_id})
    if not user or user.get("tokens", 0) < data.gift_cost:
        return {"status": "error", "message": "Not enough tokens"}

    users_col.update_one({"user_id": data.user_id}, {"$inc": {"tokens": -data.gift_cost}})
    
    host = hosts_col.find_one({"id": data.host_id})
    if host and "user_id" in host:
        users_col.update_one({"user_id": host["user_id"]}, {"$inc": {"earnings": data.gift_cost}}, upsert=True)

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


# --- Telegram Webhook for Actions & Approvals ---
@app.post("/telegram-webhook")
async def telegram_webhook(req: Request):
    body = await req.json()
    
    if "message" in body:
        msg = body["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        text = msg.get("text", "")
        
        if text.startswith("/start"):
            user = users_col.find_one({"user_id": user_id})
            if not user:
                users_col.insert_one({"user_id": user_id, "tokens": 100, "earnings": 0, "avatar": ""})
                send_telegram_message(GROUP_2_ID, f"👤 <b>New User Started Bot!</b>\nID: <code>{user_id}</code>")
            
            webapp_url = "https://vynora-bot.onrender.com/static/index.html"
            keyboard = {
                "inline_keyboard": [
                    [{"text": "🚀 Open Vynora Live App", "web_app": {"url": webapp_url}}]
                ]
            }
            send_telegram_message(chat_id, "✨ <b>Welcome to Vynora Live 1v1!</b>\n\nConnect with verified hosts and book private slots.", reply_markup=keyboard)

    elif "callback_query" in body:
        callback = body["callback_query"]
        data_str = callback["data"]
        message_id = callback["message"]["message_id"]
        chat_id = callback["message"]["chat"]["id"]

        # 1. Recharge Approvals in Group 1
        if data_str.startswith("approve_rc_"):
            recharge_id = data_str.replace("approve_rc_", "")
            rc = recharges_col.find_one({"recharge_id": recharge_id})
            if rc and rc["status"] == "pending":
                recharges_col.update_one({"recharge_id": recharge_id}, {"$set": {"status": "approved"}})
                u_id = rc["user_id"]
                tokens = rc["tokens_expected"]
                users_col.update_one({"user_id": u_id}, {"$inc": {"tokens": tokens}}, upsert=True)
                send_telegram_message(u_id, f"🎉 <b>Recharge Approved!</b> Aapke account me {tokens} tokens add kar diye gaye hain.")
                requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={
                    "chat_id": chat_id, "message_id": message_id, "text": f"✅ Recharge Approved. Added {tokens} tokens to user {u_id}."
                })

        elif data_str.startswith("reject_rc_"):
            recharge_id = data_str.replace("reject_rc_", "")
            recharges_col.update_one({"recharge_id": recharge_id}, {"$set": {"status": "rejected"}})
            requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={
                "chat_id": chat_id, "message_id": message_id, "text": f"❌ Recharge Request Rejected."
            })

        # 2. Host Booking Approvals
        elif data_str.startswith("accept_bk_"):
            booking_id = data_str.replace("accept_bk_", "")
            booking = bookings_col.find_one({"booking_id": booking_id})
            if booking:
                bookings_col.update_one({"booking_id": booking_id}, {"$set": {"status": "approved"}})
                # Add earnings to host
                host = hosts_col.find_one({"id": booking["host_id"]})
                if host and "user_id" in host:
                    users_col.update_one({"user_id": host["user_id"]}, {"$inc": {"earnings": booking["token_cost"]}}, upsert=True)
                
                send_telegram_message(booking["user_id"], "🎉 <b>Badhai ho!</b> Host ne aapki booking request accept kar li hai. Ab aap session join kar sakte hain!")
                requests.post(f"{TELEGRAM_API_URL}, editMessageText", json={
                    "chat_id": chat_id, "message_id": message_id, "text": f"✅ Booking Approved Successfully"
                })

        elif data_str.startswith("reject_bk_"):
            booking_id = data_str.replace("reject_bk_", "")
            booking = bookings_col.find_one({"booking_id": booking_id})
            if booking:
                bookings_col.update_one({"booking_id": booking_id}, {"$set": {"status": "rejected"}})
                token_cost = booking["token_cost"]
                # Refund tokens to user
                users_col.update_one({"user_id": booking["user_id"]}, {"$inc": {"tokens": token_cost}})
                send_telegram_message(booking["user_id"], f"❌ Aapki booking request reject kar di gayi hai. Aapke {token_cost} tokens refund kar diye gaye hain.")
                requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={
                    "chat_id": chat_id, "message_id": message_id, "text": f"❌ Booking Rejected & Tokens Refunded"
                })

    return {"status": "ok"}
