import json
import os
import io
import logging
import asyncio
from datetime import datetime, timedelta
from PIL import Image

# Telegram & AI SDKs
from telegram import Update, ReplyKeyboardMarkup, constants
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import openai
import google.generativeai as genai

# ==========================================
# 1. رێکخستنی سەرەکی (ADMIN & KEYS)
# ==========================================
ADMIN_ID = 7049452601  # ئایدی تۆ کە لە وێنەکە بوو
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

API_KEYS = {
    "gemini_1": "YOUR_GEMINI_KEY_1",
    "gemini_2": "YOUR_GEMINI_KEY_2",
    "openai": "YOUR_OPENAI_KEY"
}

DB_FILE = "database.json"
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==========================================
# 2. سیستەمی داتابەیس
# ==========================================
def load_db():
    if not os.path.exists(DB_FILE):
        return {"users": {}}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=4, ensure_ascii=False)

# ==========================================
# 3. بزوێنەری زیرەکی دەستکرد (Multi-Model Failover)
# ==========================================
async def get_ai_response(prompt, user_id, image_bytes=None):
    db = load_db()
    user_data = db["users"].get(str(user_id), {})
    history = user_data.get("history", [])[-15:] # ١٥ چاتی کۆتایی بۆ خێرایی و بیرەوەری
    
    sys_msg = "تۆ زیرەکی دەستکردی AnDex Development یت. زۆر پڕۆفیشناڵیت. وشەی 'ناتوانم' لای تۆ نییە. هەمیشە بە کوردی سۆرانی و بە ڕەئی خۆت وەڵام بدەرەوە."
    full_context = f"{sys_msg}\n\nHistory: {history}\nUser: {prompt}"

    # ستراتیژی سویچکردنی مۆدێلەکان (لە باشترینەوە بۆ خێراترین)
    strategies = [
        {"provider": "gemini", "key": API_KEYS["gemini_1"], "model": "gemini-1.5-pro"},
        {"provider": "gemini", "key": API_KEYS["gemini_2"], "model": "gemini-1.5-flash"},
        {"provider": "openai", "key": API_KEYS["openai"], "model": "gpt-4o"},
        {"provider": "openai", "key": API_KEYS["openai"], "model": "gpt-4o-mini"}
    ]
    
    for strategy in strategies:
        try:
            if strategy["provider"] == "gemini":
                genai.configure(api_key=strategy["key"])
                model = genai.GenerativeModel(strategy["model"])
                if image_bytes:
                    img = Image.open(io.BytesIO(image_bytes))
                    response = await asyncio.to_thread(model.generate_content, [full_context, img])
                else:
                    response = await asyncio.to_thread(model.generate_content, full_context)
                if response.text: return response.text

            elif strategy["provider"] == "openai":
                client = openai.AsyncOpenAI(api_key=strategy["key"])
                messages = [{"role": "system", "content": sys_msg}]
                for h in history:
                    role = "user" if h.startswith("User:") else "assistant"
                    messages.append({"role": role, "content": h.split(": ", 1)[-1]})
                messages.append({"role": "user", "content": prompt})

                response = await client.chat.completions.create(
                    model=strategy["model"],
                    messages=messages,
                    timeout=20.0
                )
                return response.choices[0].message.content
        except Exception as e:
            logging.error(f"Error with {strategy['model']}: {e}")
            continue # سویچ بۆ مۆدێلی دواتر
            
    return "ببوورە، سیستەمەکە تووشی کێشەی تەکنیکی بووە. تکایە کەمێکی تر هەوڵ بدەرەوە."

# ==========================================
# 4. بەڕێوبەرایەتی ئەدمن و دەسەڵاتەکان
# ==========================================
async def is_active(user_id):
    db = load_db()
    user = db["users"].get(str(user_id))
    if not user: return False
    return datetime.now() < datetime.strptime(user["expiry"], "%Y-%m-%d")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if await is_active(uid):
        kb = [['دۆخی ئەکاونت 📊'], ['دەربارە ℹ️', 'پەیوەندی 📞']]
        await update.message.reply_text("بەخێربێیت بۆ AnDex AI! 🚀", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    else:
        await update.message.reply_text(f"⚠️ ئەکاونتەکەت چالاک نییە.\nID: `{uid}`\nبۆ کاراکردن پەیوەندی بە ئەدمین بکە.", parse_mode="Markdown")

# کۆماندەکانی ئەدمین
async def admin_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid, days = context.args[0], int(context.args[1])
        db = load_db()
        expiry = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        db["users"][str(uid)] = {"expiry": expiry, "history": []}
        save_db(db)
        await update.message.reply_text(f"✅ یوزەر {uid} چالاک کرا تا {expiry}")
    except: await update.message.reply_text("Format: /add [id] [days]")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = " ".join(context.args)
    db = load_db()
    for uid in db["users"]:
        try: await context.bot.send_message(chat_id=uid, text=f"📢 ئاگاداری:\n\n{msg}")
        except: continue

# ==========================================
# 5. بەڕێوبەرایەتی نامەکان
# ==========================================
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if not await is_active(uid): return

    text = update.message.text
    if text == "دۆخی ئەکاونت 📊":
        db = load_db()
        await update.message.reply_text(f"🗓 کاتی بەسەرچوون: {db['users'][uid]['expiry']}")
        return
    elif text == "دەربارە ℹ️":
        await update.message.reply_text("AnDex AI Advanced Bot by AnDex Development.")
        return
    elif text == "پەیوەندی 📞":
        await update.message.reply_text("Admin: @YourUsername")
        return

    # AI Processing
    await update.message.chat.send_action(constants.ChatAction.TYPING)
    img_bytes = None
    if update.message.photo:
        file = await update.message.photo[-1].get_file()
        img_bytes = await file.download_as_bytearray()
        text = update.message.caption or "ئەم وێنەیە چییە؟"

    resp = await get_ai_response(text, uid, img_bytes)
    
    # Save History
    db = load_db()
    db["users"][uid]["history"].append(f"User: {text}")
    db["users"][uid]["history"].append(f"AI: {resp}")
    db["users"][uid]["history"] = db["users"][uid]["history"][-15:]
    save_db(db)
    
    await update.message.reply_text(resp)

# ==========================================
# 6. ڕەنکردنی بۆت
# ==========================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", admin_add))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_msg))
    
    print("AnDex AI is Live and Ready!")
    app.run_polling()

if __name__ == "__main__":
    main()
