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
# 1. ڕێکخستنی سەرەکی (تکایە لێرە زانیارییەکانت بنووسە)
# ==========================================
API_KEYS = {
    "gemini_1": "YOUR_GEMINI_KEY_1",
    "gemini_2": "YOUR_GEMINI_KEY_2",
    "openai": "YOUR_OPENAI_KEY"
}
ADMIN_ID = 123456789  # ئایدی تێلەگرامی خۆت
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
DB_FILE = "database.json"

# لۆگینگ بۆ دۆزینەوەی هەڵەکان
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==========================================
# 2. بەڕێوبەرایەتی داتابەیس (JSON)
# ==========================================
def load_db():
    if not os.path.exists(DB_FILE):
        return {"users": {}}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"users": {}}

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=4, ensure_ascii=False)

# ==========================================
# 3. لۆژیکی زیرەکی دەستکرد و Failover
# ==========================================
async def get_ai_response(prompt, user_id, image_bytes=None):
    db = load_db()
    user_data = db["users"].get(str(user_id), {})
    history = user_data.get("history", [])[-20:] # بیرەوەری ٢٠ نامەی کۆتایی
    
    system_prompt = (
        "تۆ زیرەکی دەستکردی AnDex Development یت. زۆر تۆکمە و پڕۆفیشناڵیت. "
        "هەرگیز ناڵێیت ناتوانم. لە هەموو بوارێک (کۆد، دیزاین، وێنە، پلان) شارەزایت. "
        "هەمیشە بە کوردی سۆرانی و بە ڕەئی خۆتەوە وەڵام بدەرەوە."
    )
    
    full_context = f"{system_prompt}\n\nمێژووی گفتوگۆ:\n{history}\n\nیوزەر: {prompt}"

    # ڕیزبەندی تاقیکردنەوەی API یەکان ئەگەر یەکێکیان شکستی هێنا
    api_sequence = ["gemini_1", "gemini_2", "openai"]
    
    for api_name in api_sequence:
        try:
            if "gemini" in api_name:
                genai.configure(api_key=API_KEYS[api_name])
                model = genai.GenerativeModel('gemini-1.5-flash')
                if image_bytes:
                    img = Image.open(io.BytesIO(image_bytes))
                    response = model.generate_content([full_context, img])
                else:
                    response = model.generate_content(full_context)
                
                if response.text:
                    return response.text + "\n\n(Powered by AnDex Gemini Core)"

            elif api_name == "openai":
                client = openai.AsyncOpenAI(api_key=API_KEYS[api_name])
                messages = [{"role": "system", "content": system_prompt}]
                for h in history:
                    role = "user" if h.startswith("User:") else "assistant"
                    messages.append({"role": role, "content": h.split(": ", 1)[-1]})
                messages.append({"role": "user", "content": prompt})

                response = await client.chat.completions.create(
                    model="gpt-4o",
                    messages=messages
                )
                return response.choices[0].message.content + "\n\n(Powered by AnDex GPT Core)"

        except Exception as e:
            logging.error(f"Error with {api_name}: {e}")
            continue # دەچێتە سەر API دواتر
            
    return "ببوورە، سیستەمەکە لە ئێستادا لەژێر چاکسازییە."

# ==========================================
# 4. پاراستنی ئاسایش و ئەکتیڤکردن
# ==========================================
async def is_active(user_id):
    db = load_db()
    user = db["users"].get(str(user_id))
    if not user: return False
    expiry = datetime.strptime(user["expiry"], "%Y-%m-%d")
    return datetime.now() < expiry

# ==========================================
# 5. فرمانەکانی بەکارهێنەر (User Commands)
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await is_active(user_id):
        keyboard = [['Status 📊'], ['Info ℹ️', 'Contact Admin 📞']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "بەخێربێیت بۆ زیرەکی دەستکردی AnDex Development 🚀\nمن ئامادەم بۆ جێبەجێکردنی هەر ئەرکێکی قورس.",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            f"⚠️ ئەکاونتەکەت چالاک نییە.\nID: `{user_id}`\nتکایە ئەم ئایدییە بنێرە بۆ ئەدمین بۆ کاراکردن.",
            parse_mode="Markdown"
        )

# ==========================================
# 6. پانێڵی ئەدمین (Admin Commands)
# ==========================================
async def admin_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid, days = context.args[0], int(context.args[1])
        db = load_db()
        expiry = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        db["users"][str(uid)] = {"expiry": expiry, "history": []}
        save_db(db)
        await update.message.reply_text(f"✅ یوزەر {uid} چالاک کرا تا {expiry}")
    except:
        await update.message.reply_text("Format: /add [id] [days]")

async def admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    db = load_db()
    msg = "👥 لیستی یوزەرە چالاکەکان:\n\n"
    for uid, data in db["users"].items():
        msg += f"🆔 `{uid}` - 📅 {data['expiry']}\n"
    await update.message.reply_text(msg or "هیچ یوزەرێک نییە.", parse_mode="Markdown")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    text = " ".join(context.args)
    db = load_db()
    for uid in db["users"]:
        try: await context.bot.send_message(chat_id=uid, text=f"📢 ئاگاداری لە ئەدمین:\n\n{text}")
        except: continue
    await update.message.reply_text("نێردرا بۆ هەمووان.")

# ==========================================
# 7. بەڕێوبەرایەتی نامە و وێنە
# ==========================================
async def handle_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not await is_active(user_id):
        await start(update, context); return

    text = update.message.text
    # بەشی مینیۆ
    if text == "Status 📊":
        db = load_db(); exp = db["users"][user_id]["expiry"]
        await update.message.reply_text(f"📅 کاتی بەسەرچوون: {exp}"); return
    elif text == "Info ℹ️":
        await update.message.reply_text("ئەم بۆتە بەهێزترین سیستەمی AI هەیە و پشت بە مۆدێلەکانی Gemini و GPT دەبەستێت."); return
    elif text == "Contact Admin 📞":
        await update.message.reply_text("پەیوەندی بکە بە: @Admin_Username"); return

    # وەڵامدانەوەی AI
    await update.message.chat.send_action(constants.ChatAction.TYPING)
    image_bytes = None
    if update.message.photo:
        photo = await update.message.photo[-1].get_file()
        image_bytes = await photo.download_as_bytearray()
        text = update.message.caption or "ئەم وێنەیە چییە؟"

    response = await get_ai_response(text, user_id, image_bytes)
    
    # نوێکردنەوەی مێژوو
    db = load_db()
    db["users"][user_id]["history"].append(f"User: {text}")
    db["users"][user_id]["history"].append(f"AI: {response}")
    db["users"][user_id]["history"] = db["users"][user_id]["history"][-20:]
    save_db(db)
    
    await update.message.reply_text(response)

# ==========================================
# 8. دەستپێکردنی بزوێنەری بۆت
# ==========================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", admin_add))
    app.add_handler(CommandHandler("users", admin_list))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_all))
    
    print("--- AnDex AI Core is Live ---")
    app.run_polling()

if __name__ == "__main__":
    main()
