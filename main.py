import os
import time
import uuid
import base64
import re
import threading
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
import uvicorn

try:
    from agora_token_builder import RtcTokenBuilder, Role_Publisher
except Exception:
    RtcTokenBuilder = None
    Role_Publisher = 1

# ============================================================
# VYNORA LIVE - MongoDB + FastAPI + Agora
# Complete replacement backend
# ============================================================

APP = FastAPI(title="Vynora Live API", version="2.0")
app = APP  # Render/uvicorn compatibility: main:app

APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MONGO_URI = os.getenv("MONGO_URI", "").strip()
if not MONGO_URI:
    raise RuntimeError("MONGO_URI is required")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
AGORA_APP_ID = os.getenv("AGORA_APP_ID", "").strip()
AGORA_APP_CERTIFICATE = os.getenv("AGORA_APP_CERTIFICATE", "").strip()
WEB_APP_URL = os.getenv("WEB_APP_URL", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "7778606261,7001825467").split(",") if x.strip().isdigit()}

# Telegram workflow groups / team access. Add these in Render Environment.
GROUP_1_ID = os.getenv("GROUP_1_ID", os.getenv("HOST_RECHARGE_GROUP_ID", "")).strip()
GROUP_2_ID = os.getenv("GROUP_2_ID", os.getenv("NEW_USER_GROUP_ID", "")).strip()
GROUP_3_ID = os.getenv("GROUP_3_ID", os.getenv("TEAM_GROUP_ID", "")).strip()

def _group_id(value):
    try:
        return int(value) if value else None
    except Exception:
        return None

GROUP1 = _group_id(GROUP_1_ID)
GROUP2 = _group_id(GROUP_2_ID)
GROUP3 = _group_id(GROUP_3_ID)


PLATFORM_CUT = float(os.getenv("PLATFORM_CUT", "0.30"))
AGENCY_CUT = float(os.getenv("AGENCY_CUT", "0.10"))
DEFAULT_RATE = int(os.getenv("DEFAULT_RATE", "30"))
UPI_ID = os.getenv("UPI_ID", "vynoralive@slc").strip()
UPI_NAME = os.getenv("UPI_NAME", "RajnishKumar").strip()
REQUIRE_USER_APPROVAL = os.getenv("REQUIRE_USER_APPROVAL", "false").lower() == "true"
RECHARGE_PLANS = {50: 100, 100: 220, 300: 700, 500: 1200, 1000: 2500, 2000: 5200}
MAX_BOOKING_MINUTES = 30

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
APP.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
db = mongo["vynora_live"]

users_col = db["users"]
hosts_col = db["hosts"]
bookings_col = db["bookings"]
recharges_col = db["recharges"]
withdrawals_col = db["withdrawals"]
chats_col = db["chats"]
gifts_col = db["gifts"]
live_col = db["public_lives"]
settings_col = db["settings"]

try:
    users_col.create_index("user_id", unique=True)
    hosts_col.create_index("user_id", unique=True)
    bookings_col.create_index("booking_id", unique=True)
    bookings_col.create_index([("user_id", 1), ("status", 1)])
    bookings_col.create_index([("host_id", 1), ("status", 1)])
    live_col.create_index("host_user_id", unique=True)
    settings_col.create_index("key", unique=True)
except Exception:
    pass

# ------------------------- Account safety middleware ---------
# Banned users/hosts are rejected server-side, not only hidden in the UI.
async def _read_request_json(request: Request):
    try:
        body = await request.body()
        if body:
            import json
            data = json.loads(body.decode("utf-8"))
        else:
            data = {}
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        request._receive = receive
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@APP.middleware("http")
async def banned_account_guard(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        data = await _read_request_json(request) if request.method in {"POST", "PUT", "PATCH"} else {}
        candidate_ids = set()
        for key in ("user_id", "host_user_id", "host_id", "sender_id", "receiver_id"):
            value = data.get(key)
            if value is not None:
                try:
                    candidate_ids.add(oid_int(value) or int(value))
                except Exception:
                    pass
        for key in ("user_id", "host_user_id"):
            value = request.query_params.get(key)
            if value:
                try:
                    candidate_ids.add(int(value))
                except Exception:
                    pass
        m = re.search(r"/api/(?:user|host/status|public-live/stop)/(-?\d+)", request.url.path)
        if m:
            candidate_ids.add(int(m.group(1)))
        for uid in candidate_ids:
            u = users_col.find_one({"user_id": uid}, {"banned": 1})
            h = hosts_col.find_one({"user_id": uid}, {"banned": 1})
            if (u and u.get("banned")) or (h and h.get("banned")):
                return JSONResponse({"detail": "Account is blocked by admin", "banned": True}, status_code=403)
    return await call_next(request)

# ------------------------- Models ----------------------------

class BookingModel(BaseModel):
    user_id: int
    host_id: int | str
    host_name: str = ""
    duration_mins: int = Field(ge=1, le=30)
    token_cost: int = Field(ge=1)


class ActionBookingModel(BaseModel):
    booking_id: str
    host_id: Optional[int] = None
    user_id: Optional[int] = None


class StartCallModel(BaseModel):
    booking_id: str
    user_id: int
    role: str


class CompleteBookingModel(BaseModel):
    booking_id: str
    user_id: Optional[int] = None


class RateModel(BaseModel):
    user_id: int
    rate: int = Field(ge=1, le=100000)


class WithdrawModel(BaseModel):
    user_id: int
    amount: float = Field(gt=0)
    upi_id: str = ""


class RechargeModel(BaseModel):
    user_id: int
    amount: float = Field(gt=0)
    transaction_id: str = ""
    screenshot: str = ""


class ChatModel(BaseModel):
    channel: str
    user_id: int
    message: str


class GiftModel(BaseModel):
    channel: str
    sender_id: int
    receiver_id: int
    gift_name: str = "🎁 Gift"
    token_cost: int = Field(gt=0)


class HostRegisterModel(BaseModel):
    user_id: int
    name: str = ""
    rate: int = DEFAULT_RATE
    photo_url: str = ""
    age: str = ""
    country: str = "India"
    language: str = "Hindi"
    experience: str = ""
    availability: str = ""
    bio: str = ""
    social_link: str = ""
    telegram_username: str = ""


class LiveStartModel(BaseModel):
    host_user_id: int
    title: str = "🔴 Public Live"
    private_enabled: bool = False
    private_token_cost: int = 30


class LiveJoinModel(BaseModel):
    user_id: int
    host_user_id: int


class AnnouncementModel(BaseModel):
    title: str = "📢 Vynora Live Announcement"
    message: str
    button_text: str = "Open"
    action: str = ""
    active: bool = True


# ------------------------- Helpers ----------------------------

def now() -> float:
    return time.time()


def oid_int(value):
    try:
        return int(str(value).replace("h_", "").replace("host_", ""))
    except Exception:
        return None


def user_name(user_id: int) -> str:
    u = users_col.find_one({"user_id": int(user_id)}) or {}
    return u.get("name") or u.get("first_name") or f"User #{user_id}"


def host_doc(host_id: int):
    h = hosts_col.find_one({"user_id": int(host_id)})
    if h:
        return h
    return users_col.find_one({"user_id": int(host_id), "is_host": True})


def normalize_host(h):
    uid = int(h.get("user_id", h.get("host_id", 0)))
    return {
        "user_id": uid,
        "host_id": f"h_{uid}",
        "name": h.get("name") or h.get("host_name") or f"Host #{uid}",
        "first_name": h.get("first_name", ""),
        "photo_url": h.get("photo_url") or h.get("profile_photo") or h.get("photo") or "",
        "rate": int(h.get("rate") or h.get("rate_per_minute") or DEFAULT_RATE),
        "is_online": bool(h.get("is_online", h.get("online", False))),
        "verified": bool(h.get("verified", h.get("is_verified", False))),
        "is_host": True,
        "public_live": bool(h.get("public_live", False)),
        "private_live": bool(h.get("private_live", False)),
        "private_live_cost": int(h.get("private_live_cost", 30)),
        "dummy": bool(h.get("dummy", False)),
    }


def save_base64_image(data: str, prefix: str) -> str:
    if not data:
        return ""
    if "," in data:
        header, data = data.split(",", 1)
    try:
        raw = base64.b64decode(data)
    except Exception:
        raise HTTPException(400, "Invalid image data")
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(400, "Image is too large")
    ext = ".jpg"
    filename = f"{prefix}_{uuid.uuid4().hex}.jpg"
    path = UPLOAD_DIR / filename
    path.write_bytes(raw)
    return f"/uploads/{filename}"


def public_host_exists(host_id: int) -> bool:
    h = host_doc(host_id)
    return bool(h and h.get("is_host", True) and h.get("verified", False) and not h.get("banned", False))


def ensure_user(user_id: int, name: str = ""):
    users_col.update_one(
        {"user_id": int(user_id)},
        {"$setOnInsert": {
            "user_id": int(user_id),
            "name": name or f"User #{user_id}",
            "tokens": 0,
            "earnings": 0.0,
            "approved": False,
            "banned": False,
            "created_at": now(),
        }},
        upsert=True,
    )
    return users_col.find_one({"user_id": int(user_id)}) or {}


def calculate_cost(rate: int, minutes: int) -> int:
    return int(rate) * int(minutes)


def private_channel(host_id: int, user_id: int) -> str:
    return f"private_call_{host_id}_{user_id}"


def remaining_for_booking(b):
    started = b.get("session_started_at")
    if not started:
        return None
    duration = int(b.get("duration_mins", 1)) * 60
    return max(0, int(started + duration - now()))


# Render start command uses: uvicorn main:app
app = APP


# ------------------------- Telegram Bot ------------------------

def telegram_api(method, payload=None, timeout=20):
    if not BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        r = requests.post(url, json=payload or {}, timeout=timeout)
        return r.json()
    except Exception:
        return None


def telegram_send(chat_id, text, reply_markup=None):
    payload = {"chat_id": int(chat_id), "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram_api("sendMessage", payload)


def india_now_text():
    return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d-%m-%Y %I:%M:%S %p") + " IST"

def workflow_tags():
    return ""

def send_group(group_id, text, reply_markup=None):
    if group_id is None or not BOT_TOKEN:
        return None
    return telegram_send(group_id, text, reply_markup)

def host_approval_keyboard(user_id):
    return {"inline_keyboard": [[
        {"text": "✅ Approve Host", "callback_data": f"approve_host:{int(user_id)}"},
        {"text": "❌ Reject", "callback_data": f"reject_host:{int(user_id)}"}
    ]]}

def recharge_keyboard(recharge_id):
    return {"inline_keyboard": [[
        {"text": "✅ Approve Recharge", "callback_data": f"approve_recharge:{recharge_id}"},
        {"text": "❌ Reject", "callback_data": f"reject_recharge:{recharge_id}"}
    ]]}

def notify_new_user_group(user_id, first_name, username=""):
    send_group(GROUP2,
        "🆕 NEW USER REGISTERED\n\n"
        f"👤 Name: {first_name or '-'}\n"
        f"🆔 User ID: {int(user_id)}\n"
        f"🔗 Username: @{username.lstrip('@') if username else '-'}\n"
        f"🕐 Date/Time: {india_now_text()}\n\n"
        f"{workflow_tags()}")

def notify_host_application(doc):
    uid=int(doc["user_id"])
    text=("🎙️ NEW HOST APPLICATION\n\n"
          f"👤 Name: {doc.get('name','-')}\n"
          f"🆔 User ID: {uid}\n"
          f"🔗 Username: @{doc.get('telegram_username','').lstrip('@') or '-'}\n"
          f"🎂 Age: {doc.get('age') or '-'}\n"
          f"🌍 Country: {doc.get('country') or '-'}\n"
          f"🗣 Language: {doc.get('language') or '-'}\n"
          f"⭐ Experience: {doc.get('experience') or '-'}\n"
          f"🕐 Availability: {doc.get('availability') or '-'}\n"
          f"🪙 Requested Rate: {doc.get('rate',DEFAULT_RATE)} token/min\n"
          f"🔗 Social: {doc.get('social_link') or '-'}\n"
          f"📝 Bio: {doc.get('bio') or '-'}\n"
          f"🕐 Applied: {india_now_text()}\n\n"
          f"{workflow_tags()}")
    return send_group(GROUP1, text, host_approval_keyboard(uid))

def notify_approved_host(doc, approved_by):
    uid=int(doc["user_id"])
    return send_group(GROUP3,
        "✅ HOST APPROVED & VERIFIED\n\n"
        f"👤 Name: {doc.get('name','-')}\n"
        f"🆔 User ID: {uid}\n"
        f"🪙 Rate: {doc.get('rate',DEFAULT_RATE)} token/min\n"
        f"👑 Status: VERIFIED HOST\n"
        f"🧑‍💼 Approved By: {approved_by}\n"
        f"🕐 {india_now_text()}\n\n"
        f"{workflow_tags()}")

def notify_recharge_request(doc):
    return send_group(GROUP1,
        "💳 NEW RECHARGE REQUEST\n\n"
        f"🆔 Recharge ID: {doc.get('recharge_id')}\n"
        f"👤 User ID: {doc.get('user_id')}\n"
        f"💵 Amount: ₹{doc.get('amount')}\n"
        f"🪙 Tokens: {doc.get('tokens')}\n"
        f"🔢 UTR: {doc.get('transaction_id') or '-'}\n"
        f"🕐 {india_now_text()}\n\n"
        f"{workflow_tags()}", recharge_keyboard(doc.get('recharge_id')))

def notify_approved_recharge(doc, approved_by):
    return send_group(GROUP3,
        "✅ RECHARGE APPROVED\n\n"
        f"🆔 Recharge ID: {doc.get('recharge_id')}\n"
        f"👤 User ID: {doc.get('user_id')}\n"
        f"💵 Amount: ₹{doc.get('amount')}\n"
        f"🪙 Tokens Added: {doc.get('tokens')}\n"
        f"🧑‍💼 Approved By: {approved_by}\n"
        f"🕐 {india_now_text()}\n\n"
        f"{workflow_tags()}")



def telegram_start_message(chat_id, first_name="User", username="", first_start=False):
    name = first_name or "User"
    keyboard = None
    if WEB_APP_URL.startswith("https://"):
        keyboard = {"inline_keyboard": [[{"text": "🚀 Open Vynora Live App", "web_app": {"url": WEB_APP_URL}}]]}
    elif WEB_APP_URL:
        keyboard = {"inline_keyboard": [[{"text": "🚀 Open Vynora Live App", "url": WEB_APP_URL}]]}

    ensure_user(int(chat_id), name)
    before = users_col.find_one({"user_id": int(chat_id)}) or {}
    users_col.update_one(
        {"user_id": int(chat_id)},
        {"$set": {"telegram_chat_id": int(chat_id), "first_name": name, "telegram_started": True}},
        upsert=True,
    )
    if first_start:
        notify_new_user_group(int(chat_id), name, username or before.get("username", ""))
    return telegram_send(
        chat_id,
        f"✨ Welcome to Vynora Live 1v1, {name}!\n\n"
        "📞 Private 1-to-1 video call\n"
        "🔴 Public Live + Gifting\n"
        "🎁 Gifts & Tokens\n"
        "⏱️ 1–30 minute private sessions\n\n"
        "👇 नीचे button दबाकर app खोलें.",
        keyboard,
    )


def is_admin(user_id: int) -> bool:
    return int(user_id) in ADMIN_IDS


def has_live_access(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    u = users_col.find_one({"user_id": int(user_id)}) or {}
    h = hosts_col.find_one({"user_id": int(user_id)}) or {}
    return bool(u.get("live_access") or h.get("live_access") or (h.get("is_host") and h.get("verified")))


def admin_help_text():
    return (
        "🛠 Vynora Live Admin Commands\n\n"
        "/addtoken USER_ID AMOUNT — token जोड़ें\n"
        "/removetoken USER_ID AMOUNT — token हटाएँ\n"
        "/settoken USER_ID AMOUNT — token set करें\n"
        "/addhost USER_ID [RATE] — host add/approve\n"
        "/removehost USER_ID — host हटाएँ\n"
        "/approvehost USER_ID — host approve/verify\n"
        "/approveuser USER_ID — user approve\n"
        "/ban USER_ID [reason] — user/host ban\n"
        "/unban USER_ID — ban हटाएँ\n"
        "/block USER_ID [reason] — ban का alias\n"
        "/unblock USER_ID — unban का alias\n"
        "/user USER_ID — user details\n"
        "/announce MESSAGE — सभी registered Telegram users को message\n"
        "/announceusers MESSAGE — users को message\n"
        "/announcehosts MESSAGE — hosts को message\n"
        "/offer MESSAGE — सभी registered users को offer message\n"
        "/announcement MESSAGE — app banner set + broadcast\n"
        "/clearannouncement — app banner हटाएँ\n"
        "/approverecharge RECHARGE_ID — recharge approve\n"
        "/rejectrecharge RECHARGE_ID — recharge reject\n"
        "/givelive USER_ID — Public Live access दें\n"
        "/revokelive USER_ID — Public Live access हटाएँ\n"
        "/livestatus USER_ID — live access देखें\n"
        "/stats — users/hosts/banned counts\n"
        "/helpadmin — यह list\n\n"
        "ℹ️ Broadcast उन्हीं users को जाएगा जिन्होंने bot में /start करके Telegram chat register किया है."
    )


def _parse_int(value):
    try:
        return int(str(value).strip())
    except Exception:
        return None


def admin_command(chat_id: int, text: str):
    parts = text.strip().split()
    cmd = parts[0].split("@")[0].lower()
    args = parts[1:]

    if cmd in {"/helpadmin", "/adminhelp"}:
        telegram_send(chat_id, admin_help_text())
        return

    if cmd == "/stats":
        users = users_col.count_documents({})
        hosts = hosts_col.count_documents({"is_host": True})
        banned = users_col.count_documents({"banned": True})
        verified = hosts_col.count_documents({"is_host": True, "verified": True})
        telegram_send(chat_id, f"📊 Vynora Stats\n\n👤 Users: {users}\n🎙 Hosts: {hosts}\n✅ Verified hosts: {verified}\n🚫 Banned: {banned}")
        return

    if cmd in {"/addtoken", "/removetoken", "/settoken"}:
        if len(args) != 2:
            telegram_send(chat_id, f"Usage: {cmd} USER_ID AMOUNT")
            return
        uid, amount = _parse_int(args[0]), _parse_int(args[1])
        if not uid or amount is None or amount < 0:
            telegram_send(chat_id, "❌ User ID/amount invalid.")
            return
        ensure_user(uid)
        if cmd == "/addtoken":
            users_col.update_one({"user_id": uid}, {"$inc": {"tokens": amount}})
            action = f"+{amount}"
        elif cmd == "/removetoken":
            r = users_col.update_one({"user_id": uid, "tokens": {"$gte": amount}}, {"$inc": {"tokens": -amount}})
            if r.modified_count == 0 and amount > 0:
                telegram_send(chat_id, "❌ User के पास इतने tokens नहीं हैं.")
                return
            action = f"-{amount}"
        else:
            users_col.update_one({"user_id": uid}, {"$set": {"tokens": amount}})
            action = f"={amount}"
        u = users_col.find_one({"user_id": uid}) or {}
        telegram_send(chat_id, f"✅ User {uid}: tokens {action}\n💰 Current balance: {int(u.get('tokens', 0))}")
        return

    if cmd in {"/addhost", "/approvehost"}:
        if not args:
            telegram_send(chat_id, f"Usage: {cmd} USER_ID [RATE]")
            return
        uid = _parse_int(args[0])
        rate = _parse_int(args[1]) if len(args) > 1 else DEFAULT_RATE
        if not uid or not rate or rate < 1:
            telegram_send(chat_id, "❌ User ID/rate invalid.")
            return
        u = ensure_user(uid)
        name = u.get("name") or u.get("first_name") or f"Host #{uid}"
        doc = {
            "user_id": uid, "name": name, "rate": rate, "is_host": True,
            "verified": True, "approved": True, "is_online": False,
            "live_access": True, "public_live": False, "private_live": False,
            "private_live_cost": 30, "photo_url": u.get("profile_photo", ""),
        }
        hosts_col.update_one({"user_id": uid}, {"$set": doc}, upsert=True)
        users_col.update_one({"user_id": uid}, {"$set": {"is_host": True, "verified": True, "host_approved": True, "approved": True, "live_access": True, "rate": rate}}, upsert=True)
        telegram_send(chat_id, f"✅ Host approved/added\n👤 ID: {uid}\n🎙 Name: {name}\n💰 Rate: ₹{rate}/min")
        approved_doc = hosts_col.find_one({"user_id": uid}) or doc
        notify_approved_host(approved_doc, chat_id)
        telegram_send(uid, "🎉 Your Vynora Live Host application is approved. You are now a Verified Host.")
        return

    if cmd == "/removehost":
        if len(args) != 1:
            telegram_send(chat_id, "Usage: /removehost USER_ID")
            return
        uid = _parse_int(args[0])
        if not uid:
            telegram_send(chat_id, "❌ Invalid user ID.")
            return
        hosts_col.delete_one({"user_id": uid})
        users_col.update_one({"user_id": uid}, {"$set": {"is_host": False, "verified": False, "host_approved": False, "is_online": False}})
        telegram_send(chat_id, f"✅ Host removed: {uid}")
        return

    if cmd == "/approveuser":
        if len(args) != 1:
            telegram_send(chat_id, "Usage: /approveuser USER_ID")
            return
        uid = _parse_int(args[0])
        if not uid:
            telegram_send(chat_id, "❌ Invalid user ID.")
            return
        ensure_user(uid)
        users_col.update_one({"user_id": uid}, {"$set": {"approved": True, "banned": False}})
        telegram_send(chat_id, f"✅ User approved: {uid}")
        return

    if cmd in {"/ban", "/block"}:
        if not args:
            telegram_send(chat_id, f"Usage: {cmd} USER_ID [reason]")
            return
        uid = _parse_int(args[0])
        if not uid:
            telegram_send(chat_id, "❌ Invalid user ID.")
            return
        reason = " ".join(args[1:]).strip() or "Admin action"
        ensure_user(uid)
        users_col.update_one({"user_id": uid}, {"$set": {"banned": True, "ban_reason": reason}})
        hosts_col.update_one({"user_id": uid}, {"$set": {"banned": True, "is_online": False, "public_live": False}})
        telegram_send(chat_id, f"🚫 Banned: {uid}\nReason: {reason}")
        return

    if cmd in {"/unban", "/unblock"}:
        if len(args) != 1:
            telegram_send(chat_id, f"Usage: {cmd} USER_ID")
            return
        uid = _parse_int(args[0])
        if not uid:
            telegram_send(chat_id, "❌ Invalid user ID.")
            return
        users_col.update_one({"user_id": uid}, {"$set": {"banned": False, "ban_reason": ""}})
        hosts_col.update_one({"user_id": uid}, {"$set": {"banned": False}})
        telegram_send(chat_id, f"✅ Unbanned: {uid}")
        return

    if cmd in {"/givelive", "/grantlive"}:
        if len(args) != 1:
            telegram_send(chat_id, "Usage: /givelive USER_ID")
            return
        uid = _parse_int(args[0])
        if not uid:
            telegram_send(chat_id, "❌ Invalid user ID.")
            return
        ensure_user(uid)
        users_col.update_one({"user_id": uid}, {"$set": {"live_access": True, "live_access_by": int(chat_id), "live_access_at": now()}})
        hosts_col.update_one({"user_id": uid}, {"$set": {"live_access": True}}, upsert=True)
        telegram_send(chat_id, f"🎥 Live access granted: {uid}")
        telegram_send(uid, "🎥 Vynora Live access granted by Admin. You can now use Live access if your profile is eligible.")
        return

    if cmd in {"/revokelive", "/removelive"}:
        if len(args) != 1:
            telegram_send(chat_id, "Usage: /revokelive USER_ID")
            return
        uid = _parse_int(args[0])
        if not uid:
            telegram_send(chat_id, "❌ Invalid user ID.")
            return
        users_col.update_one({"user_id": uid}, {"$set": {"live_access": False}})
        hosts_col.update_one({"user_id": uid}, {"$set": {"live_access": False}})
        telegram_send(chat_id, f"🚫 Live access revoked: {uid}")
        return

    if cmd == "/livestatus":
        if len(args) != 1:
            telegram_send(chat_id, "Usage: /livestatus USER_ID")
            return
        uid = _parse_int(args[0])
        if not uid:
            telegram_send(chat_id, "❌ Invalid user ID.")
            return
        telegram_send(chat_id, f"🎥 Live access for {uid}: {'YES' if has_live_access(uid) else 'NO'}")
        return

    if cmd == "/user":
        if len(args) != 1:
            telegram_send(chat_id, "Usage: /user USER_ID")
            return
        uid = _parse_int(args[0])
        if not uid:
            telegram_send(chat_id, "❌ Invalid user ID.")
            return
        u = users_col.find_one({"user_id": uid}) or {}
        h = hosts_col.find_one({"user_id": uid}) or {}
        telegram_send(chat_id, (
            f"👤 User {uid}\n"
            f"Name: {u.get('name') or u.get('first_name') or '-'}\n"
            f"Username: @{u.get('username', '').lstrip('@') or '-'}\n"
            f"Tokens: {int(u.get('tokens', 0))}\n"
            f"Approved: {'Yes' if u.get('approved') else 'No'}\n"
            f"Banned: {'Yes' if u.get('banned') else 'No'}\n"
            f"Host: {'Yes' if h.get('is_host') or u.get('is_host') else 'No'}\n"
            f"Verified: {'Yes' if h.get('verified') or u.get('verified') else 'No'}"
        ))
        return

    if cmd in {"/approverecharge", "/rejectrecharge"}:
        if len(args) != 1:
            telegram_send(chat_id, f"Usage: {cmd} RECHARGE_ID")
            return
        rid = args[0].strip()
        r = recharges_col.find_one({"recharge_id": rid})
        if not r:
            telegram_send(chat_id, "❌ Recharge not found")
            return
        if r.get("status") != "pending":
            telegram_send(chat_id, f"⚠️ Recharge already {r.get('status')}")
            return
        if cmd == "/approverecharge":
            users_col.update_one({"user_id": int(r["user_id"])}, {"$inc": {"tokens": int(r.get("tokens", 0))}})
            recharges_col.update_one({"_id": r["_id"]}, {"$set": {"status": "approved", "approved_at": now(), "approved_by": int(chat_id)}})
            telegram_send(chat_id, f"✅ Recharge approved\n👤 User: {r['user_id']}\n🪙 Tokens added: {int(r.get('tokens', 0))}")
            notify_approved_recharge(r, chat_id)
            telegram_send(int(r["user_id"]), f"🎉 Recharge approved!\n🪙 {int(r.get('tokens', 0))} tokens आपके wallet में add किए गए हैं.")
        else:
            recharges_col.update_one({"_id": r["_id"]}, {"$set": {"status": "rejected", "rejected_at": now(), "rejected_by": int(chat_id)}})
            telegram_send(chat_id, f"❌ Recharge rejected: {rid}")
        return

    if cmd == "/clearannouncement":
        settings_col.update_one({"key": "announcement"}, {"$set": {"active": False, "updated_at": now(), "updated_by": int(chat_id)}}, upsert=True)
        telegram_send(chat_id, "✅ App announcement banner cleared.")
        return

    if cmd in {"/announcement", "/announce", "/offer", "/announceusers", "/announcehosts"}:
        message = text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else ""
        if not message:
            telegram_send(chat_id, f"Usage: {cmd} MESSAGE")
            return

        if cmd == "/announcement":
            settings_col.update_one({"key": "announcement"}, {"$set": {
                "active": True, "title": "📢 Vynora Live Announcement", "message": message,
                "button_text": "Open", "action": "", "updated_at": now(), "updated_by": int(chat_id)
            }}, upsert=True)
            prefix = "📢 VYNORA LIVE\n\n"
        else:
            prefix = "🎁 SPECIAL OFFER\n\n" if cmd == "/offer" else "📢 ANNOUNCEMENT\n\n"

        query = {"telegram_chat_id": {"$exists": True}}
        if cmd == "/announcehosts":
            query["is_host"] = True
        elif cmd == "/announceusers":
            query["is_host"] = {"$ne": True}
        recipients = set()
        for d in users_col.find(query, {"telegram_chat_id": 1}):
            cid = d.get("telegram_chat_id")
            if cid is not None:
                recipients.add(int(cid))
        sent = failed = 0
        for cid in recipients:
            result = telegram_send(cid, prefix + message)
            if result and result.get("ok"):
                sent += 1
            else:
                failed += 1
            time.sleep(0.05)
        telegram_send(chat_id, f"✅ Broadcast complete\n📨 Sent: {sent}\n⚠️ Failed: {failed}\n👥 Target chats: {len(recipients)}")
        return

    telegram_send(chat_id, "❓ Unknown admin command. /helpadmin भेजें.")


def telegram_polling_worker():
    if not BOT_TOKEN:
        print("BOT_TOKEN not configured; Telegram polling disabled.")
        return

    telegram_api("deleteWebhook", {"drop_pending_updates": False})
    offset = 0
    print("Telegram bot polling started.")

    while True:
        try:
            result = telegram_api("getUpdates", {
                "offset": offset, "timeout": 25,
                "allowed_updates": ["message", "callback_query"],
            }, timeout=35)
            if not result or not result.get("ok"):
                time.sleep(3)
                continue

            for update in result.get("result", []):
                offset = int(update["update_id"]) + 1

                cb = update.get("callback_query")
                if cb:
                    cb_from = int((cb.get("from") or {}).get("id", 0))
                    if not is_admin(cb_from):
                        telegram_api("answerCallbackQuery", {"callback_query_id": cb.get("id"), "text": "Admin only", "show_alert": True})
                        continue
                    data = cb.get("data", "")
                    try:
                        if data.startswith("approve_host:"):
                            uid = int(data.split(":",1)[1])
                            u = ensure_user(uid)
                            name = u.get("name") or u.get("first_name") or f"Host #{uid}"
                            oldh = hosts_col.find_one({"user_id": uid}) or {}
                            doc = {"user_id": uid, "name": name, "rate": int(oldh.get("rate") or u.get("rate") or DEFAULT_RATE), "is_host": True, "verified": True, "approved": True, "is_online": False, "public_live": False, "private_live": False, "private_live_cost": 30, "photo_url": u.get("profile_photo", ""), "live_access": True, "updated_at": now()}
                            hosts_col.update_one({"user_id": uid}, {"$set": doc}, upsert=True)
                            users_col.update_one({"user_id": uid}, {"$set": {"is_host": True, "verified": True, "host_approved": True, "approved": True, "rate": doc["rate"], "live_access": True}})
                            notify_approved_host(doc, cb_from)
                            telegram_send(uid, "🎉 Host approved! You are now a Verified Host with Live access.")
                            telegram_api("answerCallbackQuery", {"callback_query_id": cb.get("id"), "text": "Host approved"})
                        elif data.startswith("reject_host:"):
                            uid = int(data.split(":",1)[1])
                            hosts_col.update_one({"user_id": uid}, {"$set": {"application_status": "rejected", "verified": False, "is_host": False}})
                            users_col.update_one({"user_id": uid}, {"$set": {"host_approved": False}})
                            telegram_send(uid, "❌ Your Vynora Live host application was not approved at this time.")
                            telegram_api("answerCallbackQuery", {"callback_query_id": cb.get("id"), "text": "Host rejected"})
                        elif data.startswith("approve_recharge:") or data.startswith("reject_recharge:"):
                            rid = data.split(":",1)[1]
                            r = recharges_col.find_one({"recharge_id": rid})
                            if not r or r.get("status") != "pending":
                                telegram_api("answerCallbackQuery", {"callback_query_id": cb.get("id"), "text": "Already processed"})
                                continue
                            if data.startswith("approve_recharge:"):
                                users_col.update_one({"user_id": int(r["user_id"])}, {"$inc": {"tokens": int(r.get("tokens",0))}})
                                recharges_col.update_one({"_id": r["_id"]}, {"$set": {"status": "approved", "approved_at": now(), "approved_by": cb_from}})
                                notify_approved_recharge(r, cb_from)
                                telegram_send(int(r["user_id"]), f"🎉 Recharge approved! {int(r.get('tokens',0))} tokens wallet में add हुए.")
                                telegram_api("answerCallbackQuery", {"callback_query_id": cb.get("id"), "text": "Recharge approved"})
                            else:
                                recharges_col.update_one({"_id": r["_id"]}, {"$set": {"status": "rejected", "rejected_at": now(), "rejected_by": cb_from}})
                                telegram_send(int(r["user_id"]), "❌ Recharge request rejected. Please contact support.")
                                telegram_api("answerCallbackQuery", {"callback_query_id": cb.get("id"), "text": "Recharge rejected"})
                    except Exception as cb_exc:
                        telegram_api("answerCallbackQuery", {"callback_query_id": cb.get("id"), "text": "Action failed", "show_alert": True})
                        print(f"Telegram callback error: {cb_exc}")
                    continue

                msg = update.get("message") or {}
                chat = msg.get("chat") or {}
                chat_id = chat.get("id")
                if chat_id is None:
                    continue

                text = (msg.get("text") or "").strip()
                sender = msg.get("from") or {}
                first_name = sender.get("first_name", "User")
                sender_id = int(sender.get("id", chat_id))

                # Save Telegram identity so later broadcasts can reach this user.
                existing_user = users_col.find_one({"user_id": sender_id}) or {}
                was_started = bool(existing_user.get("telegram_started"))
                ensure_user(sender_id, first_name)
                users_col.update_one({"user_id": sender_id}, {"$set": {
                    "telegram_chat_id": int(chat_id),
                    "first_name": first_name,
                    "username": sender.get("username", ""),
                    "telegram_started": True,
                }})

                if is_admin(sender_id) and text.startswith("/"):
                    admin_command(chat_id, text)
                elif text.startswith("/start"):
                    telegram_start_message(chat_id, first_name, sender.get("username", ""), first_start=not was_started)
                elif text.startswith("/help"):
                    telegram_send(chat_id,
                        "🆘 Vynora Live Help\n\n"
                        "🚀 /start — Open Vynora Live\n"
                        "📞 Book a private call from the app\n"
                        "🔴 Hosts can start Public Live\n"
                        "🎁 Gifts are available during live/calls."
                    )
                else:
                    telegram_send(chat_id,
                        "👋 Vynora Live me welcome!\n\n"
                        "App खोलने के लिए /start भेजें.")
        except Exception as exc:
            print(f"Telegram polling error: {exc}")
            time.sleep(5)


if BOT_TOKEN:
    threading.Thread(target=telegram_polling_worker, daemon=True).start()

# ------------------------- Health -----------------------------

@APP.get("/")
def root():
    # Telegram Mini App / browser entry point.
    index_file = Path(__file__).with_name("index.html")
    if index_file.exists():
        return FileResponse(str(index_file), media_type="text/html")
    return {"status": "ok", "service": "vynora-live"}


@APP.get("/health")
@APP.get("/healthz")
def health():
    mongo.admin.command("ping")
    return {"status": "ok", "service": "vynora-live"}


# ------------------------- User/Profile -----------------------

@APP.get("/api/user/{user_id}")
def get_user(user_id: int):
    u = ensure_user(user_id)
    host_calls = bookings_col.count_documents({"host_id": int(user_id), "status": "completed"})
    host_tokens = sum(int(x.get("token_cost", 0)) for x in bookings_col.find({"host_id": int(user_id), "status": "completed"}, {"token_cost": 1}))
    return {
        "user_id": user_id,
        "name": u.get("name") or u.get("first_name") or f"User #{user_id}",
        "first_name": u.get("first_name", ""),
        "username": u.get("username", ""),
        "tokens": int(u.get("tokens", 0)),
        "earnings": float(u.get("earnings", 0)),
        "profile_photo": u.get("profile_photo", ""),
        "is_host": bool(u.get("is_host", False)),
        "verified": bool(u.get("verified", False)),
        "approved": bool(u.get("approved", False)),
        "banned": bool(u.get("banned", False)),
        "role": "admin" if is_admin(user_id) else ("verified_host" if u.get("is_host") and u.get("verified") else ("host" if u.get("is_host") else "user")),
        "is_admin": is_admin(user_id),
        "admin_display_name": "VYNORA ADMIN" if is_admin(user_id) else "",
        "live_access": has_live_access(user_id),
        "host_total_calls": host_calls,
        "host_total_tokens": host_tokens,
    }


@APP.post("/api/update-profile-photo")
def update_profile_photo(data: dict):
    user_id = int(data.get("user_id", 0))
    photo = data.get("photo", "")
    if not user_id or not photo:
        raise HTTPException(400, "user_id and photo are required")
    url = save_base64_image(photo, f"user_{user_id}")
    users_col.update_one({"user_id": user_id}, {"$set": {"profile_photo": url, "photo_url": url}})
    hosts_col.update_one({"user_id": user_id}, {"$set": {"photo_url": url, "profile_photo": url}})
    return {"status": "success", "photo_url": url}


# ------------------------- Hosts -------------------------------

@APP.get("/api/config")
def public_config():
    return {
        "upi_id": UPI_ID,
        "upi_name": UPI_NAME,
        "support": "https://t.me/VynoraSupport",
        "recharge_plans": [{"amount": a, "tokens": t} for a, t in RECHARGE_PLANS.items()],
        "private_durations": [1, 2, 5, 10, 15, 20, 30],
        "admin_badge": "👑 VYNORA ADMIN",
        "host_badge": "✓ VERIFIED HOST",
        "team_badge": "",
    }


@APP.get("/api/announcement")
def get_announcement():
    doc = settings_col.find_one({"key": "announcement"}) or {}
    return {
        "active": bool(doc.get("active", False)),
        "title": doc.get("title", "📢 Vynora Live Announcement"),
        "message": doc.get("message", ""),
        "button_text": doc.get("button_text", ""),
        "action": doc.get("action", ""),
        "updated_at": doc.get("updated_at"),
    }


@APP.post("/api/admin/announcement")
def set_announcement(data: AnnouncementModel, request: Request):
    # Admin authentication uses the authenticated Telegram user ID passed by the Mini App.
    # For production, ADMIN_IDS must be configured in Render.
    admin_id = request.headers.get("X-Telegram-User-Id") or request.query_params.get("admin_id")
    if not admin_id or not is_admin(int(admin_id)):
        raise HTTPException(403, "Admin only")
    doc = {
        "key": "announcement", "active": bool(data.active), "title": data.title[:80],
        "message": data.message[:500], "button_text": data.button_text[:30],
        "action": data.action[:300], "updated_at": now(), "updated_by": int(admin_id),
    }
    settings_col.update_one({"key": "announcement"}, {"$set": doc}, upsert=True)
    return {"status": "success", **doc}


@APP.get("/api/presence/{user_id}")
def get_presence(user_id: int):
    if is_admin(user_id):
        return {"user_id": user_id, "role": "admin", "badge": "👑 VYNORA ADMIN", "display_name": "VYNORA ADMIN"}
    h = host_doc(user_id)
    if h and h.get("is_host") and h.get("verified"):
        return {"user_id": user_id, "role": "verified_host", "badge": "✓ VERIFIED HOST", "display_name": h.get("name") or user_name(user_id)}
    return {"user_id": user_id, "role": "user", "badge": "", "display_name": user_name(user_id)}


@APP.get("/api/hosts")
def get_hosts():
    out = []
    seen = set()
    # Real verified hosts first.
    for h in hosts_col.find({"is_host": True, "dummy": {"$ne": True}}).sort([("verified", -1), ("is_online", -1), ("updated_at", -1)]):
        uid = int(h["user_id"])
        if uid not in seen:
            seen.add(uid)
            out.append(normalize_host(h))
    for h in users_col.find({"is_host": True, "dummy": {"$ne": True}}).sort([("verified", -1), ("is_online", -1)]):
        uid = int(h["user_id"])
        if uid not in seen:
            seen.add(uid)
            out.append(normalize_host(h))

    # Demo hosts are always at the bottom and can never be booked.
    dummy_hosts = [
        {"user_id": -900001, "name": "Angel • Demo", "rate": 50, "is_host": True, "verified": True, "is_online": True, "public_live": False, "private_live": False, "dummy": True, "photo_url": "https://i.pravatar.cc/500?img=47"},
        {"user_id": -900002, "name": "Sofia • Demo", "rate": 40, "is_host": True, "verified": True, "is_online": True, "public_live": False, "private_live": False, "dummy": True, "photo_url": "https://i.pravatar.cc/500?img=32"},
        {"user_id": -900003, "name": "Mia • Demo", "rate": 60, "is_host": True, "verified": True, "is_online": True, "public_live": False, "private_live": False, "dummy": True, "photo_url": "https://i.pravatar.cc/500?img=44"},
    ]
    out.extend(normalize_host(h) for h in dummy_hosts)
    return {"hosts": out}


@APP.get("/api/host/status/{user_id}")
def host_status(user_id: int):
    h = host_doc(user_id)
    if not h:
        return {
            "is_host": False, "registered": False, "is_online": False,
            "verified": False, "rate": DEFAULT_RATE
        }
    n = normalize_host(h)
    return {
        "is_host": True,
        "registered": True,
        "is_online": n["is_online"],
        "online": n["is_online"],
        "verified": n["verified"],
        "rate": n["rate"],
        "rate_per_minute": n["rate"],
        "public_live": n["public_live"],
        "private_live": n["private_live"],
        "private_live_cost": n["private_live_cost"],
    }


@APP.post("/api/register-host")
def register_host(data: HostRegisterModel):
    ensure_user(data.user_id, data.name)
    existing = host_doc(data.user_id) or {}
    photo = data.photo_url or existing.get("photo_url", "")
    existing_status = existing.get("application_status", "")
    # Do not silently verify from the app. A normal application stays pending until admin approval.
    doc = {
        "user_id": int(data.user_id),
        "name": data.name or user_name(data.user_id),
        "rate": int(data.rate or DEFAULT_RATE),
        "is_host": True,
        "verified": bool(existing.get("verified", False)),
        "approved": bool(existing.get("approved", False)),
        "application_status": "approved" if existing.get("verified") else "pending",
        "is_online": False, "public_live": False, "private_live": False,
        "private_live_cost": int(existing.get("private_live_cost", 30)),
        "photo_url": photo,
        "age": data.age, "country": data.country, "language": data.language,
        "experience": data.experience, "availability": data.availability,
        "bio": data.bio, "social_link": data.social_link,
        "telegram_username": data.telegram_username,
        "applied_at": existing.get("applied_at") or now(),
        "updated_at": now(),
    }
    hosts_col.update_one({"user_id": data.user_id}, {"$set": doc}, upsert=True)
    users_col.update_one({"user_id": data.user_id}, {"$set": {
        "name": doc["name"], "photo_url": photo,
        "host_application": True, "host_approved": bool(doc["verified"]),
        "is_host": bool(doc["verified"]), "verified": bool(doc["verified"]),
    }})
    if not doc["verified"] and existing_status != "pending":
        notify_host_application(doc)
    return {"status": "success", "application_status": doc["application_status"], "host": normalize_host(doc)}


@APP.post("/api/host/update-rate")
def update_host_rate(data: RateModel):
    result = hosts_col.update_one(
        {"user_id": data.user_id, "is_host": True},
        {"$set": {"rate": data.rate, "rate_per_minute": data.rate, "updated_at": now()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Host not registered")
    return {"status": "success", "rate": data.rate}


@APP.post("/api/host/toggle-live/{user_id}")
def toggle_host_live(user_id: int):
    h = host_doc(user_id)
    if not h:
        raise HTTPException(404, "Host not registered")
    new_state = not bool(h.get("is_online", h.get("online", False)))
    hosts_col.update_one({"user_id": user_id}, {"$set": {"is_online": new_state, "online": new_state}})
    users_col.update_one({"user_id": user_id}, {"$set": {"is_online": new_state}})
    return {"status": "success", "is_online": new_state}


# ------------------------- Private booking --------------------

@APP.post("/api/book-slot")
def book_slot(data: BookingModel):
    if REQUIRE_USER_APPROVAL:
        u = ensure_user(data.user_id)
        if not u.get("approved"):
            raise HTTPException(403, "Your account is awaiting admin approval")
    if data.duration_mins not in [1, 2, 5, 10, 15, 20, 30]:
        raise HTTPException(400, "Select a valid session duration")
    h = host_doc(oid_int(data.host_id))
    if oid_int(data.host_id) < 0:
        raise HTTPException(400, "This demo host is from another country and cannot be booked")
    if not h or not h.get("is_host", True):
        raise HTTPException(404, "Host not found")
    host_id = int(h["user_id"])
    if not bool(h.get("is_online", h.get("online", False))):
        raise HTTPException(400, "Host is offline")
    if host_id == data.user_id:
        raise HTTPException(400, "Self booking is not allowed")

    rate = int(h.get("rate") or DEFAULT_RATE)
    real_cost = calculate_cost(rate, data.duration_mins)
    if data.token_cost != real_cost:
        data.token_cost = real_cost

    # Atomic token deduction prevents double spending.
    user = users_col.find_one_and_update(
        {"user_id": int(data.user_id), "tokens": {"$gte": real_cost}},
        {"$inc": {"tokens": -real_cost}},
        return_document=ReturnDocument.AFTER,
    )
    if not user:
        raise HTTPException(400, f"Insufficient tokens. Required: {real_cost}")

    booking_id = uuid.uuid4().hex[:12]
    channel = private_channel(host_id, data.user_id)
    doc = {
        "booking_id": booking_id,
        "user_id": int(data.user_id),
        "host_id": host_id,
        "host_name": h.get("name") or data.host_name or f"Host #{host_id}",
        "host_img": h.get("photo_url", ""),
        "duration_mins": int(data.duration_mins),
        "token_cost": real_cost,
        "channel_name": channel,
        "status": "pending",
        "session_status": "waiting",
        "time": now(),
        "accepted_at": None,
        "user_joined_at": None,
        "host_joined_at": None,
        "session_started_at": None,
        "session_ended_at": None,
        "earnings_credited": False,
        "created_at": now(),
    }
    bookings_col.insert_one(doc)
    return {"status": "success", "booking_id": booking_id, "channel_name": channel,
            "duration_mins": data.duration_mins, "token_cost": real_cost}


def _find_booking(booking_id: str):
    return bookings_col.find_one({"booking_id": booking_id})


@APP.get("/api/user/bookings/{user_id}")
def user_bookings(user_id: int):
    docs = list(bookings_col.find({"user_id": user_id}).sort("created_at", -1).limit(100))
    result = []
    current = now()
    for b in docs:
        b.pop("_id", None)
        if b.get("session_started_at") and b.get("session_status") == "active":
            if current >= b["session_started_at"] + int(b.get("duration_mins", 1)) * 60:
                _complete_expired(b)
                b["status"] = "completed"
                b["session_status"] = "completed"
        result.append(b)
    return {"bookings": result}


@APP.get("/api/host/bookings/{host_id}")
def host_bookings(host_id: int):
    docs = list(bookings_col.find({"host_id": host_id}).sort("created_at", -1).limit(100))
    result = []
    for b in docs:
        b.pop("_id", None)
        b["user_name"] = user_name(int(b.get("user_id")))
        u = users_col.find_one({"user_id": int(b.get("user_id"))}) or {}
        b["user_img"] = u.get("profile_photo", "")
        result.append(b)
    return {"bookings": result}


def accept_common(booking_id: str, host_id: int):
    b = _find_booking(booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")
    if int(b["host_id"]) != int(host_id):
        raise HTTPException(403, "Not your booking")
    if b.get("status") != "pending":
        raise HTTPException(400, "Booking is no longer pending")

    updated = bookings_col.find_one_and_update(
        {"_id": b["_id"], "status": "pending"},
        {"$set": {
            "status": "approved",
            "session_status": "waiting",
            "accepted_at": now(),
            # IMPORTANT: timer remains NULL here.
            "session_started_at": None,
            "user_joined_at": None,
            "host_joined_at": None,
            "session_ended_at": None,
        }},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise HTTPException(409, "Booking was already accepted/rejected")
    return updated


@APP.post("/api/host/accept-booking")
def accept_booking(data: ActionBookingModel):
    if data.host_id is None:
        raise HTTPException(400, "host_id required")
    b = accept_common(data.booking_id, data.host_id)
    return {
        "status": "success",
        "booking_id": b["booking_id"],
        "channel_name": b["channel_name"],
        "duration_mins": b["duration_mins"],
        "host_name": b.get("host_name", ""),
    }


@APP.post("/api/host/reject-booking")
def reject_booking(data: ActionBookingModel):
    b = _find_booking(data.booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")
    if data.host_id is not None and int(b["host_id"]) != int(data.host_id):
        raise HTTPException(403, "Not your booking")
    if b.get("status") != "pending":
        raise HTTPException(400, "Booking is no longer pending")

    bookings_col.update_one({"_id": b["_id"]}, {"$set": {"status": "rejected", "session_status": "rejected"}})
    # Refund exactly once.
    users_col.update_one({"user_id": int(b["user_id"])}, {"$inc": {"tokens": int(b["token_cost"])}})
    return {"status": "success"}


# ------------------------- Exact private session timer --------

@APP.post("/api/start-call")
def start_call(data: StartCallModel):
    role = data.role.lower().strip()
    if role not in ("user", "host"):
        raise HTTPException(400, "role must be user or host")

    b = _find_booking(data.booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")

    participant_id = int(data.user_id)
    if role == "user" and participant_id != int(b["user_id"]):
        raise HTTPException(403, "User is not a participant")
    if role == "host" and participant_id != int(b["host_id"]):
        raise HTTPException(403, "Host is not a participant")
    if b.get("status") not in ("approved", "active"):
        raise HTTPException(400, "Booking is not approved")

    stamp = now()
    field = "user_joined_at" if role == "user" else "host_joined_at"
    bookings_col.update_one(
        {"_id": b["_id"], "$or": [{field: None}, {field: {"$exists": False}}]},
        {"$set": {field: stamp}},
    )

    # Re-read after recording this participant.
    b = bookings_col.find_one({"_id": b["_id"]})
    both = b.get("user_joined_at") is not None and b.get("host_joined_at") is not None

    if both and not b.get("session_started_at"):
        # Atomic: only the first request can establish the official start.
        actual_start = max(float(b["user_joined_at"]), float(b["host_joined_at"]))
        bookings_col.update_one(
            {
                "_id": b["_id"],
                "session_status": "waiting",
                "$or": [{"session_started_at": None}, {"session_started_at": {"$exists": False}}],
            },
            {"$set": {
                "session_started_at": actual_start,
                "session_status": "active",
                "status": "active",
            }},
        )
        b = bookings_col.find_one({"_id": b["_id"]})

    remaining = remaining_for_booking(b)
    return {
        "status": "success",
        "role": role,
        "user_joined": b.get("user_joined_at") is not None,
        "host_joined": b.get("host_joined_at") is not None,
        "session_started_at": b.get("session_started_at"),
        "remaining_seconds": remaining,
        "session_status": b.get("session_status", "waiting"),
    }


@APP.get("/api/session/{booking_id}")
def get_session(booking_id: str):
    b = _find_booking(booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")

    remaining = remaining_for_booking(b)
    if b.get("session_started_at") and remaining is not None and remaining <= 0:
        _complete_expired(b)
        b = bookings_col.find_one({"_id": b["_id"]}) or b
        remaining = 0

    return {
        "status": "success",
        "booking_id": booking_id,
        "session_status": b.get("session_status", "waiting"),
        "booking_status": b.get("status"),
        "session_started_at": b.get("session_started_at"),
        "user_joined": b.get("user_joined_at") is not None,
        "host_joined": b.get("host_joined_at") is not None,
        "remaining_seconds": remaining if remaining is not None else -1,
        "duration_mins": int(b.get("duration_mins", 1)),
    }


def credit_host_once(b):
    if b.get("earnings_credited"):
        return
    gross = float(b.get("token_cost", 0))
    host_share = gross * (1.0 - PLATFORM_CUT)
    agency = host_share * AGENCY_CUT
    final_host = host_share - agency

    result = bookings_col.update_one(
        {"_id": b["_id"], "earnings_credited": {"$ne": True}},
        {"$set": {
            "earnings_credited": True,
            "platform_share": gross * PLATFORM_CUT,
            "host_share": host_share,
            "agency_commission": agency,
            "host_final": final_host,
        }},
    )
    if result.modified_count:
        hosts_col.update_one({"user_id": int(b["host_id"])}, {"$inc": {"earnings": final_host}})
        users_col.update_one({"user_id": int(b["host_id"])}, {"$inc": {"earnings": final_host}})


def _complete_expired(b):
    bookings_col.update_one(
        {"_id": b["_id"], "session_status": {"$in": ["active", "waiting"]}},
        {"$set": {"status": "completed", "session_status": "completed", "session_ended_at": now()}},
    )
    credit_host_once(b)
    hosts_col.update_one({"user_id": int(b["host_id"])}, {"$set": {"is_online": True, "online": True}})


@APP.post("/api/complete-booking")
def complete_booking(data: CompleteBookingModel):
    b = _find_booking(data.booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")
    if data.user_id is not None and int(data.user_id) not in [int(b["user_id"]), int(b["host_id"])]:
        raise HTTPException(403, "Not a participant")
    bookings_col.update_one(
        {"_id": b["_id"], "session_status": {"$ne": "completed"}},
        {"$set": {"status": "completed", "session_status": "completed", "session_ended_at": now()}},
    )
    credit_host_once(b)
    hosts_col.update_one({"user_id": int(b["host_id"])}, {"$set": {"is_online": True, "online": True}})
    return {"status": "success"}


# ------------------------- Agora --------------------------------

def make_agora_token(channel: str, uid: int, ttl: int = 3600):
    if not AGORA_APP_ID or not AGORA_APP_CERTIFICATE:
        raise HTTPException(500, "Agora credentials are not configured")
    if RtcTokenBuilder is None:
        raise HTTPException(500, "agora-token-builder package is missing")






