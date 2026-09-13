import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage

# Bot Token aur Configurations
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
SUPER_ADMIN_ID = 7001825467
SUPPORT_USERNAME = "@VynoraSupport"
UPI_ID = "vynoralive@slc"
ACCOUNT_HOLDER = "Rajnish Kumar"

# Telegram Group IDs (Yahan apne groups ki ID dalein)
GROUP_2_REGISTRATION_ID = -100XXXXXXXXXX  # New User Registration Group
GROUP_1_MAIN_ID = -100XXXXXXXXXX          # Main Command Center / UTR Group
GROUP_3_AUDIT_ID = -100XXXXXXXXXX         # Verified Payment & Audit Group

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    
    # Group 2 me naye user ka registration log bhejna
    reg_text = (
        f"👤 **New User Registered!**\n"
        f"• Name: {user.full_name}\n"
        f"• Username: @{user.username if user.username else 'None'}\n"
        f"• User ID: `{user.id}`"
    )
    await bot.send_message(GROUP_2_REGISTRATION_ID, reg_text, parse_mode="Markdown")
    
    # User ke liye Welcome Message aur Mini App Button
    welcome_message = (
        f"✨ **Welcome to Vynora Live 1v1** ✨\n\n"
        f"Aap yahan 1-on-1 video calls, private live streams, aur Vynora Token gifting ka anand le sakte hain.\n"
        f"Kisi bhi sahayata ke liye sampark karein: {SUPPORT_USERNAME}"
    )
    
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🚀 Open Vynora Live App", web_app=types.WebAppInfo(url="YOUR_MINI_APP_URL"))],
            [types.InlineKeyboardButton(text="💳 Recharge Wallet (UPI)", callback_data="recharge_menu")]
        ]
    )
    
    await message.answer(welcome_message, reply_markup=keyboard, parse_mode="Markdown")

@dp.callback_query(F.data == "recharge_menu")
async def recharge_menu(callback: types.CallbackQuery):
    text = (
        f"💎 **Vynora Recharge Gateway**\n\n"
        f"• **UPI ID:** `{UPI_ID}`\n"
        f"• **Name:** {ACCOUNT_HOLDER}\n\n"
        f"Payment karne ke baad apna UTR number aur screenshot Group 1 me ya bot par bhejein."
    )
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
