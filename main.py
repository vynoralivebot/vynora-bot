import os
import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient

# Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "7001825467"))
GROUP_1_ID = os.getenv("GROUP_1_ID")  # Command Center
GROUP_2_ID = os.getenv("GROUP_2_ID")  # User Registration
GROUP_3_ID = os.getenv("GROUP_3_ID")  # Financial Audit

# Database Setup
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["vynora_live_db"]
users_col = db["users"]
hosts_col = db["hosts"]
bookings_col = db["bookings"]
transactions_col = db["transactions"]

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---- 1. USER REGISTRATION LOGGING (Group 2) ----
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    user = message.from_user
    user_id = user.id
    username = f"@{user.username}" if user.username else "No Username"
    first_name = user.first_name or "User"

    # Check if user exists in DB
    existing_user = await users_col.find_one({"user_id": user_id})
    if not existing_user:
        new_user = {
            "user_id": user_id,
            "first_name": first_name,
            "username": username,
            "tokens": 0,
            "created_at": datetime.utcnow()
        }
        await users_col.insert_one(new_user)

        # Notify Group 2 (User Registration Group)
        if GROUP_2_ID:
            log_text = (
                f"👤 **New User Registered!**\n\n"
                f"🔹 **Name:** {first_name}\n"
                f"🔹 **Username:** {username}\n"
                f"🆔 **ID:** `{user_id}`\n"
                f"⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            try:
                await bot.send_message(chat_id=GROUP_2_ID, text=log_text, parse_mode="Markdown")
            except Exception as e:
                print(f"Group 2 Log Error: {e}")

    # Mini App Button Response
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🚀 Launch Vynora Live 1v1", web_app=types.WebAppInfo(url=WEB_APP_URL))
        ]]
    )
    await message.answer(
        f"👋 Swagat hai {first_name}!\n\n**Vynora Live 1v1** me aapka swagat hai. Neeche diye gaye button par click karke Mini App kholne ke liye click karein.",
        reply_markup=markup,
        parse_mode="Markdown"
    )

# ---- 2. AUTOMATIC 5-MIN REFUND BACKGROUND TASK ----
async def check_pending_bookings():
    """ Runs every 30 seconds to auto-refund bookings older than 5 minutes """
    while True:
        try:
            five_mins_ago = datetime.utcnow() - timedelta(minutes=5)
            expired_bookings = bookings_col.find({
                "status": "pending",
                "created_at": {"$lte": five_mins_ago}
            })

            async for booking in expired_bookings:
                # Refund tokens to User
                await users_col.update_one(
                    {"user_id": booking["user_id"]},
                    {"$inc": {"tokens": booking["token_amount"]}}
                )
                # Update booking status
                await bookings_col.update_one(
                    {"_id": booking["_id"]},
                    {"$set": {"status": "auto_refunded", "refunded_at": datetime.utcnow()}}
                )

                # Notify User & Group 1
                try:
                    await bot.send_message(
                        chat_id=booking["user_id"],
                        text=f"⚠️ Host ne 5 minute me response nahi diya. `{booking['token_amount']}` Vynora Tokens aapke wallet me refund kar diye gaye hain."
                    )
                except:
                    pass

        except Exception as e:
            print(f"Escrow Auto-Refund Loop Error: {e}")
        
        await asyncio.sleep(30)

# ---- 3. FASTAPI ROUTING ----
@app.post("/webhook")
async def webhook(request: Request):
    update = types.Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"status": "ok"}

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.on_event("startup")
async def on_startup():
    if WEB_APP_URL:
        webhook_url = f"{WEB_APP_URL.rstrip('/')}/webhook"
        await bot.set_webhook(webhook_url)
    
    # Start Escrow Refund Background Task
    asyncio.create_task(check_pending_bookings())

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
