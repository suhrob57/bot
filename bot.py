import logging
import json
import asyncio
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatMemberStatus

# Muhit o'zgaruvchilarini yuklash
load_dotenv()

# TOKENNI OLISH
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN topilmadi! .env faylni tekshiring yoki tokenni qo'lda kiriting.")

# Debug uchun tokenni tekshirish
print("⚙️ Muhit o'zgaruvchilari yuklandi...")
print(f"🔑 BOT_TOKEN: {BOT_TOKEN[:5]}*** (yashirin)")

# Kanal username'larini kiritish
CHANNEL_USERNAMES = ['@bekM_gamer', '@TESLA_esports']

# JSON faylni o‘qish
def load_movies():
    try:
        with open('movies.json', 'r', encoding='utf-8') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        logging.error("❌ movies.json fayli topilmadi yoki noto‘g‘ri formatda.")
        return {}

movies_data = load_movies()

# Foydalanuvchi obuna bo'lganligini tekshirish
async def is_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE, channel_username: str) -> bool:
    try:
        chat_member = await context.bot.get_chat_member(chat_id=channel_username, user_id=user_id)
        return chat_member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logging.error(f"⚠️ Obunani tekshirishda xatolik ({channel_username}): {e}")
        return False

# /start komandasi
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if all([await is_subscribed(user_id, context, channel) for channel in CHANNEL_USERNAMES]):
        await update.message.reply_text("✅ Xush kelibsiz! Botdan foydalanish uchun raqam yuboring.")
    else:
        keyboard = [[InlineKeyboardButton("1-kanalga obuna bo‘lish", url=f"https://t.me/{CHANNEL_USERNAMES[0][1:]}")],
                    [InlineKeyboardButton("2-kanalga obuna bo‘lish", url=f"https://t.me/{CHANNEL_USERNAMES[1][1:]}")],
                    [InlineKeyboardButton("✅ Obunani tekshirish", callback_data='check_sub')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("🔔 Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:", reply_markup=reply_markup)

# Obunani tekshirish
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    if all([await is_subscribed(user_id, context, channel) for channel in CHANNEL_USERNAMES]):
        await query.answer("✅ Rahmat! Siz kanallarga obuna bo‘lgansiz.")
        await query.edit_message_text("🎉 Xush kelibsiz! Botdan foydalanish uchun raqam yuboring.")
    else:
        await query.answer("🚀 Iltimos, barcha kanallarga obuna bo‘ling.", show_alert=True)
        await query.edit_message_text("📢 Iltimos, barcha kanallarga obuna bo‘ling.")

# Raqam orqali kino ma’lumotlarini yuborish
async def handle_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if not all([await is_subscribed(user_id, context, channel) for channel in CHANNEL_USERNAMES]):
        await update.message.reply_text("⚠️ Iltimos, avval barcha kanalga obuna bo‘ling.")
        return
    
    number = update.message.text.strip()
    video_info = movies_data.get(number)
    if video_info:
        video_info["views"] = video_info.get("views", 0) + 1
        with open('movies.json', 'w', encoding='utf-8') as file:
            json.dump(movies_data, file, ensure_ascii=False, indent=4)

        video_url = video_info["video_url"]
        video_caption = f"🎬 Kino nomi: {video_info['title']}\n👀 Ko‘rilganlar: {video_info['views']}"
        await update.message.reply_video(video=video_url, caption=video_caption)
    else:
        await update.message.reply_text("❌ Uzr, bu raqamga mos video topilmadi.")

# Botni ishga tushirish
async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlerlar
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(check_subscription))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r'^\d+$'), handle_number))

    logging.info("🚀 Bot ishga tushdi...")
    await application.run_polling()

# **ASYNCIO LOOP MUAMMOSINI HAL QILISH**
if __name__ == '__main__':
    try:
        if asyncio.get_event_loop().is_running():
            asyncio.ensure_future(main())  # Agar loop allaqachon ishlayotgan bo'lsa, `ensure_future` ishlatiladi
        else:
            asyncio.run(main())  # Aks holda, `asyncio.run()` yordamida yangi loop yaratiladi
    except KeyboardInterrupt:
        logging.info("🛑 Bot to‘xtatildi")
