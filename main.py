import os
import random
import shutil
import uuid
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pymongo import MongoClient
import requests

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static folder for direct image uploads
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# MongoDB Connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://cluster0.xxx.mongodb.net/?retryWrites=true&w=majority")
client = MongoClient(MONGO_URI)
db = client["vynora_live"]

# Dual Admins Configuration
ADMIN_IDS = [7001825467, 1108685585]
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_GROUP_ID = os.getenv("TELEGRAM_GROUP_ID", "YOUR_GROUP_ID")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-render-url.onrender.com")

class UserRegister(BaseModel):
    user_id: int
    username: str
    full_name: str

class GameBet(BaseModel):
    user_id: int
    bet_amount: int
    game_type: str
    choice: str

class CallBooking(BaseModel):
    user_id: int
    host_id: int

# --- 1. USER REGISTRATION & PROFILE API ---
@app.post("/api/register")
def register_user(data: UserRegister):
    user = db.users.find_one({"user_id": data.user_id})
    if not user:
        new_user = {
            "user_id": data.user_id,
            "username": data.username,
            "full_name": data.full_name,
            "tokens": 0,  # Join bonus strictly 0
            "dp_url": "https://via.placeholder.com/150",
            "is_banned": False,
            "is_host": False,
            "can_create_room": data.user_id in ADMIN_IDS
        }
        db.users.insert_one(new_user)
        return {"status": "registered", "tokens": 0, "can_create_room": new_user["can_create_room"], "dp_url": new_user["dp_url"]}
    
    return {
        "status": "exists", 
        "tokens": user.get("tokens", 0), 
        "dp_url": user.get("dp_url", "https://via.placeholder.com/150"), 
        "can_create_room": user.get("can_create_room", False) or user.get("user_id") in ADMIN_IDS
    }

# --- 2. DIRECT FILE UPLOAD DP API ---
@app.post("/api/update-dp")
async def update_dp(user_id: int = Form(...), file: UploadFile = File(...)):
    ext = file.filename.split(".")[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    dp_url = f"/uploads/{filename}"
    
    result = db.users.update_one({"user_id": user_id}, {"$set": {"dp_url": dp_url}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "success", "dp_url": dp_url}

# --- 3. 1V1 VIDEO CALL & GROUP NOTIFICATION API ---
@app.post("/api/book-call")
def book_call(data: CallBooking):
    user = db.users.find_one({"user_id": data.user_id})
    host = db.users.find_one({"user_id": data.host_id})
    
    if not user or not host:
        raise HTTPException(status_code=404, detail="User or Host not found")
    
    if user.get("tokens", 0) < 50:
        raise HTTPException(status_code=400, detail="Insufficient tokens for call")
    
    notification_text = (
        f"🚨 **New 1v1 Call Request!**\n\n"
        f"👤 User: {user.get('full_name')} (ID: {data.user_id})\n"
        f"🎯 Target Host: {host.get('full_name')} (ID: {data.host_id})\n\n"
        f"Host please accept the request to start the session."
    )
    
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
            "chat_id": TELEGRAM_GROUP_ID,
            "text": notification_text,
            "parse_mode": "Markdown",
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "✅ Accept Call", "callback_data": f"accept_call_{data.host_id}_{data.user_id}"}
                ]]
            }
        })
    except Exception as e:
        print("Notification error:", e)
        
    return {"status": "success", "message": "Call request sent!"}

# --- 4. MINI GAMES API ---
@app.post("/api/game/play")
def play_game(data: GameBet):
    user = db.users.find_one({"user_id": data.user_id})
    if not user or user.get("tokens", 0) < data.bet_amount:
        raise HTTPException(status_code=400, detail="Insufficient tokens")
    
    db.users.update_one({"user_id": data.user_id}, {"$inc": {"tokens": -data.bet_amount}})
    
    won = random.choice([True, False])
    payout = 0
    if won:
        payout = data.bet_amount * 2
        db.users.update_one({"user_id": data.user_id}, {"$inc": {"tokens": payout}})
        
    updated_user = db.users.find_one({"user_id": data.user_id})
    return {"won": won, "payout": payout, "new_balance": updated_user["tokens"]}

# --- 5. TELEGRAM BOT WEBHOOK ---
@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    body = await request.json()
    
    if "callback_query" in body:
        cq = body["callback_query"]
        data = cq["data"]
        chat_id = cq["message"]["chat"]["id"]
        
        if data.startswith("accept_call_"):
            parts = data.split("_")
            host_id = parts[2]
            user_id = parts[3]
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
                "chat_id": chat_id, 
                "text": f"✅ Host {host_id} has accepted the call with user {user_id}! Session connected."
            })
        return {"status": "ok"}

    if "message" in body:
        msg = body["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        text = msg.get("text", "")
        
        parts = text.split()
        cmd = parts[0] if parts else ""
        
        if cmd == "/start":
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
                "chat_id": chat_id,
                "text": "✨ Welcome to **Vynora Live**! Click the button below to open the app:",
                "parse_mode": "Markdown",
                "reply_markup": {
                    "inline_keyboard": [[
                        {"text": "🚀 Open Vynora Live App", "web_app": {"url": WEBAPP_URL}}
                    ]]
                }
            })
            return {"status": "ok"}
        
        if user_id in ADMIN_IDS:
            if cmd == "/giveroom" and len(parts) > 1:
                target_id = int(parts[1])
                db.users.update_one({"user_id": target_id}, {"$set": {"can_create_room": True}})
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
                    "chat_id": chat_id, "text": f"✅ User {target_id} ko 3-Seat Audio Room banane ki permission mil gayi hai!"
                })
            elif cmd == "/revokeroom" and len(parts) > 1:
                target_id = int(parts[1])
                db.users.update_one({"user_id": target_id}, {"$set": {"can_create_room": False}})
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
                    "chat_id": chat_id, "text": f"❌ User {target_id} se room creation permission wapas le li gayi hai."
                })
            elif cmd == "/addtokens" and len(parts) > 2:
                target_id = int(parts[1])
                amount = int(parts[2])
                db.users.update_one({"user_id": target_id}, {"$inc": {"tokens": amount}}, upsert=True)
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
                    "chat_id": chat_id, "text": f"🪙 Added {amount} tokens to user {target_id}."
                })
            elif cmd == "/cuttokens" and len(parts) > 2:
                target_id = int(parts[1])
                amount = int(parts[2])
                db.users.update_one({"user_id": target_id}, {"$inc": {"tokens": -amount}})
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
                    "chat_id": chat_id, "text": f"⚠️ Cut {amount} tokens from user {target_id}."
                })
            elif cmd == "/ban" and len(parts) > 1:
                target_id = int(parts[1])
                db.users.update_one({"user_id": target_id}, {"$set": {"is_banned": True}})
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
                    "chat_id": chat_id, "text": f"🚫 User {target_id} has been banned."
                })
            elif cmd == "/unban" and len(parts) > 1:
                target_id = int(parts[1])
                db.users.update_one({"user_id": target_id}, {"$set": {"is_banned": False}})
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
                    "chat_id": chat_id, "text": f"✅ User {target_id} has been unbanned."
                })

    return {"status": "ok"}
