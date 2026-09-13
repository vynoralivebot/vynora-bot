# --- ADMIN APPROVAL HANDLERS (WITH LOGGING & FAILSAFE) ---
@dp.callback_query(F.data.startswith("approve_tx_"))
async def approve_payment_callback(callback: types.CallbackQuery):
    clicker_id = callback.from_user.id
    
    # Super Admin Check (Safety Bypass for main admin)
    if clicker_id != SUPER_ADMIN_ID:
        await callback.answer(f"❌ Keval Super Admin (ID: {SUPER_ADMIN_ID}) hi approve kar sakte hain! Aapki ID: {clicker_id}", show_alert=True)
        return

    tx_id = callback.data.replace("approve_tx_", "")
    
    try:
        tx = await asyncio.wait_for(transactions_col.find_one({"_id": tx_id}), timeout=3.0)
    except Exception as e:
        tx = None

    if not tx:
        await callback.answer("❌ Transaction record nahi mila ya expire ho gaya hai!", show_alert=True)
        return

    if tx.get("status") == "approved":
        await callback.answer("⚠️ Ye transaction pehle hi approve ho chuki hai!", show_alert=True)
        return

    user_id = tx["user_id"]
    amount = tx["amount_inr"]
    tokens_to_add = int(amount * 1)

    # DB Wallet Update
    try:
        await users_col.update_one({"user_id": user_id}, {"$inc": {"tokens": tokens_to_add}}, upsert=True)
        await transactions_col.update_one({"_id": tx_id}, {"$set": {"status": "approved", "approved_at": datetime.utcnow()}})
    except Exception as e:
        print(f"DB Update Error: {e}")

    # Notify User
    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"✅ **Payment Approved!**\n\nAapke wallet me `{tokens_to_add}` Vynora Tokens credit ho gaye hain! 🚀",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"User Notification Error: {e}")

    # Log to Group 3 Audit
    if GROUP_3_ID:
        audit_text = (
            f"🧾 **FINANCIAL AUDIT RECORD**\n\n"
            f"✅ **Status:** Approved\n"
            f"👤 **User ID:** `{user_id}`\n"
            f"💰 **Amount:** ₹{amount}\n"
            f"🪙 **Tokens Credited:** {tokens_to_add}\n"
            f"📌 **UTR:** `{tx['utr_number']}`\n"
            f"👨‍💼 **Approved By:** `{clicker_id}`\n"
            f"⏰ **Timestamp:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        try:
            gid3 = int(GROUP_3_ID) if str(GROUP_3_ID).replace("-", "").isdigit() else GROUP_3_ID
            await bot.send_message(chat_id=gid3, text=audit_text, parse_mode="Markdown")
        except Exception as e:
            print(f"Group 3 Log Error: {e}")

    await callback.message.edit_text(f"{callback.message.text}\n\n✅ **APPROVED BY ADMIN**")
    await callback.answer("✅ Payment Approved Successfully!", show_alert=True)
