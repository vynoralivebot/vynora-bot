from pydantic import BaseModel

class RegisterHostReq(BaseModel):
    user_id: int
    name: str
    age: int
    rate: int
    lang: str
    loc: str
    img: str
    bio: str

# 1. Host Self-Registration API
@app.post("/api/register-host")
async def register_host(req: RegisterHostReq):
    try:
        doc = {
            "_id": f"host_{req.user_id}",
            "user_id": req.user_id,
            "name": req.name,
            "age": req.age,
            "rate": req.rate,
            "lang": req.lang,
            "loc": req.loc,
            "img": req.img,
            "bio": req.bio,
            "status": "pending",
            "isReal": True,
            "isVerified": False,
            "isOnline": False,
            "rating": "5.0",
            "calls": "0",
            "created_at": datetime.utcnow()
        }
        await hosts_col.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)

        # Notify Group 1 (Command Center) for Admin Approval
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Approve Host", callback_data=f"apphost_{req.user_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"rejhost_{req.user_id}")
        ]])
        
        msg = (
            f"👩 **NEW HOST REGISTRATION REQUEST**\n\n"
            f"👤 **User ID:** `{req.user_id}`\n"
            f"📛 **Name:** {req.name}\n"
            f"🎂 **Age:** {req.age}\n"
            f"🪙 **Rate:** {req.rate} Tokens/min\n"
            f"🗣️ **Languages:** {req.lang}\n"
            f"📍 **Location:** {req.loc}\n"
            f"📝 **Bio:** {req.bio}"
        )
        await bot.send_photo(chat_id=GROUP_1_ID, photo=req.img, caption=msg, reply_markup=kb, parse_mode="Markdown")
        return {"status": "success", "message": "Host Application submitted for Admin approval!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# 2. Host Status Check API
@app.get("/api/host-info/{user_id}")
async def get_host_info(user_id: int):
    doc = await hosts_col.find_one({"_id": f"host_{user_id}"})
    if not doc:
        return {"status": "none"}
    return {
        "status": doc.get("status", "none"),
        "isOnline": doc.get("isOnline", False),
        "isVerified": doc.get("isVerified", False),
        "details": {
            "name": doc.get("name"),
            "rate": doc.get("rate"),
            "img": doc.get("img")
        }
    }

# 3. Host Toggle Camera/Live Status API
@app.post("/api/host/toggle-live")
async def toggle_live(data: dict):
    u_id = data.get("user_id")
    doc = await hosts_col.find_one({"_id": f"host_{u_id}"})
    if doc and doc.get("status") == "approved":
        new_status = not doc.get("isOnline", False)
        await hosts_col.update_one({"_id": f"host_{u_id}"}, {"$set": {"isOnline": new_status}})
        return {"status": "success", "isOnline": new_status}
    return {"status": "error", "message": "Not an approved host"}

# 4. Telegram Admin Approval Callback Handlers
@dp.callback_query(F.data.startswith("apphost_"))
async def approve_host_callback(call: types.CallbackQuery):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("❌ Only Super Admin can approve hosts!", show_alert=True)
        return
    host_user_id = int(call.data.split("_")[1])
    await hosts_col.update_one(
        {"_id": f"host_{host_user_id}"},
        {"$set": {"status": "approved", "isVerified": True, "isOnline": True}}
    )
    await call.message.edit_caption(
        caption=call.message.caption + "\n\n✅ **APPROVED BY ADMIN (LIVE ACTIVE)**",
        reply_markup=None,
        parse_mode="Markdown"
    )
    await call.answer("Host Approved Successfully!")
    try:
        await bot.send_message(host_user_id, "🎉 **Congratulations!** Your Host Application is Approved by Admin. You are now a Verified Host! 📹")
    except: pass

@dp.callback_query(F.data.startswith("rejhost_"))
async def reject_host_callback(call: types.CallbackQuery):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("❌ Only Super Admin can reject!", show_alert=True)
        return
    host_user_id = int(call.data.split("_")[1])
    await hosts_col.update_one(
        {"_id": f"host_{host_user_id}"},
        {"$set": {"status": "rejected", "isOnline": False}}
    )
    await call.message.edit_caption(
        caption=call.message.caption + "\n\n❌ **REJECTED BY ADMIN**",
        reply_markup=None,
        parse_mode="Markdown"
    )
    await call.answer("Host Rejected")
