# --- 1. TELEGRAM BOT HANDLERS & LOGGING ---
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    user = message.from_user
    user_id = user.id
    username = f"@{user.username}" if user.username else "No Username"
    first_name = user.first_name or "User"

    # Save or Update User in DB
    try:
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {"first_name": first_name, "username": username}, "$setOnInsert": {"tokens": 0, "created_at": datetime.utcnow()}},
            upsert=True
        )
    except Exception as e:
        print(f"DB Error: {e}")

    # ALWAYS send notification to Group 2 for testing
    if GROUP_2_ID:
        log_text = (
            f"👤 **User Activity / Start Alert!**\n\n"
            f"🔹 **Name:** {first_name}\n"
            f"🔹 **Username:** {username}\n"
            f"🆔 **User ID:** `{user_id}`\n"
            f"⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        try:
            # Clean string chat_id to int if needed
            gid = int(GROUP_2_ID) if str(GROUP_2_ID).replace("-", "").isdigit() else GROUP_2_ID
            await bot.send_message(chat_id=gid, text=log_text, parse_mode="Markdown")
        except Exception as e:
            print(f"Group 2 Log Error: {e}")

    # Mini App Button Response
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🚀 Launch Vynora Live 1v1", web_app=types.WebAppInfo(url=WEB_APP_URL))
        ]]
    )
    await message.answer(
        f"👋 **Vynora Live 1v1** me aapka swagat hai!\n\nNeeche button par click karke Mini App launch karein.",
        reply_markup=markup,
        parse_mode="Markdown"
    )
