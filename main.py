@dp.message(F.text == "/start")
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚀 Launch Vynora Live 1v1", web_app=WebAppInfo(url=RENDER_URL + "?v=2"))
    ]])
    await message.answer(
        "✨ **Vynora Live 1v1 me aapka swagat hai!**\n\nNeeche button par click karke Mini App launch karein:",
        reply_markup=kb,
        parse_mode="Markdown"
    )
