import os
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import motor.motor_asyncio

app = FastAPI()

# Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "YOUR_MONGO_URI")

# Database Connection
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client["vynora_db"]

# Telegram Bot Setup
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Bot /start Command (Opens Mini App)
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    markup = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text="🚀 Open Vynora App", 
            web_app=types.WebAppInfo(url=os.getenv("WEB_APP_URL", "https://your-render-url.onrender.com"))
        )]
    ])
    await message.answer("Vynora Live Video Calling App me aapka swagat hai!", reply_markup=markup)

# Mini App Main Route (Frontend HTML)
@app.get("/", response_class=HTMLResponse)
async def serve_webapp(request: Request):
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Vynora Live</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            body { background-color: #0f172a; color: #ffffff; }
        </style>
    </head>
    <body class="flex flex-col h-screen justify-between p-4">
        <!-- Top Bar -->
        <div class="flex justify-between items-center bg-slate-800 p-3 rounded-xl">
            <h1 class="font-bold text-lg text-blue-400">Vynora Live</h1>
            <div class="bg-slate-700 px-3 py-1 rounded-full text-sm font-semibold text-yellow-400">
                🪙 <span id="user-balance">0 Mins</span>
            </div>
        </div>

        <!-- Main Content -->
        <div class="flex-1 flex flex-col justify-center items-center text-center my-6">
            <div class="w-20 h-20 bg-blue-600 rounded-full flex items-center justify-center text-3xl mb-4 shadow-lg shadow-blue-500/50">
                📹
            </div>
            <h2 class="text-xl font-bold mb-2">Anonymous 1-on-1 Video Call</h2>
            <p class="text-slate-400 text-sm mb-6">Connect instantly with verified hosts privately.</p>
            <button class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 rounded-xl shadow-lg transition">
                Start Random Call
            </button>
        </div>

        <!-- Bottom Navigation -->
        <div class="flex justify-around bg-slate-800 p-3 rounded-xl text-xs text-slate-400">
            <button class="flex flex-col items-center text-blue-400">
                <span>🏠</span> Home
            </button>
            <button class="flex flex-col items-center">
                <span>👥</span> Hosts
            </button>
            <button class="flex flex-col items-center">
                <span>💳</span> Wallet
            </button>
            <button class="flex flex-col items-center">
                <span>👤</span> Profile
            </button>
        </div>

        <script>
            const tg = window.Telegram.WebApp;
            tg.expand();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# FastAPI Startup event for Polling
@app.on_event("startup")
async def on_startup():
    asyncio.create_task(dp.start_polling(bot))
