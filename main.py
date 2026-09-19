# ============================================================
# 🚀 VYNORA LIVE 1v1 - PROFESSIONAL BACKEND
# ============================================================

import os
import time
import uuid
import asyncio
import logging
import traceback
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from database import (
    users_col,
    hosts_col,
    bookings_col,
    recharges_col,
    withdrawals_col,
    chats_col,
)

# ============================================================
# 🎥 AGORA
# ============================================================

try:
    from agora_token_builder import RtcTokenBuilder
except Exception:
    RtcTokenBuilder = None


# ============================================================
# ⚙️ ENVIRONMENT
# ============================================================

load_dotenv()

APP_NAME = "Vynora Live 1v1"

PORT = int(
    os.getenv("PORT", "8000")
)

BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    ""
)

ADMIN_TELEGRAM_ID = os.getenv(
    "ADMIN_TELEGRAM_ID",
    ""
)

AGORA_APP_ID = os.getenv(
    "AGORA_APP_ID",
    ""
)

AGORA_APP_CERTIFICATE = os.getenv(
    "AGORA_APP_CERTIFICATE",
    ""
)

WEB_APP_URL = os.getenv(
    "WEB_APP_URL",
    ""
)

GROUP_1_ID = os.getenv(
    "GROUP_1_ID",
    ""
)

GROUP_2_ID = os.getenv(
    "GROUP_2_ID",
    ""
)

GROUP_3_ID = os.getenv(
    "GROUP_3_ID",
    ""
)

PLATFORM_FEE_PERCENT = float(
    os.getenv(
        "PLATFORM_FEE_PERCENT",
        "30"
    )
)

HOST_EARNING_PERCENT = (
    100 - PLATFORM_FEE_PERCENT
)

DEFAULT_DURATION_MINS = int(
    os.getenv(
        "DEFAULT_DURATION_MINS",
        "10"
    )
)

DEFAULT_HOST_RATE = float(
    os.getenv(
        "DEFAULT_HOST_RATE",
        "1"
    )
)

UPLOAD_DIR = os.getenv(
    "UPLOAD_DIR",
    "static/uploads"
)

os.makedirs(
    UPLOAD_DIR,
    exist_ok=True
)


# ============================================================
# 📝 LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    )
)

logger = logging.getLogger(
    APP_NAME
)


# ============================================================
# 🚀 FASTAPI
# ============================================================

app = FastAPI(
    title=APP_NAME,
    version="2.1.0",
    description=(
        "Professional Vynora Live "
        "1v1 Video Call Backend"
    )
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# 🧰 HELPER FUNCTIONS
# ============================================================

def now_ts():
    return time.time()


def safe_int(
    value: Any,
    default: int = 0
):
    try:
        return int(value)
    except Exception:
        return default


def safe_float(
    value: Any,
    default: float = 0
):
    try:
        return float(value)
    except Exception:
        return default


def clean_host_id(
    host_id: Any
):
    return (
        str(host_id)
        .replace("host_", "")
        .replace("h_", "")
    )


def serialize_doc(
    doc: Optional[dict]
):
    if not doc:
        return None

    result = dict(doc)

    if "_id" in result:
        result["_id"] = str(
            result["_id"]
        )

    return result


def serialize_many(cursor):
    return [
        serialize_doc(item)
        for item in cursor
    ]


def get_user(
    user_id: int
):
    return users_col.find_one({
        "user_id": int(user_id)
    })


def get_host(
    host_id: Any
):
    host = hosts_col.find_one({
        "host_id": str(host_id)
    })

    if not host:
        host = hosts_col.find_one({
            "user_id":
                safe_int(
                    host_id,
                    -1
                )
        })

    return host


def get_booking(
    booking_id: str
):
    return bookings_col.find_one({
        "booking_id":
            str(booking_id)
    })


def calculate_host_earning(
    token_cost: float
):
    return round(
        float(token_cost)
        * HOST_EARNING_PERCENT
        / 100,
        2
    )


# ============================================================
# 🤖 TELEGRAM API
# ============================================================

def telegram_api(
    method: str,
    payload: dict
):

    if not BOT_TOKEN:

        logger.warning(
            "⚠️ BOT_TOKEN is not configured."
        )

        return None

    try:

        import requests

        url = (
            "https://api.telegram.org/"
            f"bot{BOT_TOKEN}/{method}"
        )

        response = requests.post(
            url,
            json=payload,
            timeout=15
        )

        response.raise_for_status()

        return response.json()

    except Exception as e:

        logger.error(
            "Telegram API Error: %s",
            e
        )

        return None


def send_telegram_message(
    chat_id: int,
    text: str,
    reply_markup: Optional[dict] = None
):

    payload = {
        "chat_id": int(chat_id),
        "text": text,
        "parse_mode": "HTML"
    }

    if reply_markup:
        payload["reply_markup"] = (
            reply_markup
        )

    return telegram_api(
        "sendMessage",
        payload
    )


def answer_callback_query(
    callback_query_id: str
):

    if not callback_query_id:
        return None

    return telegram_api(
        "answerCallbackQuery",
        {
            "callback_query_id":
                callback_query_id
        }
    )


# ============================================================
# 🏠 HOME
# ============================================================

@app.get("/")
def root():

    if os.path.exists(
        "static/index.html"
    ):

        return FileResponse(
            "static/index.html"
        )

    return {
        "status": "online",
        "app": APP_NAME,
        "version": "2.1.0",
        "message":
            "🚀 Vynora Live Backend Running"
    }


@app.get("/health")
def health():

    return {
        "status": "healthy",
        "timestamp": now_ts()
    }


# ============================================================
# 👤 USER
# ============================================================

class UserModel(BaseModel):

    user_id: int

    name: Optional[str] = ""

    username: Optional[str] = ""


@app.post("/api/user/register")
def register_user(
    data: UserModel
):

    existing = get_user(
        data.user_id
    )

    update_data = {
        "name":
            data.name,

        "username":
            data.username,

        "updated_at":
            now_ts()
    }

    if existing:

        users_col.update_one(
            {
                "user_id":
                    data.user_id
            },
            {
                "$set":
                    update_data
            }
        )

        return {
            "status":
                "success",

            "message":
                "👤 User updated successfully"
        }

    users_col.insert_one({

        "user_id":
            data.user_id,

        "name":
            data.name,

        "username":
            data.username,

        "tokens":
            0,

        "created_at":
            now_ts(),

        "updated_at":
            now_ts()
    })

    return {
        "status":
            "success",

        "message":
            "🎉 User registered successfully"
    }


@app.get("/api/user/{user_id}")
def user_details(
    user_id: int
):

    user = get_user(
        user_id
    )

    if not user:

        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    return {
        "status":
            "success",

        "user":
            serialize_doc(user)
    }


@app.get("/api/user/{user_id}/wallet")
def user_wallet(
    user_id: int
):

    user = get_user(
        user_id
    )

    if not user:

        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    return {
        "status":
            "success",

        "tokens":
            safe_float(
                user.get(
                    "tokens",
                    0
                )
            )
    }


# ============================================================
# 👩 HOST
# ============================================================

class HostRegisterModel(BaseModel):

    user_id: int

    host_id: Optional[str] = None

    name: str

    username: Optional[str] = ""

    rate: float = (
        DEFAULT_HOST_RATE
    )

    duration_mins: int = Field(
        DEFAULT_DURATION_MINS,
        ge=1,
        le=180
    )


@app.post("/api/host/register")
def register_host(
    data: HostRegisterModel
):

    host_id = (
        data.host_id
        or f"host_{data.user_id}"
    )

    host_doc = {

        "host_id":
            host_id,

        "user_id":
            data.user_id,

        "name":
            data.name,

        "username":
            data.username,

        "rate":
            data.rate,

        "duration_mins":
            data.duration_mins,

        "online":
            False,

        "approved":
            True,

        "updated_at":
            now_ts()
    }

    existing = hosts_col.find_one({
        "host_id":
            host_id
    })

    if existing:

        hosts_col.update_one(
            {
                "_id":
                    existing["_id"]
            },
            {
                "$set":
                    host_doc
            }
        )

    else:

        host_doc["created_at"] = (
            now_ts()
        )

        hosts_col.insert_one(
            host_doc
        )

    return {
        "status":
            "success",

        "host_id":
            host_id,

        "message":
            "👩 Host profile saved successfully"
    }


class HostStatusModel(BaseModel):

    host_id: str

    online: bool


@app.post("/api/host/status")
def host_status(
    data: HostStatusModel
):

    result = hosts_col.update_one(
        {
            "host_id":
                str(data.host_id)
        },
        {
            "$set": {

                "online":
                    data.online,

                "updated_at":
                    now_ts()
            }
        }
    )

    if result.matched_count == 0:

        raise HTTPException(
            status_code=404,
            detail="Host not found"
        )

    return {

        "status":
            "success",

        "online":
            data.online,

        "message": (
            "🟢 Host is now online"
            if data.online
            else
            "🔴 Host is now offline"
        )
    }


@app.get("/api/hosts")
def get_hosts():

    hosts = list(
        hosts_col.find({
            "approved": {
                "$ne": False
            }
        })
    )

    output = []

    for host in hosts:

        item = serialize_doc(
            host
        )

        item["host_id"] = str(
            host.get(
                "host_id",
                host.get(
                    "user_id",
                    ""
                )
            )
        )

        item["rate"] = safe_float(
            host.get(
                "rate",
                DEFAULT_HOST_RATE
            )
        )

        item["duration_mins"] = safe_int(
            host.get(
                "duration_mins",
                DEFAULT_DURATION_MINS
            )
        )

        item["online"] = bool(
            host.get(
                "online",
                False
            )
        )

        output.append(
            item
        )

    return {
        "status":
            "success",

        "hosts":
            output
    }


# ============================================================
# 📞 BOOKING
# ============================================================

class BookingModel(BaseModel):

    user_id: int

    host_id: str

    host_name: str

    duration_mins: int = Field(
        DEFAULT_DURATION_MINS,
        ge=1,
        le=180
    )

    token_cost: float = Field(
        0,
        ge=0
    )


@app.post("/api/book-slot")
def book_slot(
    data: BookingModel
):

    user = get_user(
        data.user_id
    )

    if not user:

        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    host = get_host(
        data.host_id
    )

    if not host:

        raise HTTPException(
            status_code=404,
            detail="Host not found"
        )

    # --------------------------------------------------------
    # 📌 Host plan duration
    # --------------------------------------------------------

    duration = safe_int(
        host.get(
            "duration_mins",
            data.duration_mins
        )
    )

    # --------------------------------------------------------
    # 💰 Calculate booking cost
    # --------------------------------------------------------

    if data.token_cost > 0:

        token_cost = float(
            data.token_cost
        )

    else:

        host_rate = safe_float(
            host.get(
                "rate",
                DEFAULT_HOST_RATE
            )
        )

        token_cost = round(
            host_rate * duration,
            2
        )

    available_tokens = safe_float(
        user.get(
            "tokens",
            0
        )
    )

    if available_tokens < token_cost:

        raise HTTPException(
            status_code=400,
            detail=(
                "❌ Insufficient tokens. "
                f"Required: {token_cost}, "
                f"Available: {available_tokens}"
            )
        )

    # --------------------------------------------------------
    # 🔐 Atomic wallet deduction
    # --------------------------------------------------------

    wallet_result = users_col.update_one(

        {
            "user_id":
                data.user_id,

            "tokens": {
                "$gte":
                    token_cost
            }
        },

        {
            "$inc": {
                "tokens":
                    -token_cost
            }
        }
    )

    if wallet_result.modified_count != 1:

        raise HTTPException(
            status_code=400,
            detail=(
                "❌ Token deduction failed. "
                "Please try again."
            )
        )

    # --------------------------------------------------------
    # 🆔 Unique booking ID
    # --------------------------------------------------------

    booking_id = str(
        uuid.uuid4()
    )[:12]

    clean_id = clean_host_id(
        data.host_id
    )

    channel_name = (
        f"private_call_"
        f"{clean_id}_"
        f"{data.user_id}_"
        f"{booking_id}"
    )

    current_time = now_ts()

    # ========================================================
    # ⏱️ IMPORTANT TIMER FIX
    #
    # Booking time is NOT call start time.
    #
    # session_started_at = None
    #
    # Timer will start only when:
    #
    # 👤 USER JOINED
    # +
    # 👩 HOST JOINED
    #
    # ========================================================

    booking_doc = {

        "booking_id":
            booking_id,

        "user_id":
            int(data.user_id),

        "host_id":
            str(data.host_id),

        "host_name":
            data.host_name,

        "duration_mins":
            int(duration),

        "token_cost":
            float(token_cost),

        "channel_name":
            channel_name,

        "status":
            "pending",

        "session_status":
            "waiting",

        "created_at":
            current_time,

        "accepted_at":
            None,

        "user_joined_at":
            None,

        "host_joined_at":
            None,

        "session_started_at":
            None,

        "session_ended_at":
            None,

        "call_started_at":
            None,

        "earnings_credited":
            False,

        "last_updated_at":
            current_time
    }

    bookings_col.insert_one(
        booking_doc
    )

    # --------------------------------------------------------
    # 📩 Notify host
    # --------------------------------------------------------

    host_user_id = host.get(
        "user_id"
    )

    if host_user_id:

        keyboard = {

            "inline_keyboard": [[

                {
                    "text":
                        "✅ Accept Call",

                    "callback_data":
                        f"accept_bk_{booking_id}"
                },

                {
                    "text":
                        "❌ Reject",

                    "callback_data":
                        f"reject_bk_{booking_id}"
                }

            ]]
        }

        send_telegram_message(

            int(host_user_id),

            (
                "📞 <b>New Private Call Request</b>\n\n"

                f"👤 User ID: "
                f"<code>{data.user_id}</code>\n"

                f"⏱️ Duration: "
                f"<b>{duration} min</b>\n"

                f"💰 Tokens: "
                f"<b>{token_cost}</b>\n\n"

                "👇 Please choose:"
            ),

            keyboard
        )

    return {

        "status":
            "success",

        "booking_id":
            booking_id,

        "channel_name":
            channel_name,

        "duration_mins":
            duration,

        "token_cost":
            token_cost,

        "session_started_at":
            None,

        "message":
            (
                "📞 Call request sent successfully. "
                "⏳ Timer starts only when "
                "both User and Host join."
            )
    }


# ============================================================
# 📋 USER BOOKINGS
# ============================================================

@app.get(
    "/api/user/bookings/{user_id}"
)
def user_bookings(
    user_id: int
):

    bookings = list(

        bookings_col.find({
            "user_id":
                int(user_id)
        }).sort(
            "created_at",
            -1
        )
    )

    return {

        "status":
            "success",

        "bookings":
            serialize_many(
                bookings
            )
    }


# ============================================================
# 📋 HOST BOOKINGS
# ============================================================

@app.get(
    "/api/host/bookings/{host_id}"
)
def host_bookings(
    host_id: str
):

    bookings = list(

        bookings_col.find({
            "host_id":
                str(host_id)
        }).sort(
            "created_at",
            -1
        )
    )

    return {

        "status":
            "success",

        "bookings":
            serialize_many(
                bookings
            )
    }


# ============================================================
# 💰 HOST EARNING
# ============================================================

def credit_host_earning(
    booking: dict
):

    if not booking:
        return False

    if booking.get(
        "earnings_credited",
        False
    ):

        return False

    host = get_host(
        booking.get(
            "host_id"
        )
    )

    if not host:
        return False

    host_user_id = host.get(
        "user_id"
    )

    if not host_user_id:
        return False

    token_cost = safe_float(
        booking.get(
            "token_cost",
            0
        )
    )

    host_earning = (
        calculate_host_earning(
            token_cost
        )
    )

    if host_earning <= 0:
        return False

    # --------------------------------------------------------
    # 🔐 Prevent duplicate earnings
    # --------------------------------------------------------

    result = bookings_col.update_one(

        {
            "_id":
                booking["_id"],

            "earnings_credited":
                False
        },

        {
            "$set": {

                "earnings_credited":
                    True,

                "host_earning":
                    host_earning,

                "platform_fee":
                    round(
                        token_cost
                        - host_earning,
                        2
                    ),

                "earning_credited_at":
                    now_ts()
            }
        }
    )

    if result.modified_count != 1:
        return False

    users_col.update_one(

        {
            "user_id":
                safe_int(
                    host_user_id
                )
        },

        {
            "$inc": {
                "tokens":
                    host_earning
            }
        }
    )

    send_telegram_message(

        int(host_user_id),

        (
            "💰 <b>Call Earning Added!</b>\n\n"

            f"💵 Booking Value: "
            f"<b>{token_cost}</b>\n"

            f"🏦 Platform Fee: "
            f"<b>"
            f"{round(token_cost - host_earning, 2)}"
            f"</b>\n"

            f"👩‍💼 Your Earning: "
            f"<b>{host_earning}</b>\n\n"

            "✅ Amount added to your wallet."
        )
    )

    return True


# ============================================================
# ✅ ACCEPT BOOKING
# ============================================================

def approve_booking(
    booking: dict
):

    if not booking:

        return {
            "status":
                "error",

            "message":
                "Booking not found"
        }

    if booking.get(
        "status"
    ) != "pending":

        return {
            "status":
                "error",

            "message":
                "⚠️ Booking already processed."
        }

    accepted_at = now_ts()

    # --------------------------------------------------------
    # ⛔ DO NOT START SESSION TIMER HERE
    # --------------------------------------------------------

    result = bookings_col.update_one(

        {
            "_id":
                booking["_id"],

            "status":
                "pending"
        },

        {
            "$set": {

                "status":
                    "approved",

                "session_status":
                    "waiting",

                "accepted_at":
                    accepted_at,

                "last_updated_at":
                    accepted_at
            }
        }
    )

    if result.modified_count != 1:

        return {
            "status":
                "error",

            "message":
                "Booking was already processed."
        }

    # --------------------------------------------------------
    # 💰 Preserve host earning behavior
    # --------------------------------------------------------

    updated_booking = bookings_col.find_one({
        "_id":
            booking["_id"]
    })

    credit_host_earning(
        updated_booking
    )

    # --------------------------------------------------------
    # 📩 Notify user
    # --------------------------------------------------------

    send_telegram_message(

        int(
            booking["user_id"]
        ),

        (
            "📞 <b>Your Call Request Was Accepted!</b>\n\n"

            "👩 Host has accepted your call.\n\n"

            "⏳ <b>Your timer has NOT started yet.</b>\n"

            "🎥 Timer will start when both "
            "participants join the call.\n\n"

            "👉 Please tap <b>Answer Call</b>."
        )
    )

    return {

        "status":
            "success",

        "message":
            "✅ Booking approved",

        "booking_id":
            booking["booking_id"]
    }


class ActionBookingModel(BaseModel):

    booking_id: str

    host_id: Optional[str] = None


@app.post(
    "/api/host/accept-booking"
)
def accept_booking(
    data: ActionBookingModel
):

    booking = get_booking(
        data.booking_id
    )

    if not booking:

        raise HTTPException(
            status_code=404,
            detail="Booking not found"
        )

    if data.host_id:

        host = get_host(
            data.host_id
        )

        if (
            not host
            or str(
                host.get("host_id")
            )
            != str(
                booking.get("host_id")
            )
        ):

            raise HTTPException(
                status_code=403,
                detail=(
                    "Not authorized "
                    "for this booking."
                )
            )

    return approve_booking(
        booking
    )


# ============================================================
# ❌ REJECT BOOKING
# ============================================================

def reject_booking(
    booking: dict
):

    if not booking:

        return {
            "status":
                "error",

            "message":
                "Booking not found"
        }

    if booking.get(
        "status"
    ) != "pending":

        return {
            "status":
                "error",

            "message":
                "Booking already processed."
        }

    token_cost = safe_float(
        booking.get(
            "token_cost",
            0
        )
    )

    ended_at = now_ts()

    result = bookings_col.update_one(

        {
            "_id":
                booking["_id"],

            "status":
                "pending"
        },

        {
            "$set": {

                "status":
                    "rejected",

                "session_status":
                    "ended",

                "session_ended_at":
                    ended_at,

                "last_updated_at":
                    ended_at
            }
        }
    )

    if result.modified_count != 1:

        return {
            "status":
                "error",

            "message":
                "Booking already processed."
        }

    # --------------------------------------------------------
    # 💰 Refund tokens
    # --------------------------------------------------------

    if token_cost > 0:

        users_col.update_one(

            {
                "user_id":
                    int(
                        booking["user_id"]
                    )
            },

            {
                "$inc": {
                    "tokens":
                        token_cost
                }
            }
        )

    send_telegram_message(

        int(
            booking["user_id"]
        ),

        (
            "❌ <b>Call Request Rejected</b>\n\n"

            f"💰 <b>{token_cost}</b> tokens "
            "have been refunded to your wallet."
        )
    )

    return {

        "status":
            "success",

        "message":
            "❌ Booking rejected and tokens refunded."
    }


@app.post(
    "/api/host/reject-booking"
)
def reject_booking_api(
    data: ActionBookingModel
):

    booking = get_booking(
        data.booking_id
    )

    if not booking:

        raise HTTPException(
            status_code=404,
            detail="Booking not found"
        )

    return reject_booking(
        booking
    )


# ============================================================
# 🎥 START CALL
# ============================================================

class StartCallModel(BaseModel):

    booking_id: str

    user_id: int

    role: str


@app.post(
    "/api/start-call"
)
def start_call(
    data: StartCallModel
):

    role = (
        data.role
        .lower()
        .strip()
    )

    if role not in (
        "user",
        "host"
    ):

        raise HTTPException(
            status_code=400,
            detail="Invalid role"
        )

    booking = get_booking(
        data.booking_id
    )

    if not booking:

        raise HTTPException(
            status_code=404,
            detail="Booking not found"
        )

    # --------------------------------------------------------
    # Booking must be approved
    # --------------------------------------------------------

    if booking.get(
        "status"
    ) not in (
        "approved",
        "active"
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "Call is not approved yet."
            )
        )

    # ========================================================
    # 🔐 USER VALIDATION
    # ========================================================

    if role == "user":

        if safe_int(
            booking.get("user_id")
        ) != int(
            data.user_id
        ):

            raise HTTPException(
                status_code=403,
                detail=(
                    "User is not part "
                    "of this booking."
                )
            )

        participant_field = (
            "user_joined_at"
        )

    # ========================================================
    # 🔐 HOST VALIDATION
    # ========================================================

    else:

        host = get_host(
            booking.get(
                "host_id"
            )
        )

        if (
            not host
            or safe_int(
                host.get("user_id")
            )
            != int(
                data.user_id
            )
        ):

            raise HTTPException(
                status_code=403,
                detail=(
                    "Host is not part "
                    "of this booking."
                )
            )

        participant_field = (
            "host_joined_at"
        )

    current_time = now_ts()

    # --------------------------------------------------------
    # 👤 Save participant join time
    # --------------------------------------------------------

    bookings_col.update_one(

        {
            "_id":
                booking["_id"],

            participant_field:
                None
        },

        {
            "$set": {

                participant_field:
                    current_time,

                "last_updated_at":
                    current_time
            }
        }
    )

    # --------------------------------------------------------
    # Reload booking
    # --------------------------------------------------------

    booking = bookings_col.find_one({
        "_id":
            booking["_id"]
    })

    user_joined = booking.get(
        "user_joined_at"
    )

    host_joined = booking.get(
        "host_joined_at"
    )

    session_started = booking.get(
        "session_started_at"
    )

    # ========================================================
    # 🚀 BOTH PARTICIPANTS JOINED
    # ========================================================

    if (
        user_joined is not None
        and host_joined is not None
        and session_started is None
    ):

        actual_start = now_ts()

        # ----------------------------------------------------
        # 🔐 Atomic session start
        #
        # Only one request can set the timer.
        # ----------------------------------------------------

        bookings_col.update_one(

            {
                "_id":
                    booking["_id"],

                "session_status":
                    "waiting",

                "user_joined_at": {
                    "$exists":
                        True,

                    "$ne":
                        None
                },

                "host_joined_at": {
                    "$exists":
                        True,

                    "$ne":
                        None
                },

                "$or": [

                    {
                        "session_started_at":
                            None
                    },

                    {
                        "session_started_at": {
                            "$exists":
                                False
                        }
                    }

                ]
            },

            {
                "$set": {

                    "session_started_at":
                        actual_start,

                    "call_started_at":
                        actual_start,

                    "session_status":
                        "active",

                    "status":
                        "active",

                    "last_updated_at":
                        actual_start
                }
            }
        )

        # ----------------------------------------------------
        # Read official server time
        # ----------------------------------------------------

        booking = bookings_col.find_one({
            "_id":
                booking["_id"]
        })

        session_started = (
            booking.get(
                "session_started_at"
            )
        )

    # ========================================================
    # ⏱️ SERVER AUTHORITATIVE TIMER
    # ========================================================

    duration_secs = (

        safe_int(
            booking.get(
                "duration_mins",
                DEFAULT_DURATION_MINS
            )
        )

        * 60
    )

    session_ends_at = None

    remaining_seconds = None

    if session_started:

        session_ends_at = (
            float(
                session_started
            )
            + duration_secs
        )

        remaining_seconds = max(

            0,

            int(
                session_ends_at
                - now_ts()
            )
        )

    return {

        "status":
            "success",

        "role":
            role,

        "booking_id":
            booking["booking_id"],

        "user_joined_at":
            booking.get(
                "user_joined_at"
            ),

        "host_joined_at":
            booking.get(
                "host_joined_at"
            ),

        "session_started_at":
            session_started,

        "session_ends_at":
            session_ends_at,

        "duration_mins":
            safe_int(
                booking.get(
                    "duration_mins",
                    DEFAULT_DURATION_MINS
                )
            ),

        "remaining_seconds":
            remaining_seconds,

        "session_status":
            booking.get(
                "session_status",
                "waiting"
            )
    }


# ============================================================
# ⏱️ SESSION STATUS
# ============================================================

@app.get(
    "/api/session/{booking_id}"
)
def session_status(
    booking_id: str
):

    booking = get_booking(
        booking_id
    )

    if not booking:

        raise HTTPException(
            status_code=404,
            detail="Booking not found"
        )

    duration = safe_int(
        booking.get(
            "duration_mins",
            DEFAULT_DURATION_MINS
        )
    )

    session_started = booking.get(
        "session_started_at"
    )

    # --------------------------------------------------------
    # ⏳ Waiting
    # --------------------------------------------------------

    if not session_started:

        return {

            "status":
                "success",

            "booking_id":
                booking_id,

            "session_status":
                booking.get(
                    "session_status",
                    "waiting"
                ),

            "session_started_at":
                None,

            "session_ends_at":
                None,

            "remaining_seconds":
                None,

            "duration_mins":
                duration,

            "user_joined":
                booking.get(
                    "user_joined_at"
                ) is not None,

            "host_joined":
                booking.get(
                    "host_joined_at"
                ) is not None
        }

    # --------------------------------------------------------
    # ⏱️ Calculate exact end
    # --------------------------------------------------------

    session_ends_at = (
        float(
            session_started
        )
        + duration * 60
    )

    remaining_seconds = max(

        0,

        int(
            session_ends_at
            - now_ts()
        )
    )

    # --------------------------------------------------------
    # 🔴 Session expired
    # --------------------------------------------------------

    if remaining_seconds <= 0:

        ended_at = now_ts()

        result = bookings_col.update_one(

            {
                "_id":
                    booking["_id"],

                "session_status":
                    "active"
            },

            {
                "$set": {

                    "session_status":
                        "ended",

                    "status":
                        "completed",

                    "session_ended_at":
                        ended_at,

                    "last_updated_at":
                        ended_at
                }
            }
        )

        if result.modified_count == 1:

            # Preserve earning protection
            # in case earning wasn't credited.
            credit_host_earning(
                booking
            )

            booking = bookings_col.find_one({
                "_id":
                    booking["_id"]
            })

    return {

        "status":
            "success",

        "booking_id":
            booking_id,

        "session_status":
            booking.get(
                "session_status"
            ),

        "session_started_at":
            session_started,

        "session_ends_at":
            session_ends_at,

        "remaining_seconds":
            remaining_seconds,

        "duration_mins":
            duration
    }


# ============================================================
# 📞 COMPLETE BOOKING
# ============================================================

class CompleteBookingModel(BaseModel):

    booking_id: str

    user_id: Optional[int] = None

    role: Optional[str] = None


@app.post(
    "/api/complete-booking"
)
def complete_booking(
    data: CompleteBookingModel
):

    booking = get_booking(
        data.booking_id
    )

    if not booking:

        raise HTTPException(
            status_code=404,
            detail="Booking not found"
        )

    # --------------------------------------------------------
    # 🔐 Participant validation
    # --------------------------------------------------------

    if data.user_id is not None:

        role = (
            data.role
            or ""
        ).lower()

        authorized = False

        if role == "user":

            authorized = (
                safe_int(
                    booking.get(
                        "user_id"
                    )
                )
                == int(
                    data.user_id
                )
            )

        elif role == "host":

            host = get_host(
                booking.get(
                    "host_id"
                )
            )

            authorized = (
                host is not None
                and safe_int(
                    host.get(
                        "user_id"
                    )
                )
                == int(
                    data.user_id
                )
            )

        if not authorized:

            raise HTTPException(
                status_code=403,
                detail="Not authorized."
            )

    ended_at = now_ts()

    result = bookings_col.update_one(

        {
            "_id":
                booking["_id"],

            "status": {
                "$nin": [
                    "completed",
                    "rejected"
                ]
            }
        },

        {
            "$set": {

                "status":
                    "completed",

                "session_status":
                    "ended",

                "session_ended_at":
                    ended_at,

                "last_updated_at":
                    ended_at
            }
        }
    )

    # --------------------------------------------------------
    # 💰 Make sure earning is credited
    # --------------------------------------------------------

    if result.modified_count == 1:

        updated_booking = (
            bookings_col.find_one({
                "_id":
                    booking["_id"]
            })
        )

        credit_host_earning(
            updated_booking
        )

    return {

        "status":
            "success",

        "message":
            "📞 Call ended successfully."
    }


# ============================================================
# 🎥 AGORA TOKEN
# ============================================================

class AgoraTokenModel(BaseModel):

    channel_name: str

    uid: int = 0

    booking_id: Optional[str] = None

    user_id: Optional[int] = None

    role: Optional[str] = None


@app.post(
    "/api/agora/token"
)
def generate_agora_token(
    data: AgoraTokenModel
):

    if not AGORA_APP_ID:

        raise HTTPException(
            status_code=500,
            detail=(
                "Agora App ID "
                "is not configured."
            )
        )

    if not AGORA_APP_CERTIFICATE:

        raise HTTPException(
            status_code=500,
            detail=(
                "Agora App Certificate "
                "is not configured."
            )
        )

    if RtcTokenBuilder is None:

        raise HTTPException(
            status_code=500,
            detail=(
                "Agora token library "
                "is not installed."
            )
        )

    # --------------------------------------------------------
    # 🔐 Private booking validation
    # --------------------------------------------------------

    if data.booking_id:

        booking = get_booking(
            data.booking_id
        )

        if not booking:

            raise HTTPException(
                status_code=404,
                detail="Booking not found."
            )

        if (
            booking.get(
                "channel_name"
            )
            != data.channel_name
        ):

            raise HTTPException(
                status_code=403,
                detail="Invalid channel."
            )

        if booking.get(
            "status"
        ) not in (
            "approved",
            "active"
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Call is not approved."
                )
            )

        if data.user_id is not None:

            role = (
                data.role
                or ""
            ).lower()

            authorized = False

            if role == "user":

                authorized = (
                    safe_int(
                        booking.get(
                            "user_id"
                        )
                    )
                    == int(
                        data.user_id
                    )
                )

            elif role == "host":

                host = get_host(
                    booking.get(
                        "host_id"
                    )
                )

                authorized = (
                    host is not None
                    and safe_int(
                        host.get(
                            "user_id"
                        )
                    )
                    == int(
                        data.user_id
                    )
                )

            if not authorized:

                raise HTTPException(
                    status_code=403,
                    detail=(
                        "Not authorized "
                        "for this call."
                    )
                )

    # --------------------------------------------------------
    # ⏳ Token expiry
    # --------------------------------------------------------

    expiration_time = 3600

    privilege_expired_ts = int(
        now_ts()
        + expiration_time
    )

    token = (
        RtcTokenBuilder
        .buildTokenWithUid(

            AGORA_APP_ID,

            AGORA_APP_CERTIFICATE,

            data.channel_name,

            int(data.uid),

            1,

            privilege_expired_ts
        )
    )

    return {

        "status":
            "success",

        "token":
            token,

        "app_id":
            AGORA_APP_ID,

        "channel_name":
            data.channel_name,

        "uid":
            int(data.uid),

        "expires_at":
            privilege_expired_ts
    }


# ============================================================
# 💳 RECHARGE
# ============================================================

class RechargeModel(BaseModel):

    user_id: int

    amount: float = Field(
        gt=0
    )


@app.post("/api/recharge")
def create_recharge(
    data: RechargeModel
):

    user = get_user(
        data.user_id
    )

    if not user:

        raise HTTPException(
            status_code=404,
            detail="User not found."
        )

    recharge_id = str(
        uuid.uuid4()
    )

    recharge_doc = {

        "recharge_id":
            recharge_id,

        "user_id":
            data.user_id,

        "amount":
            data.amount,

        "status":
            "pending",

        "created_at":
            now_ts()
    }

    recharges_col.insert_one(
        recharge_doc
    )

    return {

        "status":
            "success",

        "recharge_id":
            recharge_id,

        "message":
            "💳 Recharge request created."
    }


# ============================================================
# 📸 RECHARGE SCREENSHOT
# ============================================================

@app.post(
    "/api/recharge/{recharge_id}/screenshot"
)
async def upload_recharge_screenshot(

    recharge_id: str,

    file: UploadFile = File(...)
):

    recharge = recharges_col.find_one({

        "recharge_id":
            recharge_id
    })

    if not recharge:

        raise HTTPException(
            status_code=404,
            detail="Recharge not found."
        )

    extension = os.path.splitext(
        file.filename or ""
    )[1].lower()

    allowed_extensions = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp"
    }

    if extension not in (
        allowed_extensions
    ):

        raise HTTPException(
            status_code=400,
            detail="Invalid image format."
        )

    content = await file.read()

    # 10 MB limit
    if len(content) > (
        10 * 1024 * 1024
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "Image must be under 10 MB."
            )
        )

    filename = (
        f"{uuid.uuid4()}"
        f"{extension}"
    )

    file_path = os.path.join(
        UPLOAD_DIR,
        filename
    )

    with open(
        file_path,
        "wb"
    ) as f:

        f.write(content)

    relative_path = (
        f"/uploads/{filename}"
    )

    recharges_col.update_one(

        {
            "_id":
                recharge["_id"]
        },

        {
            "$set": {

                "screenshot":
                    relative_path,

                "screenshot_uploaded_at":
                    now_ts()
            }
        }
    )

    return {

        "status":
            "success",

        "screenshot":
            relative_path,

        "message":
            "📸 Screenshot uploaded successfully."
    }


# ============================================================
# 💰 ADMIN RECHARGE APPROVAL
# ============================================================

class ApproveRechargeModel(BaseModel):

    recharge_id: str


@app.post(
    "/api/admin/recharge/approve"
)
def approve_recharge(
    data: ApproveRechargeModel
):

    recharge = recharges_col.find_one({

        "recharge_id":
            data.recharge_id
    })

    if not recharge:

        raise HTTPException(
            status_code=404,
            detail="Recharge not found."
        )

    amount = safe_float(
        recharge.get(
            "amount",
            0
        )
    )

    result = recharges_col.update_one(

        {
            "_id":
                recharge["_id"],

            "status":
                "pending"
        },

        {
            "$set": {

                "status":
                    "approved",

                "approved_at":
                    now_ts()
            }
        }
    )

    if result.modified_count != 1:

        return {

            "status":
                "success",

            "message":
                "Recharge already processed."
        }

    users_col.update_one(

        {
            "user_id":
                safe_int(
                    recharge["user_id"]
                )
        },

        {
            "$inc": {
                "tokens":
                    amount
            }
        }
    )

    send_telegram_message(

        safe_int(
            recharge["user_id"]
        ),

        (
            "🎉 <b>Recharge Successful!</b>\n\n"

            f"💰 Added Tokens: "
            f"<b>{amount}</b>\n\n"

            "✅ Your wallet has been updated."
        )
    )

    return {

        "status":
            "success",

        "message":
            "💰 Recharge approved successfully."
    }


# ============================================================
# 🎁 GIFTS
# ============================================================

class GiftModel(BaseModel):

    user_id: int

    host_id: str

    gift_name: str

    gift_value: float = Field(
        gt=0
    )


@app.post("/api/gift/send")
def send_gift(
    data: GiftModel
):

    user = get_user(
        data.user_id
    )

    if not user:

        raise HTTPException(
            status_code=404,
            detail="User not found."
        )

    result = users_col.update_one(

        {
            "user_id":
                data.user_id,

            "tokens": {
                "$gte":
                    data.gift_value
            }
        },

        {
            "$inc": {
                "tokens":
                    -data.gift_value
            }
        }
    )

    if result.modified_count != 1:

        raise HTTPException(
            status_code=400,
            detail="❌ Insufficient tokens."
        )

    gift_doc = {

        "gift_id":
            str(uuid.uuid4()),

        "user_id":
            data.user_id,

        "host_id":
            data.host_id,

        "gift_name":
            data.gift_name,

        "gift_value":
            data.gift_value,

        "created_at":
            now_ts()
    }

    chats_col.insert_one(
        gift_doc
    )

    return {

        "status":
            "success",

        "message":
            (
                f"🎁 {data.gift_name} "
                "sent successfully!"
            ),

        "gift":
            serialize_doc(
                gift_doc
            )
    }


# ============================================================
# 💬 CHAT
# ============================================================

class ChatMessageModel(BaseModel):

    booking_id: str

    sender_id: int

    message: str


@app.post("/api/chat/send")
def send_chat(
    data: ChatMessageModel
):

    booking = get_booking(
        data.booking_id
    )

    if not booking:

        raise HTTPException(
            status_code=404,
            detail="Booking not found."
        )

    message = (
        data.message
        .strip()
    )

    if not message:

        raise HTTPException(
            status_code=400,
            detail=(
                "Message cannot be empty."
            )
        )

    if len(message) > 2000:

        raise HTTPException(
            status_code=400,
            detail="Message too long."
        )

    host = get_host(
        booking.get(
            "host_id"
        )
    )

    allowed_users = {
        safe_int(
            booking.get(
                "user_id"
            )
        )
    }

    if host:

        allowed_users.add(
            safe_int(
                host.get(
                    "user_id"
                )
            )
        )

    if data.sender_id not in (
        allowed_users
    ):

        raise HTTPException(
            status_code=403,
            detail="Not a participant."
        )

    chat_doc = {

        "message_id":
            str(uuid.uuid4()),

        "booking_id":
            data.booking_id,

        "sender_id":
            data.sender_id,

        "message":
            message,

        "created_at":
            now_ts()
    }

    chats_col.insert_one(
        chat_doc
    )

    return {

        "status":
            "success",

        "message":
            serialize_doc(
                chat_doc
            )
    }


@app.get(
    "/api/chat/{booking_id}"
)
def get_chat(
    booking_id: str
):

    booking = get_booking(
        booking_id
    )

    if not booking:

        raise HTTPException(
            status_code=404,
            detail="Booking not found."
        )

    messages = list(

        chats_col.find({

            "booking_id":
                booking_id

        }).sort(
            "created_at",
            1
        )
    )

    return {

        "status":
            "success",

        "messages":
            serialize_many(
                messages
            )
    }


# ============================================================
# 💸 WITHDRAWAL
# ============================================================

class WithdrawModel(BaseModel):

    user_id: int

    amount: float = Field(
        gt=0
    )

    upi_id: str


@app.post("/api/withdraw")
def withdraw_earnings(
    data: WithdrawModel
):

    user = get_user(
        data.user_id
    )

    if not user:

        raise HTTPException(
            status_code=404,
            detail="User not found."
        )

    result = users_col.update_one(

        {
            "user_id":
                data.user_id,

            "tokens": {
                "$gte":
                    data.amount
            }
        },

        {
            "$inc": {
                "tokens":
                    -data.amount
            }
        }
    )

    if result.modified_count != 1:

        raise HTTPException(
            status_code=400,
            detail=(
                "❌ Insufficient wallet balance."
            )
        )

    withdrawal_id = str(
        uuid.uuid4()
    )

    withdrawal_doc = {

        "withdrawal_id":
            withdrawal_id,

        "user_id":
            data.user_id,

        "amount":
            data.amount,

        "upi_id":
            data.upi_id,

        "status":
            "pending",

        "created_at":
            now_ts()
    }

    withdrawals_col.insert_one(
        withdrawal_doc
    )

    return {

        "status":
            "success",

        "withdrawal_id":
            withdrawal_id,

        "message":
            "💸 Withdrawal request submitted."
    }


# ============================================================
# 🤖 TELEGRAM WEBHOOK
# ============================================================

@app.post(
    "/telegram/webhook"
)
async def telegram_webhook(
    update: dict
):

    try:

        callback_query = update.get(
            "callback_query"
        )

        # ====================================================
        # 🔘 CALLBACK BUTTON
        # ====================================================

        if callback_query:

            callback_id = (
                callback_query.get(
                    "id",
                    ""
                )
            )

            answer_callback_query(
                callback_id
            )

            callback_data = (
                callback_query
                .get(
                    "data",
                    ""
                )
            )

            telegram_user_id = (
                safe_int(
                    callback_query
                    .get(
                        "from",
                        {}
                    )
                    .get(
                        "id"
                    )
                )
            )

            # ------------------------------------------------
            # ✅ ACCEPT
            # ------------------------------------------------

            if callback_data.startswith(
                "accept_bk_"
            ):

                booking_id = (
                    callback_data[
                        len(
                            "accept_bk_"
                        ):
                    ]
                )

                booking = get_booking(
                    booking_id
                )

                if not booking:

                    send_telegram_message(
                        telegram_user_id,
                        "❌ Booking not found."
                    )

                    return {
                        "ok":
                            True
                    }

                host = get_host(
                    booking.get(
                        "host_id"
                    )
                )

                if (
                    not host
                    or safe_int(
                        host.get(
                            "user_id"
                        )
                    )
                    != telegram_user_id
                ):

                    send_telegram_message(
                        telegram_user_id,
                        (
                            "🔐 You are not "
                            "authorized for "
                            "this booking."
                        )
                    )

                    return {
                        "ok":
                            True
                    }

                result = approve_booking(
                    booking
                )

                return {

                    "ok":
                        True,

                    "result":
                        result
                }

            # ------------------------------------------------
            # ❌ REJECT
            # ------------------------------------------------

            if callback_data.startswith(
                "reject_bk_"
            ):

                booking_id = (
                    callback_data[
                        len(
                            "reject_bk_"
                        ):
                    ]
                )

                booking = get_booking(
                    booking_id
                )

                if not booking:

                    send_telegram_message(
                        telegram_user_id,
                        "❌ Booking not found."
                    )

                    return {
                        "ok":
                            True
                    }

                host = get_host(
                    booking.get(
                        "host_id"
                    )
                )

                if (
                    not host
                    or safe_int(
                        host.get(
                            "user_id"
                        )
                    )
                    != telegram_user_id
                ):

                    send_telegram_message(
                        telegram_user_id,
                        "🔐 You are not authorized."
                    )

                    return {
                        "ok":
                            True
                    }

                result = reject_booking(
                    booking
                )

                return {

                    "ok":
                        True,

                    "result":
                        result
                }

            return {
                "ok":
                    True
            }

        # ====================================================
        # 💬 NORMAL TELEGRAM MESSAGE
        # ====================================================

        message = update.get(
            "message"
        )

        if message:

            chat_id = safe_int(
                message
                .get(
                    "chat",
                    {}
                )
                .get(
                    "id"
                )
            )

            text = (
                message
                .get(
                    "text",
                    ""
                )
                .strip()
            )

            # ------------------------------------------------
            # 🚀 START
            # ------------------------------------------------

            if text == "/start":

                send_telegram_message(

                    chat_id,

                    (
                        "🚀 <b>Welcome to "
                        "Vynora Live!</b>\n\n"

                        "📞 Private 1v1 Calls\n"
                        "💰 Host Earnings\n"
                        "🎁 Gifts\n"
                        "💬 Private Chat\n"
                        "⏱️ Exact Call Timer\n\n"

                        "✨ Your Vynora Live "
                        "system is ready!"
                    )
                )

            # ------------------------------------------------
            # 📚 HELP
            # ------------------------------------------------

            elif text == "/help":

                send_telegram_message(

                    chat_id,

                    (
                        "📚 <b>Vynora Live Help</b>\n\n"

                        "📞 Accept calls from "
                        "booking notifications.\n\n"

                        "⏱️ Timer starts only "
                        "when User + Host "
                        "both join.\n\n"

                        "💰 Host earnings are "
                        "protected from "
                        "duplicate credit.\n\n"

                        "💸 Withdraw from "
                        "the app."
                    )
                )

        return {
            "ok":
                True
        }

    except Exception as e:

        logger.error(
            "Telegram Webhook Error: %s",
            e
        )

        logger.error(
            traceback.format_exc()
        )

        return {
            "ok":
                True
        }


# ============================================================
# 🧹 BACKGROUND SESSION CLEANUP
# ============================================================

async def cleanup_loop():

    while True:

        try:

            current_time = now_ts()

            active_bookings = list(

                bookings_col.find({

                    "session_status":
                        "active",

                    "session_started_at": {
                        "$ne":
                            None
                    }

                }).limit(200)
            )

            for booking in (
                active_bookings
            ):

                started_at = safe_float(
                    booking.get(
                        "session_started_at",
                        0
                    )
                )

                duration = safe_int(
                    booking.get(
                        "duration_mins",
                        DEFAULT_DURATION_MINS
                    )
                )

                if (
                    started_at > 0
                    and current_time
                    >=
                    started_at
                    + duration * 60
                ):

                    ended_at = now_ts()

                    result = (
                        bookings_col
                        .update_one(

                            {
                                "_id":
                                    booking["_id"],

                                "session_status":
                                    "active"
                            },

                            {
                                "$set": {

                                    "session_status":
                                        "ended",

                                    "status":
                                        "completed",

                                    "session_ended_at":
                                        ended_at,

                                    "last_updated_at":
                                        ended_at
                                }
                            }
                        )
                    )

                    if (
                        result.modified_count
                        == 1
                    ):

                        # Ensure earning exists
                        credit_host_earning(
                            booking
                        )

                        logger.info(
                            "⏰ Session expired: %s",
                            booking.get(
                                "booking_id"
                            )
                        )

        except asyncio.CancelledError:

            raise

        except Exception:

            logger.error(
                "Cleanup Error:\n%s",
                traceback.format_exc()
            )

        await asyncio.sleep(
            5
        )


# ============================================================
# 🚀 STARTUP
# ============================================================

@app.on_event(
    "startup"
)
async def startup_event():

    app.state.cleanup_task = (
        asyncio.create_task(
            cleanup_loop()
        )
    )

    logger.info(
        "🚀 Vynora Live started successfully."
    )

    logger.info(
        "⏱️ Timer Mode: "
        "BOTH PARTICIPANTS JOIN"
    )


# ============================================================
# 🛑 SHUTDOWN
# ============================================================

@app.on_event(
    "shutdown"
)
async def shutdown_event():

    task = getattr(
        app.state,
        "cleanup_task",
        None
    )

    if task:

        task.cancel()


# ============================================================
# 📁 STATIC FILES
# ============================================================

if os.path.exists(
    "static"
):

    app.mount(

        "/static",

        StaticFiles(
            directory="static"
        ),

        name="static"
    )


if os.path.exists(
    UPLOAD_DIR
):

    app.mount(

        "/uploads",

        StaticFiles(
            directory=UPLOAD_DIR
        ),

        name="uploads"
    )


# ============================================================
# ▶️ RUN
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(

        "main:app",

        host="0.0.0.0",

        port=PORT,

        reload=False
        )
