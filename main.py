import os
import time
import uuid
import base64
import re
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
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

PLATFORM_CUT = float(os.getenv("PLATFORM_CUT", "0.30"))
AGENCY_CUT = float(os.getenv("AGENCY_CUT", "0.10"))
DEFAULT_RATE = int(os.getenv("DEFAULT_RATE", "30"))
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

try:
    users_col.create_index("user_id", unique=True)
    hosts_col.create_index("user_id", unique=True)
    bookings_col.create_index("booking_id", unique=True)
    bookings_col.create_index([("user_id", 1), ("status", 1)])
    bookings_col.create_index([("host_id", 1), ("status", 1)])
    live_col.create_index("host_user_id", unique=True)
except Exception:
    pass


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


class LiveStartModel(BaseModel):
    host_user_id: int
    title: str = "🔴 Public Live"
    private_enabled: bool = False
    private_token_cost: int = 30


class LiveJoinModel(BaseModel):
    user_id: int
    host_user_id: int


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
    return bool(h and (h.get("verified", True) or h.get("is_host", True)))


def ensure_user(user_id: int, name: str = ""):
    users_col.update_one(
        {"user_id": int(user_id)},
        {"$setOnInsert": {
            "user_id": int(user_id),
            "name": name or f"User #{user_id}",
            "tokens": 0,
            "earnings": 0.0,
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


# ------------------------- Health -----------------------------

@APP.get("/")
def root():
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

@APP.get("/api/hosts")
def get_hosts():
    out = []
    seen = set()
    for h in hosts_col.find({"is_host": True}).sort("verified", -1):
        uid = int(h["user_id"])
        if uid not in seen:
            seen.add(uid)
            out.append(normalize_host(h))

    # Keep the endpoint useful even if hosts are stored only in users.
    for h in users_col.find({"is_host": True}).sort("verified", -1):
        uid = int(h["user_id"])
        if uid not in seen:
            seen.add(uid)
            out.append(normalize_host(h))
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
    existing = host_doc(data.user_id)
    photo = data.photo_url or (existing or {}).get("photo_url", "")
    doc = {
        "user_id": int(data.user_id),
        "name": data.name or user_name(data.user_id),
        "rate": int(data.rate or DEFAULT_RATE),
        "is_host": True,
        "verified": bool((existing or {}).get("verified", False)),
        "is_online": False,
        "public_live": False,
        "private_live": False,
        "private_live_cost": 30,
        "photo_url": photo,
        "updated_at": now(),
    }
    hosts_col.update_one({"user_id": data.user_id}, {"$set": doc}, upsert=True)
    users_col.update_one({"user_id": data.user_id}, {"$set": {
        "is_host": True, "name": doc["name"], "rate": doc["rate"],
        "verified": doc["verified"], "photo_url": photo
    }})
    return {"status": "success", "host": normalize_host(doc)}


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
    if data.duration_mins not in [1, 2, 5, 10, 15, 20, 30]:
        raise HTTPException(400, "Select a valid session duration")
    h = host_doc(oid_int(data.host_id))
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
    expire = int(time.time()) + int(ttl)
    token = RtcTokenBuilder.buildTokenWithUid(
        AGORA_APP_ID,
        AGORA_APP_CERTIFICATE,
        channel,
        int(uid),
        Role_Publisher,
        expire,
    )
    return token


@APP.get("/api/agora-token")
def agora_token(channelName: str, uid: int, role: str = "publisher",
                booking_id: str = "", user_id: int = 0):
    # Public live channel
    if channelName.startswith("host_live_"):
        host_id = oid_int(channelName.replace("host_live_", ""))
        if not host_id or not public_host_exists(host_id):
            raise HTTPException(404, "Live host not found")
        return {"token": make_agora_token(channelName, uid), "appId": AGORA_APP_ID}

    # Private booking channel must be tied to a real booking.
    if not booking_id:
        raise HTTPException(400, "booking_id required for private call")
    b = _find_booking(booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")
    if channelName != b.get("channel_name"):
        raise HTTPException(403, "Invalid channel")
    if int(uid) not in [int(b["user_id"]), int(b["host_id"])]:
        raise HTTPException(403, "Not a participant")
    if user_id and int(user_id) != int(uid):
        raise HTTPException(403, "Invalid user")

    return {"token": make_agora_token(channelName, uid), "appId": AGORA_APP_ID}


# ------------------------- Chat / Gifts -------------------------

@APP.get("/api/get-chat/{channel}")
def get_chat(channel: str):
    rows = list(chats_col.find({"channel": channel}).sort("created_at", 1).limit(100))
    for r in rows:
        r.pop("_id", None)
    return {"messages": rows}


@APP.post("/api/send-chat")
def send_chat(data: ChatModel):
    message = data.message.strip()
    if not message or len(message) > 500:
        raise HTTPException(400, "Invalid message")
    doc = {
        "channel": data.channel,
        "user_id": data.user_id,
        "name": user_name(data.user_id),
        "message": message,
        "created_at": now(),
    }
    chats_col.insert_one(doc)
    doc.pop("_id", None)
    return {"status": "success", "message": doc}


@APP.post("/api/send-gift")
def send_gift(data: GiftModel):
    if data.sender_id == data.receiver_id:
        raise HTTPException(400, "Invalid receiver")
    if data.token_cost < 1:
        raise HTTPException(400, "Invalid gift cost")

    sender = users_col.find_one_and_update(
        {"user_id": data.sender_id, "tokens": {"$gte": data.token_cost}},
        {"$inc": {"tokens": -data.token_cost}},
        return_document=ReturnDocument.AFTER,
    )
    if not sender:
        raise HTTPException(400, "Insufficient tokens")

    # Gift earning: 70% host share by default.
    receiver_share = data.token_cost * (1.0 - PLATFORM_CUT)
    users_col.update_one({"user_id": data.receiver_id}, {"$inc": {"earnings": receiver_share}})
    hosts_col.update_one({"user_id": data.receiver_id}, {"$inc": {"earnings": receiver_share}})

    gift = {
        "gift_id": uuid.uuid4().hex[:10],
        "channel": data.channel,
        "sender_id": data.sender_id,
        "receiver_id": data.receiver_id,
        "gift_name": data.gift_name,
        "token_cost": data.token_cost,
        "created_at": now(),
    }
    gifts_col.insert_one(gift)
    gift.pop("_id", None)
    return {"status": "success", "gift": gift, "sender_tokens": int(sender.get("tokens", 0))}


# ------------------------- Public Live --------------------------

@APP.post("/api/public-live/start")
def public_live_start(data: LiveStartModel):
    h = host_doc(data.host_user_id)
    if not h:
        raise HTTPException(404, "Host not registered")
    channel = f"host_live_{data.host_user_id}"
    doc = {
        "host_user_id": int(data.host_user_id),
        "channel_name": channel,
        "title": data.title[:100],
        "private_enabled": bool(data.private_enabled),
        "private_live_cost": int(max(1, data.private_token_cost)),
        "started_at": now(),
        "active": True,
    }
    live_col.update_one({"host_user_id": data.host_user_id}, {"$set": doc}, upsert=True)
    hosts_col.update_one({"user_id": data.host_user_id}, {"$set": {
        "public_live": True, "private_live": bool(data.private_enabled),
        "private_live_cost": int(max(1, data.private_token_cost)),
        "is_online": True, "online": True
    }})
    return {"status": "success", **doc}


@APP.post("/api/public-live/stop/{host_user_id}")
def public_live_stop(host_user_id: int):
    live_col.update_one({"host_user_id": host_user_id}, {"$set": {"active": False, "ended_at": now()}})
    hosts_col.update_one({"user_id": host_user_id}, {"$set": {"public_live": False, "private_live": False}})
    return {"status": "success"}


@APP.get("/api/public-live")
def public_lives():
    rows = list(live_col.find({"active": True}).sort("started_at", -1))
    out = []
    for x in rows:
        h = host_doc(int(x["host_user_id"])) or {}
        out.append({
            "host_user_id": int(x["host_user_id"]),
            "host_name": h.get("name") or user_name(int(x["host_user_id"])),
            "host_img": h.get("photo_url", ""),
            "channel_name": x["channel_name"],
            "title": x.get("title", "Public Live"),
            "private_enabled": bool(x.get("private_enabled", False)),
            "private_live_cost": int(x.get("private_live_cost", 30)),
        })
    return {"lives": out}


@APP.post("/api/public-live/join-private")
def join_private_live(data: LiveJoinModel):
    live = live_col.find_one({"host_user_id": data.host_user_id, "active": True})
    if not live:
        raise HTTPException(404, "Live is not active")
    if not live.get("private_enabled"):
        raise HTTPException(400, "Private Live is disabled")
    cost = int(live.get("private_live_cost", 30))

    # Deduct join fee once per user/live session.
    join_key = f"{data.host_user_id}:{data.user_id}:{int(live.get('started_at', 0))}"
    existing = db["live_private_joins"].find_one({"join_key": join_key})
    if not existing:
        sender = users_col.find_one_and_update(
            {"user_id": data.user_id, "tokens": {"$gte": cost}},
            {"$inc": {"tokens": -cost}},
            return_document=ReturnDocument.AFTER,
        )
        if not sender:
            raise HTTPException(400, "Insufficient tokens")
        db["live_private_joins"].insert_one({
            "join_key": join_key,
            "user_id": data.user_id,
            "host_user_id": data.host_user_id,
            "cost": cost,
            "created_at": now(),
        })
        hosts_col.update_one({"user_id": data.host_user_id},
                             {"$inc": {"earnings": cost * (1 - PLATFORM_CUT)}})

    return {
        "status": "success",
        "channel_name": live["channel_name"],
        "cost": cost,
        "token": make_agora_token(live["channel_name"], data.user_id),
        "appId": AGORA_APP_ID,
    }


# ------------------------- Recharge / Withdraw -----------------

@APP.post("/api/recharge")
def recharge(data: RechargeModel):
    if data.amount < 1:
        raise HTTPException(400, "Invalid amount")
    screenshot_url = ""
    if data.screenshot:
        screenshot_url = save_base64_image(data.screenshot, f"recharge_{data.user_id}")
    recharge_id = uuid.uuid4().hex
    doc = {
        "recharge_id": recharge_id,
        "user_id": data.user_id,
        "amount": float(data.amount),
        "transaction_id": data.transaction_id.strip(),
        "screenshot_url": screenshot_url,
        "status": "pending",
        "created_at": now(),
    }
    recharges_col.insert_one(doc)
    return {"status": "success", "recharge_id": recharge_id}


@APP.post("/api/withdraw")
def withdraw(data: WithdrawModel):
    host = host_doc(data.user_id)
    if not host:
        raise HTTPException(403, "Only registered hosts can withdraw")
    if data.amount < 700:
        raise HTTPException(400, "Minimum withdrawal is ₹700")
    today_start = now() - (now() % 86400)
    used = sum(float(x.get("amount", 0)) for x in withdrawals_col.find({
        "user_id": data.user_id, "created_at": {"$gte": today_start},
        "status": {"$in": ["pending", "approved", "paid"]}
    }))
    if used + data.amount > 3000:
        raise HTTPException(400, "Daily withdrawal limit is ₹3000")

    # Reserve earnings atomically.
    u = users_col.find_one_and_update(
        {"user_id": data.user_id, "earnings": {"$gte": data.amount}},
        {"$inc": {"earnings": -data.amount}},
        return_document=ReturnDocument.AFTER,
    )
    if not u:
        # Hosts collection may be the source of truth for earnings.
        h = hosts_col.find_one_and_update(
            {"user_id": data.user_id, "earnings": {"$gte": data.amount}},
            {"$inc": {"earnings": -data.amount}},
            return_document=ReturnDocument.AFTER,
        )
        if not h:
            raise HTTPException(400, "Insufficient earnings")

    wid = uuid.uuid4().hex
    withdrawals_col.insert_one({
        "withdrawal_id": wid,
        "user_id": data.user_id,
        "amount": float(data.amount),
        "upi_id": data.upi_id.strip(),
        "status": "pending",
        "created_at": now(),
    })
    return {"status": "success", "withdrawal_id": wid}


# ------------------------- Background expiry -------------------

def expiry_worker():
    while True:
        try:
            cutoff = now()
            for b in bookings_col.find({
                "session_started_at": {"$ne": None},
                "session_status": "active",
            }).limit(200):
                if cutoff >= float(b["session_started_at"]) + int(b.get("duration_mins", 1)) * 60:
                    _complete_expired(b)
        except Exception:
            pass
        time.sleep(2)


threading.Thread(target=expiry_worker, daemon=True).start()


# ------------------------- Start --------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(APP, host="0.0.0.0", port=port)







