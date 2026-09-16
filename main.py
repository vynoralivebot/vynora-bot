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
    img: str
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
    if not user:
        user = {"user_id": int(user_id), "tokens": 100, "earnings": 0, "avatar": ""}
        users_col.insert_one(user)
        send_telegram_message(GROUP_2_ID, f"👤 <b>New User Started Bot!</b>\nID: <code>{user_id}</code>")
    return {"tokens": user.get("tokens", 100), "earnings": user.get("earnings", 0), "avatar": user.get("avatar", "")}

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
    hosts_cursor = hosts_col.find({"status": "approved"}, {"_id": 0})
    hosts = []
    for h in hosts_cursor:
        if not h.get("id"):
            h["id"] = f"h_{h.get('user_id')}"
        hosts.append(h)
    return {"hosts": hosts}

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
    user = users_col.find_one({"user_id": int(data.user_id)})
    if not user or user.get("tokens", 0) < data.token_cost:
        return {"status": "error", "message": f"Insufficient tokens! You need {data.token_cost} tokens."}

    users_col.update_one({"user_id": int(data.user_id)}, {"$inc": {"tokens": -data.token_cost}})

    booking_id = str(uuid.uuid4())[:8]
    clean_host_id = str(data.host_id).replace("h_", "").replace("host_", "")
    channel_name = f"private_call_{clean_host_id}_{data.user_id}"

    booking_doc = {
        "booking_id": booking_id,
        "user_id": int(data.user_id),
        "host_id": data.host_id,
        "host_name": data.host_name,
        "duration_mins": data.duration_mins,
        "token_cost": data.token_cost,
        "channel_name": channel_name,
        "status": "pending",
        "time": time.time()
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
            msg = f"🔔 <b>New Private Booking Request!</b>\n\n👤 User ID: <code>{data.user_id}</code>\n⏱️ Duration: {data.duration_mins} Mins\n🪙 Cost: {data.token_cost} Tokens"
            send_telegram_message(host_telegram_id, msg, reply_markup=keyboard)

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

        # --- ROBUST AUTO-COMPLETE (HANDLES MISSING OR 0 TIME FIELDS) ---
        now = time.time()
        all_host_bookings = list(bookings_col.find({"host_id": {"$in": list(set(h_ids))}}))
        for b in all_host_bookings:
            if b.get("status") == "approved":
                start_time = b.get("time") or 0
                duration_secs = b.get("duration_mins", 1) * 60
                if start_time == 0 or now > (start_time + duration_secs + 120):
                    bookings_col.update_one({"_id": b["_id"]}, {"$set": {"status": "completed"}})

        bookings_cursor = bookings_col.find({"host_id": {"$in": list(set(h_ids))}}).sort("time", -1)
        host_bookings = []
        for b in bookings_cursor:
            b_id = str(b.get("booking_id") or b.get("_id"))
            host_bookings.append({
                "booking_id": b_id,
                "user_id": b.get("user_id"),
                "host_id": b.get("host_id"),
                "host_name": b.get("host_name"),
                "duration_mins": b.get("duration_mins"),
                "token_cost": b.get("token_cost"),
                "channel_name": b.get("channel_name", f"private_call_{user_id}_{b.get('user_id')}"),
                "status": b.get("status", "pending"),
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
    
    if not booking:
        booking = bookings_col.find_one({"status": "pending"})
        if not booking:
            return {"status": "error", "message": "Booking not found"}
    
    bookings_col.update_one({"_id": booking["_id"]}, {"$set": {"status": "approved"}})
    
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
    send_telegram_message(int(booking["user_id"]), f"📞 <b>Incoming Video Call!</b> Host accepted your booking. Tap below to pick up.", reply_markup=user_keyboard)
    
    return {"status": "success", "message": "Booking accepted successfully!", "channel_name": booking.get("channel_name")}

@app.post("/api/host/reject-booking")
def reject_booking(data: ActionBookingModel):
    booking = bookings_col.find_one({
        "$or": [
            {"booking_id": data.booking_id},
            {"_id": data.booking_id}
        ]
    })
    
    if not booking:
        booking = bookings_col.find_one({"status": "pending"})
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
        # --- ROBUST AUTO-COMPLETE (HANDLES MISSING OR 0 TIME FIELDS) ---
        user_raw_bookings = list(bookings_col.find({"user_id": int(user_id)}))
        for b in user_raw_bookings:
            if b.get("status") == "approved":
                start_time = b.get("time") or 0
                duration_secs = b.get("duration_mins", 1) * 60
                if start_time == 0 or now > (start_time + duration_secs + 120):
                    bookings_col.update_one({"_id": b["_id"]}, {"$set": {"status": "completed"}})

        user_bookings = list(bookings_col.find({"user_id": int(user_id)}, {"_id": 0}).sort("time", -1))
        for b in user_bookings:
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
    hosts_col.update_one({"user_id": int(data.user_id)}, {"$set": host_data}, upsert=True)
    
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve Host", "callback_data": f"approve_host_{data.user_id}"},
                {"text": "❌ Reject Host", "callback_data": f"reject_host_{data.user_id}"}
            ]
        ]
    }
    send_telegram_message(GROUP_1_ID, f"📹 <b>New Host Application!</b>\nName: {data.name}\nAge: {data.age}\nRate: {data.rate} Tokens/min\nID: <code>{data.user_id}</code>", reply_markup=keyboard)
    return {"status": "success", "message": "Host registered successfully! Waiting for admin approval."}

@app.post("/api/recharge")
async def recharge(user_id: int = Form(...), amount_inr: int = Form(...), utr_number: str = Form(...), screenshot: UploadFile = File(...)):
    tokens_expected = amount_inr if amount_inr < 500 else amount_inr + 50
    recharge_id = str(int(time.time()))
    recharges_col.insert_one({"recharge_id": recharge_id, "user_id": int(user_id), "amount_inr": amount_inr, "tokens_expected": tokens_expected, "utr_number": utr_number, "status": "pending"})

    keyboard = {"inline_keyboard": [[{"text": f"✅ Approve (+{tokens_expected})", "callback_data": f"approve_rc_{recharge_id}"}, {"text": "❌ Reject", "callback_data": f"reject_rc_{recharge_id}"}]]}
    send_telegram_message(GROUP_1_ID, f"💳 <b>New Recharge Request!</b>\nUser ID: <code>{user_id}</code>\nAmount: ₹{amount_inr}\nUTR: <code>{utr_number}</code>", reply_markup=keyboard)
    return {"status": "success", "message": "Recharge submitted! Waiting for admin approval."}

@app.post("/api/withdraw")
def withdraw_earnings(data: WithdrawModel):
    host = hosts_col.find_one({"user_id": int(data.user_id), "status": "approved"})
    if not host:
        return {"status": "error", "message": "Withdrawal option is only available for approved hosts!"}

    user = users_col.find_one({"user_id": int(data.user_id)})
    if not user or user.get("earnings", 0) < data.tokens:
        return {"status": "error", "message": "Insufficient earnings balance!"}

    users_col.update_one({"user_id": int(data.user_id)}, {"$inc": {"earnings": -data.tokens}})
    withdrawals_col.insert_one({"user_id": int(data.user_id), "upi_id": data.upi_id, "tokens": data.tokens, "status": "pending"})
    send_telegram_message(GROUP_3_ID, f"💸 <b>New Withdrawal Request!</b>\nHost ID: <code>{data.user_id}</code>\nTokens: {data.tokens}\nUPI: <code>{data.upi_id}</code>")
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

    chats_col.insert_one({"channel": data.channel, "sender": data.sender_name, "text": f"sent gift {data.gift_name} (🪙 {data.gift_cost})", "type": "gift", "time": time.time()})
    return {"status": "success"}

@app.post("/api/send-chat")
def send_chat(data: ChatModel):
    chats_col.insert_one({"channel": data.channel, "sender": data.sender, "text": data.text, "type": data.type, "time": time.time()})
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
        text = msg.get("text", "")
        if text.startswith("/start"):
            user = users_col.find_one({"user_id": int(user_id)})
            if not user:
                users_col.insert_one({"user_id": int(user_id), "tokens": 100, "earnings": 0, "avatar": ""})
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
                send_telegram_message(u_id, f"🎉 <b>Recharge Approved!</b> +{tokens} Tokens added.")
                send_telegram_message(GROUP_3_ID, f"💳 <b>Recharge Approved & Verified!</b>\nUser ID: <code>{u_id}</code>\nAmount: ₹{rc.get('amount_inr')}\nTokens: +{tokens}\nUTR: <code>{rc.get('utr_number')}</code>")
                requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": "✅ Recharge Approved Successfully"})

        elif data_str.startswith("reject_rc_"):
            recharge_id = data_str.replace("reject_rc_", "")
            recharges_col.update_one({"recharge_id": recharge_id}, {"$set": {"status": "rejected"}})
            requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": "❌ Recharge Rejected"})

        elif data_str.startswith("accept_bk_"):
            booking_id = data_str.replace("accept_bk_", "")
            booking = bookings_col.find_one({"booking_id": booking_id})
            if booking:
                bookings_col.update_one({"booking_id": booking_id}, {"$set": {"status": "approved"}})
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
                send_telegram_message(int(booking["user_id"]), "📞 <b>Incoming Video Call!</b> Host accepted your booking. Tap below to pick up.", reply_markup=user_keyboard)
                requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": "✅ Booking Accepted & Call Ready"})

        elif data_str.startswith("reject_bk_"):
            booking_id = data_str.replace("reject_bk_", "")
            booking = bookings_col.find_one({"booking_id": booking_id})
            if booking:
                bookings_col.update_one({"booking_id": booking_id}, {"$set": {"status": "rejected"}})
                users_col.update_one({"user_id": int(booking["user_id"])}, {"$inc": {"tokens": booking["token_cost"]}})
                send_telegram_message(int(booking["user_id"]), f"❌ Booking rejected. {booking['token_cost']} tokens refunded.")
                requests.post(f"{TELEGRAM_API_URL}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": "❌ Booking Rejected"})

    return {"ok": True}
