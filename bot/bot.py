import logging
import json
import asyncio
import nest_asyncio
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, filters
from telegram.constants import ChatMemberStatus

# nest_asyncio ni faollashtirish
nest_asyncio.apply()

# Bot tokenini va kanal username'larini kiriting
BOT_TOKEN = '7994422754:AAH5icBsFgRekKxGn5zfz9wHUBn3eortNkY'  # BotFatherdan olingan token
CHANNEL_USERNAMES = ['@bekM_gamer', '@TESLA_esports']  # Obuna bo'lish kerak bo'lgan kanallar

# JSON faylni o'qib olish
try:
    with open('movies.json', 'r', encoding='utf-8') as file:
        movies_data = json.load(file)
except FileNotFoundError:
    logging.error("movies.json fayli topilmadi. Bot ishlamaydi.")
    movies_data = {}
except json.JSONDecodeError:
    logging.error("movies.json faylini o'qishda xatolik yuz berdi. Fayl formatini tekshirib ko'ring.")
    movies_data = {}

# Foydalanuvchi kanalga obuna bo'lganligini tekshirish
async def is_subscribed(user_id: int, context: CallbackContext, channel_username: str) -> bool:
    try:
        chat_member = await context.bot.get_chat_member(chat_id=channel_username, user_id=user_id)
        if chat_member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return True
        else:
            logging.info(f"Foydalanuvchi {user_id} {channel_username} kanalida obuna emas.")
            return False
    except Exception as e:
        logging.error(f"Obunani tekshirishda xatolik: {e}")
        return False

# Start komandasi
async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    if all([await is_subscribed(user_id, context, channel) for channel in CHANNEL_USERNAMES]):
        await update.message.reply_text("Xush kelibsiz! Botdan foydalanish uchun raqam yuboring.")
    else:
        keyboard = [
            [InlineKeyboardButton("1-kanalga obuna bo'lish", url=f"https://t.me/{CHANNEL_USERNAMES[0][1:]}")],
            [InlineKeyboardButton("2-kanalga obuna bo'lish", url=f"https://t.me/{CHANNEL_USERNAMES[1][1:]}")],
            [InlineKeyboardButton("✅ Obunani tekshirish", callback_data='check_sub')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:", reply_markup=reply_markup)

# Obunani tekshirish
async def check_subscription(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    if all([await is_subscribed(user_id, context, channel) for channel in CHANNEL_USERNAMES]):
        await query.answer("Rahmat! Siz kanallarga obuna bo'lgansiz.")
        await query.edit_message_text("Xush kelibsiz! Botdan foydalanish uchun raqam yuboring.")
    else:
        await query.answer("Iltimos, Barcha kanalga obuna bo'ling.", show_alert=True)
        logging.info(f"Foydalanuvchi {user_id} obuna bo'lmagan.")
        await query.edit_message_text("Iltimos, Barcha kanalga obuna bo'ling.")

# Raqam qabul qilish va video yuborish
async def handle_number(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    if not all([await is_subscribed(user_id, context, channel) for channel in CHANNEL_USERNAMES]):
        await update.message.reply_text("Iltimos, avval barcha kanalga obuna bo'ling.")
        return

    try:
        number = update.message.text
        video_info = movies_data.get(number)
        if video_info:
            # views ni int ga o'zgartirayotganimizni tekshirib chiqamiz
            if isinstance(video_info["views"], int):
                video_info["views"] += 1
            else:
                logging.error(f"Invalid views data: {video_info['views']}")
                video_info["views"] = 1  # Agar views noto'g'ri bo'lsa, uni 1 ga o'rnatamiz

            # JSON faylni yangilash
            with open('movies.json', 'w', encoding='utf-8') as file:
                json.dump(movies_data, file, ensure_ascii=False, indent=4)

            video_url = video_info["video_url"]
            video_caption = f"📄Kino nomi: {video_info['title']}\n👀Ko'rilganlar: {str(video_info['views'])}"
            await update.message.reply_video(video=video_url, caption=video_caption)
        else:
            await update.message.reply_text("Uzr, bu raqamga mos video topilmadi.")
    except Exception as e:
        logging.error(f"Xatolik: {e}")
        await update.message.reply_text("Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.")

# Botni ishga tushirish
async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlerlar
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(check_subscription))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r'^\d+$'), handle_number))

    # Botni ishga tushirish
    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
