import logging
import json
import asyncio
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from telegram.constants import ChatMemberStatus
import os

# Logger sozlamalari
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# JSON fayllarni o'qish
def load_json(filename):
    try:
        with open(filename, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {} if filename in ["movies.json", "users.json"] else []

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)

# Fayllarni yuklash
movies_data = load_json("movies.json")
CHANNEL_USERNAMES = load_json("channels.json")  # Kanal nomlari endi https://t.me/ formatida saqlanadi
users_data = load_json("users.json")  # Foydalanuvchilar fayli

# Foydalanuvchilarni saqlash uchun funksiyalar
def save_users(users):
    save_json("users.json", users)

# Kanal nomini normalize qilish (https://t.me/ formatiga aylantirish)
def normalize_channel_url(channel_input):
    channel_input = channel_input.strip()
    if channel_input.startswith("https://t.me/"):
        return channel_input
    elif channel_input.startswith("@"):
        return f"https://t.me/{channel_input[1:]}"
    else:
        return f"https://t.me/{channel_input}"

# ConversationHandler uchun holatlar
MOVIE_TITLE, MOVIE_PARTS, MOVIE_PART_NAME, MOVIE_PART_URL, MOVIE_NUMBER = range(5)
SIMPLE_MOVIE_TITLE, SIMPLE_MOVIE_URL, SIMPLE_MOVIE_NUMBER = range(5, 8)
DELETE_MOVIE = 8
REMOVE_CHANNEL = 9  # Kanal o'chirish uchun yangi holat
BROADCAST_MESSAGE = 10  # Xabar yuborish uchun yangi holat

# Obunani tekshirish (yopiq kanallarga ham ishlaydi)
async def is_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE, channel_url: str) -> bool:
    try:
        chat = await context.bot.get_chat(channel_url)
        chat_id = chat.id
        logging.info(f"Kanal topildi: ID={chat_id}, URL={channel_url}")

        chat_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return chat_member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logging.error(f"Obunani tekshirishda xatolik (URL: {channel_url}): {e}")
        return False

# Start komandasi (yangilangan)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    username = update.message.from_user.username or "Noma'lum"
    first_name = update.message.from_user.first_name or "Noma'lum"
    profile_url = f"https://t.me/{username}" if username != "Noma'lum" else f"tg://user?id={user_id}"

    if str(user_id) not in users_data:
        users_data[str(user_id)] = {
            "username": username,
            "first_name": first_name,
            "joined_date": str(update.message.date)
        }
        save_users(users_data)

        # Kanalga xabar yuborish
        notification_channel_id = os.environ.get("NOTIFICATION_CHANNEL_ID")
        if notification_channel_id:
            notification_message = (
                f"Yangi foydalanuvchi qo'shildi!\n"
                f"Ism: {first_name}\n"
                f"Username: @{username}\n"
                f"Profil: {profile_url}"
            )
            try:
                await context.bot.send_message(
                    chat_id=notification_channel_id,
                    text=notification_message
                )
            except Exception as e:
                logging.error(f"Kanalga xabar yuborishda xatolik: {e}")

    if user_id in [int(id) for id in os.environ.get("ADMIN_IDS", "").split(",") if id.strip()]:  # Admin ID lar ro'yxatida tekshirish
        keyboard = [
            [InlineKeyboardButton("🎮 Qismli kino qo‘shish", callback_data="add_movie_parts")],
            [InlineKeyboardButton("🎬 Oddiy kino qo‘shish", callback_data="add_simple_movie")],
            [InlineKeyboardButton("📢 Kanal qo‘shish", callback_data="add_channel")],
            [InlineKeyboardButton("❌ Kanalni o'chirish", callback_data="remove_channel")],
            [InlineKeyboardButton("🗑 Kino o'chirish", callback_data="delete_movie")],
            [InlineKeyboardButton("👥 Foydalanuvchilar soni", callback_data="user_count")],
            [InlineKeyboardButton("📩 Foydalanuvchilarga xabar yuborish", callback_data="broadcast")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Admin paneliga xush kelibsiz!", reply_markup=reply_markup)
        return

    is_all_subscribed = all([await is_subscribed(user_id, context, channel) for channel in CHANNEL_USERNAMES])
    if is_all_subscribed:
        await update.message.reply_text("Xush kelibsiz! Botdan foydalanish uchun kino raqamini yuboring.")
    else:
        keyboard = [
            [InlineKeyboardButton(f"{i+1}-kanalga obuna bo‘lish", url=channel)]
            for i, channel in enumerate(CHANNEL_USERNAMES)
        ]
        keyboard.append([InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_sub")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:", reply_markup=reply_markup)

# Obunani tekshirish tugmasi
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    is_all_subscribed = all([await is_subscribed(user_id, context, channel) for channel in CHANNEL_USERNAMES])

    if is_all_subscribed:
        await query.answer("Rahmat! Siz kanallarga obuna bo‘lgansiz.")
        await query.edit_message_text("Xush kelibsiz! Botdan foydalanish uchun kino raqamini yuboring.")
    else:
        await query.answer("Iltimos, avval barcha kanalga obuna bo‘ling.", show_alert=True)

# Foydalanuvchilar sonini ko'rsatish (xatolik boshqaruvi qo‘shilgan)
async def show_user_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except Exception as e:
            logging.error(f"CallbackQuery javobida xatolik: {e}")
    else:
        logging.error("CallbackQuery obyekti topilmadi")

    user_count = len(users_data)
    if query:
        await query.edit_message_text(f"Botdan foydalanuvchilar soni: {user_count}")
    else:
        await update.message.reply_text(f"Botdan foydalanuvchilar soni: {user_count}")

# Foydalanuvchilarga xabar yuborish jarayonini boshlash
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    admin_ids = [int(id) for id in os.environ.get("ADMIN_IDS", "").split(",") if id.strip()]
    if user_id not in admin_ids:
        await query.edit_message_text("Siz admin emassiz!")
        return ConversationHandler.END

    await query.message.reply_text("Foydalanuvchilarga yuboriladigan xabarni kiriting:")
    return BROADCAST_MESSAGE

# Xabarni foydalanuvchilarga yuborish
async def send_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message.text
    success_count = 0
    fail_count = 0

    for user_id in users_data.keys():
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
            success_count += 1
            await asyncio.sleep(0.05)  # Telegram API chegaralariga rioya qilish uchun kechikish
        except Exception as e:
            logging.error(f"Foydalanuvchiga xabar yuborishda xatolik (ID: {user_id}): {e}")
            fail_count += 1

    await update.message.reply_text(
        f"Xabar yuborish yakunlandi!\n"
        f"Muvaffaqiyatli yuborildi: {success_count} ta foydalanuvchiga\n"
        f"Yuborilmadi: {fail_count} ta foydalanuvchiga"
    )
    return ConversationHandler.END

# Admin paneli tugmalari
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "add_movie_parts":
        await query.message.reply_text("Qismli kino qo‘shish uchun kino nomini kiriting:")
        return MOVIE_TITLE
    elif query.data == "add_simple_movie":
        await query.message.reply_text("Oddiy kino qo‘shish uchun kino nomini kiriting:")
        return SIMPLE_MOVIE_TITLE
    elif query.data == "add_channel":
        await query.message.reply_text("Yangi kanal qo‘shish uchun username'ni @belgisi bilan kiriting:")
        return ConversationHandler.END
    elif query.data == "remove_channel":
        return await remove_channel(update, context)
    elif query.data == "delete_movie":
        return await delete_movie(update, context)
    elif query.data == "broadcast":
        return await broadcast(update, context)
    return ConversationHandler.END

# Kino qo‘shish: Kino nomini so'rash
async def movie_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["movie_title"] = update.message.text
    await update.message.reply_text("Kino nechta qismdan iborat? (Raqamda kiriting, masalan: 7)")
    return MOVIE_PARTS

# Kino qo‘shish: Kino qismlar sonini so'rash
async def movie_parts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        parts = int(update.message.text)
        if parts <= 0:
            await update.message.reply_text("Iltimos, musbat son kiriting.")
            return MOVIE_PARTS
        context.user_data["movie_parts"] = parts
        context.user_data["current_part"] = 1
        context.user_data["movie_part_data"] = []
        await update.message.reply_text(f"1-qism nomini kiriting:")
        return MOVIE_PART_NAME
    except ValueError:
        await update.message.reply_text("Iltimos, raqam kiriting.")
        return MOVIE_PARTS

# Kino qo‘shish: Har bir qismning nomini so'rash
async def movie_part_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    part_name = update.message.text
    context.user_data["current_part_name"] = part_name
    await update.message.reply_text(f"{context.user_data['current_part']}-qism URL manzilini kiriting:")
    return MOVIE_PART_URL

# Kino qo‘shish: Har bir qismning URL manzilini so'rash
async def movie_part_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    part_url = update.message.text
    current_part = context.user_data["current_part"]
    part_data = {
        "part_name": context.user_data["current_part_name"],
        "part_url": part_url,
    }
    context.user_data["movie_part_data"].append(part_data)

    if current_part < context.user_data["movie_parts"]:
        context.user_data["current_part"] += 1
        await update.message.reply_text(f"{context.user_data['current_part']}-qism nomini kiriting:")
        return MOVIE_PART_NAME
    else:
        await update.message.reply_text("Kino raqamini kiriting:")
        return MOVIE_NUMBER

# Kino qo‘shish: Kino raqamini so'rash va saqlash
async def movie_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    number = update.message.text
    title = context.user_data["movie_title"]
    parts = context.user_data["movie_parts"]
    part_data = context.user_data["movie_part_data"]

    movies_data[number] = {
        "title": title,
        "parts": parts,
        "part_data": part_data,
        "views": 0,
    }
    save_json("movies.json", movies_data)

    await update.message.reply_text(f"✅ Qismli kino qo‘shildi! {title} ({parts} qism)")
    return ConversationHandler.END

# Oddiy kino qo'shish: Kino nomini so'rash
async def simple_movie_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["movie_title"] = update.message.text
    await update.message.reply_text("Kino URL manzilini kiriting:")
    return SIMPLE_MOVIE_URL

# Oddiy kino qo'shish: Kino URL manzilini so'rash
async def simple_movie_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["movie_url"] = update.message.text
    await update.message.reply_text("Kino raqamini kiriting:")
    return SIMPLE_MOVIE_NUMBER

# Oddiy kino qo'shish: Kino raqamini so'rash va saqlash
async def simple_movie_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    number = update.message.text
    title = context.user_data["movie_title"]
    url = context.user_data["movie_url"]

    movies_data[number] = {
        "title": title,
        "video_url": url,
        "views": 0,
    }
    save_json("movies.json", movies_data)

    await update.message.reply_text(f"✅ Oddiy kino qo‘shildi! {title}")
    return ConversationHandler.END

# Kino o'chirish
async def delete_movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not movies_data:
        await query.edit_message_text("O'chirish uchun kino mavjud emas!")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(f"{number}: {data['title']}", callback_data=f"delete_{number}")]
        for number, data in movies_data.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("O'chirish uchun kino tanlang:", reply_markup=reply_markup)
    return DELETE_MOVIE

# Kino o'chirishni tasdiqlash
async def confirm_delete_movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    movie_number = query.data.replace("delete_", "")

    if movie_number in movies_data:
        del movies_data[movie_number]
        save_json("movies.json", movies_data)
        await query.edit_message_text(f"✅ Kino o'chirildi: {movie_number}")
    else:
        await query.edit_message_text("Kino topilmadi!")
    return ConversationHandler.END

# Kanal qo‘shish
async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    admin_ids = [int(id) for id in os.environ.get("ADMIN_IDS", "").split(",") if id.strip()]
    if user_id not in admin_ids:
        return

    new_channel = update.message.text.strip()
    if not new_channel.startswith("@"):
        await update.message.reply_text("Xatolik! Kanal username'ni @belgisi bilan kiriting.")
        return

    if new_channel in CHANNEL_USERNAMES:
        await update.message.reply_text("Bu kanal allaqachon qo‘shilgan.")
        return

    CHANNEL_USERNAMES.append(normalize_channel_url(new_channel))
    save_json("channels.json", CHANNEL_USERNAMES)
    await update.message.reply_text(f"✅ Kanal qo‘shildi: {new_channel}")

# Kanalni o'chirish
async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    admin_ids = [int(id) for id in os.environ.get("ADMIN_IDS", "").split(",") if id.strip()]
    if user_id not in admin_ids:
        await query.edit_message_text("Siz admin emassiz!")
        return ConversationHandler.END

    if not CHANNEL_USERNAMES:
        await query.edit_message_text("O‘chirish uchun kanal mavjud emas!")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(channel, callback_data=f"select_{channel}")]
        for channel in CHANNEL_USERNAMES
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("O‘chirish uchun kanalni tanlang:", reply_markup=reply_markup)
    return REMOVE_CHANNEL

# Kanalni tanlash va tasdiqlash
async def select_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    channel_to_delete = query.data.replace("select_", "")

    keyboard = [
        [InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"confirm_delete_{channel_to_delete}")],
        [InlineKeyboardButton("❌ Yo'q, bekor qilish", callback_data="cancel_delete")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"Kanalni o'chirishni tasdiqlaysizmi: {channel_to_delete}?", reply_markup=reply_markup)
    return REMOVE_CHANNEL

# Kanalni o'chirishni tasdiqlash
async def confirm_delete_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    channel_to_delete = query.data.replace("confirm_delete_", "")

    if channel_to_delete in CHANNEL_USERNAMES:
        CHANNEL_USERNAMES.remove(channel_to_delete)
        save_json("channels.json", CHANNEL_USERNAMES)
        await query.edit_message_text(f"✅ Kanal o‘chirildi: {channel_to_delete}")

        keyboard = [
            [InlineKeyboardButton("🎮 Qismli kino qo‘shish", callback_data="add_movie_parts")],
            [InlineKeyboardButton("🎬 Oddiy kino qo‘shish", callback_data="add_simple_movie")],
            [InlineKeyboardButton("📢 Kanal qo‘shish", callback_data="add_channel")],
            [InlineKeyboardButton("❌ Kanalni o'chirish", callback_data="remove_channel")],
            [InlineKeyboardButton("🗑 Kino o'chirish", callback_data="delete_movie")],
            [InlineKeyboardButton("👥 Foydalanuvchilar soni", callback_data="user_count")],
            [InlineKeyboardButton("📩 Foydalanuvchilarga xabar yuborish", callback_data="broadcast")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Admin paneliga xush kelibsiz!", reply_markup=reply_markup)
    else:
        await query.edit_message_text("Kanal topilmadi!")
    return ConversationHandler.END

# Kanalni o'chirishni bekor qilish
async def cancel_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Kanalni o'chirish bekor qilindi.")

    keyboard = [
        [InlineKeyboardButton("🎮 Qismli kino qo‘shish", callback_data="add_movie_parts")],
        [InlineKeyboardButton("🎬 Oddiy kino qo‘shish", callback_data="add_simple_movie")],
        [InlineKeyboardButton("📢 Kanal qo‘shish", callback_data="add_channel")],
        [InlineKeyboardButton("❌ Kanalni o'chirish", callback_data="remove_channel")],
        [InlineKeyboardButton("🗑 Kino o'chirish", callback_data="delete_movie")],
        [InlineKeyboardButton("👥 Foydalanuvchilar soni", callback_data="user_count")],
        [InlineKeyboardButton("📩 Foydalanuvchilarga xabar yuborish", callback_data="broadcast")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("Admin paneliga xush kelibsiz!", reply_markup=reply_markup)
    return ConversationHandler.END

# Raqamni qabul qilish va video yuborish
async def handle_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if not all([await is_subscribed(user_id, context, channel) for channel in CHANNEL_USERNAMES]):
        await update.message.reply_text("Iltimos, avval barcha kanalga obuna bo‘ling.")
        return

    number = update.message.text
    video_info = movies_data.get(number)
    if video_info:
        if "part_data" in video_info:
            for part in video_info["part_data"]:
                await update.message.reply_video(
                    video=part["part_url"],
                    caption=f"📄 Kino nomi: {video_info['title']}\n🔗 Qism: {part['part_name']}\n👁 Ko‘rilganlar: {video_info['views']}",
                )
        elif "video_url" in video_info:
            await update.message.reply_video(
                video=video_info["video_url"],
                caption=f"📄 Kino nomi: {video_info['title']}\n👁 Ko‘rilganlar: {video_info['views']}",
            )
        else:
            await update.message.reply_text("Uzr, bu kinoda hech qanday ma'lumot topilmadi.")
            return

        video_info["views"] += 1
        save_json("movies.json", movies_data)
    else:
        await update.message.reply_text("Uzr, bu raqamga mos video topilmadi.")

# Botni webhook orqali ishga tushirish
async def main() -> None:
    bot_token = os.environ.get("BOT_TOKEN")
    if not bot_token:
        logger.error("BOT_TOKEN environment o'zgaruvchisi topilmadi!")
        return

    application = Application.builder().token(bot_token).read_timeout(10).write_timeout(10).build()

    # Webhook sozlamalari (Railway domeni bilan)
    port = int(os.environ.get("PORT", 8080))
    webhook_url = f"https://{os.environ.get('RAILWAY_STATIC_URL', 'your-domain.up.railway.app')}/webhook"
    await application.bot.set_webhook(url=webhook_url)

    # Handler'lar
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(check_subscription, pattern="check_sub"))
    application.add_handler(CallbackQueryHandler(show_user_count, pattern="user_count"))

    # ConversationHandler for adding movies with parts
    conv_handler_parts = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_panel, pattern="add_movie_parts")],
        states={
            MOVIE_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, movie_title)],
            MOVIE_PARTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, movie_parts)],
            MOVIE_PART_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, movie_part_name)],
            MOVIE_PART_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, movie_part_url)],
            MOVIE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, movie_number)],
        },
        fallbacks=[],
    )

    # ConversationHandler for adding simple movies
    conv_handler_simple = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_panel, pattern="add_simple_movie")],
        states={
            SIMPLE_MOVIE_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, simple_movie_title)],
            SIMPLE_MOVIE_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, simple_movie_url)],
            SIMPLE_MOVIE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, simple_movie_number)],
        },
        fallbacks=[],
    )

    # ConversationHandler for deleting movies
    conv_handler_delete = ConversationHandler(
        entry_points=[CallbackQueryHandler(delete_movie, pattern="delete_movie")],
        states={
            DELETE_MOVIE: [CallbackQueryHandler(confirm_delete_movie, pattern="^delete_")],
        },
        fallbacks=[],
    )

    # ConversationHandler for removing channels
    conv_handler_remove_channel = ConversationHandler(
        entry_points=[CallbackQueryHandler(remove_channel, pattern="remove_channel")],
        states={
            REMOVE_CHANNEL: [
                CallbackQueryHandler(select_channel, pattern="^select_"),
                CallbackQueryHandler(confirm_delete_channel, pattern="^confirm_delete_"),
                CallbackQueryHandler(cancel_delete, pattern="cancel_delete"),
            ],
        },
        fallbacks=[],
    )

    # ConversationHandler for broadcasting messages
    conv_handler_broadcast = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast, pattern="broadcast")],
        states={
            BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_broadcast_message)],
        },
        fallbacks=[],
    )

    application.add_handler(conv_handler_parts)
    application.add_handler(conv_handler_simple)
    application.add_handler(conv_handler_delete)
    application.add_handler(conv_handler_remove_channel)
    application.add_handler(conv_handler_broadcast)
    application.add_handler(CallbackQueryHandler(admin_panel))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\d+$"), handle_number))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^@"), add_channel))

    # Webhook orqali ishga tushirish
    await application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="/webhook",
        secret_token="your_secret_token"  # Opsiyonal, xavfsizlik uchun
    )

if __name__ == "__main__":
    asyncio.run(main())
