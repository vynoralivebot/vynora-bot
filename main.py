@app.post("/api/recharge")
async def submit_recharge(req: RechargeRequest):
    tx_id = f"TXN_{int(time.time())}_{req.user_id}"
    tx_doc = {
        "_id": tx_id,
        "user_id": req.user_id,
        "amount_inr": req.amount_inr,
        "utr_number": req.utr_number,
        "status": "pending",
        "created_at": datetime.utcnow()
    }
    
    # Mandatory DB Save
    try:
        await asyncio.wait_for(transactions_col.insert_one(tx_doc), timeout=5.0)
    except Exception as e:
        print(f"DB Save Error: {e}")
        return {"status": "error", "message": "Database write error. Check MONGO_URI."}

    # Send Card to Group 1 only if DB save is successful
    if GROUP_1_ID:
        try:
            gid1 = int(GROUP_1_ID) if str(GROUP_1_ID).replace("-", "").isdigit() else GROUP_1_ID
            card_text = (
                f"💳 **NEW RECHARGE REQUEST**\n\n"
                f"👤 **User ID:** `{req.user_id}`\n"
                f"💵 **Amount:** ₹{req.amount_inr}\n"
                f"📌 **UTR:** `{req.utr_number}`\n"
                f"⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            markup = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_tx_{tx_id}"),
                    InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_tx_{tx_id}")
                ]]
            )
            await bot.send_message(chat_id=gid1, text=card_text, reply_markup=markup, parse_mode="Markdown")
        except Exception as e:
            print(f"Group 1 Send Error: {e}")

    return {"status": "submitted", "message": "UTR Super Admin ko verification ke liye bhej diya gaya hai."}
