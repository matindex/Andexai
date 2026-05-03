import json
import os
import io
import logging
import asyncio
from datetime import datetime, timedelta
from PIL import Image

# Telegram & Gemini SDK
from telegram import Update, ReplyKeyboardMarkup, constants
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai

# ==========================================
# 1. ڕێکخستنی سەرەکی (AnDex Config)
# ==========================================
# لێرە تەنها ئەو کلیلانە دابنێ کە هەتن، ئەگەر دانەیەکیش بێت کێشە نییە
API_KEYS = [
    "YOUR_GEMINI_KEY_1",
    "YOUR_GEMINI_KEY_2"
]

# لیستی مۆدێلەکان بەپێی ئەولەویەت
MODELS_TO_TRY = ["gemini-1.5-pro", "gemini-1.5-flash"]

ADMIN_ID = 123456789  # ئایدی تێلەگرامی خۆت
BOT_TOKEN = ""
DB_FILE = "database.json"

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==========================================
# 2. داتابەیس
# ==========================================
def load_db():
    if not os.path.exists(DB_FILE): return {"users": {}}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except: return {"users": {}}

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=4, ensure_ascii=False)

# ==========================================
# 3. بزوێنەری زیرەکی دەستکرد (Matrix Failover)
# ==========================================
async def get_ai_response(prompt, user_id, image_bytes=None):
    db = load_db()
    history = db["users"].get(str(user_id), {}).get("history", [])[-20:]
    
    system_instruction = (
        "تۆ زیرەکی دەستکردی AnDex Development یت. زۆر تۆکمەیت. "
        "هەرگیز ناڵێیت ناتوانم. وەک مێشکێکی ئەندازیاری و پڕۆفیشناڵ وەڵام بدەرەوە. "
        "زمان: کوردی سۆرانی."
    )
    
    full_context = f"{system_instruction}\n\nمێژوو:\n{history}\n\nیوزەر: {prompt}"

    # فلتەرکردنی کلیلە چۆڵەکان بۆ ئەوەی کات نەکوژرێت
    active_keys = [k for k in API_KEYS if k.strip()]
    
    for key in active_keys:
        genai.configure(api_key=key)
        for model_name in MODELS_TO_TRY:
            try:
                model = genai.GenerativeModel(model_name)
                if image_bytes:
                    img = Image.open(io.BytesIO(image_bytes))
                    response = model.generate_content([full_context, img])
                else:
                    response = model.generate_content(full_context)
                
                if response.text:
                    return response.text
            except Exception as e:
                logging.warning(f"هەڵە لە مۆدێلی {model_name} بە کلیلی {key[:5]}: {e}")
                continue
                
    return "ببوورە، هەموو سەرچاوەکانی Gemini لە ئێستادا سەرقاڵن."

# ==========================================
# 4. پاراستن و فرمانەکان
# ==========================================
async def is_active(user_id):
    db = load_db()
    user = db["users"].get(str(user_id))
    if not user: return False
    return datetime.now() < datetime.strptime(user["expiry"], "%Y-%m-%d")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await is_active(user_id):
        kb = [['Status 📊'], ['Info ℹ️', 'Admin 📞']]
        await update.message.reply_text("AnDex AI ئامادەیە 🚀", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    else:
        await update.message.reply_text(f"⚠️ ئەکاونتەکەت چالاک نییە.\nID: `{user_id}`", parse_mode="Markdown")

# Admin Panel
async def admin_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid, days = context.args[0], int(context.args[1])
        db = load_db()
        exp = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        db["users"][str(uid)] = {"expiry": exp, "history": []}
        save_db(db); await update.message.reply_text(f"✅ ئەکتیڤ کرا بۆ {days} ڕۆژ.")
    except: await update.message.reply_text("/add [ID] [Days]")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    txt = " ".join(context.args)
    db = load_db()
    for uid in db["users"]:
        try: await context.bot.send_message(uid, f"📢 ئاگاداری:\n\n{txt}")
        except: continue
    await update.message.reply_text("نێردرا.")

# ==========================================
# 5. وەڵامدانەوەی گشتی
# ==========================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not await is_active(user_id): return

    text = update.message.text
    if text == "Status 📊":
        db = load_db(); exp = db["users"][user_id]["expiry"]
        await update.message.reply_text(f"⏳ چالاکە تا: {exp}"); return
    elif text == "Admin 📞":
        await update.message.reply_text("بۆ نوێکردنەوە: @AdminAccount"); return

    await update.message.chat.send_action(constants.ChatAction.TYPING)
    
    img_bytes = None
    if update.message.photo:
        file = await update.message.photo[-1].get_file()
        img_bytes = await file.download_as_bytearray()
        text = update.message.caption or "ئەم وێنەیە شی بکەرەوە"

    response = await get_ai_response(text, user_id, img_bytes)
    
    db = load_db()
    db["users"][user_id]["history"].append(f"U: {text}")
    db["users"][user_id]["history"].append(f"A: {response}")
    db["users"][user_id]["history"] = db["users"][user_id]["history"][-20:]
    save_db(db)
    
    await update.message.reply_text(response)

# ==========================================
# 6. ڕەنکردن
# ==========================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", admin_add))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))
    print("--- AnDex AI Core (Gemini Matrix) is Online ---")
    app.run_polling()

if __name__ == "__main__":
    main()
