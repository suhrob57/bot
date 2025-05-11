import logging
import json
import asyncio
import nest_asyncio
import os
import sys
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
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
from dotenv import load_dotenv
from aiohttp import web

# .env faylidan ma'lumotlarni yuklash
load_dotenv()

# nest_asyncio ni faollashtirish (Render platformasi uchun)
nest_asyncio.apply()

# Bot tokeni, admin ID lar va bildirishnoma kanali ID si
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))
NOTIFICATION_CHANNEL_ID = os.getenv("NOTIFICATION_CHANNEL_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Renderda webhook URL, masalan: https://your-app.onrender.com
PORT = int(os.getenv("PORT", 10000))  # Renderda PORT muhit o'zgaruvchisi

# Logger sozlamalari
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# JSON fayllarni o'qish (Render uchun disk yo'li)
def load_json(filename):
    try:
        # Joriy papka va Render standart yo'llarini tekshirish
        current_dir = os.path.dirname(os.path.abspath(__file__))
        possible_paths = [
            os.path.join(current_dir, filename),                    # Joriy papka
            os.path.join("/opt/render/project", filename),      # Render uchun standart yo'l
            os.path.join("/opt/render/project", filename),          # Yana bir alternativa
            filename                                                # Nisbiy yo'l
        ]

        for path in possible_paths:
            if os.path.exists(path):
                logging.info(f"{filename} fayli topildi: {path}")
                with open(path, "r", encoding="utf-8") as file:
                    return json.load(file)

        raise FileNotFoundError(f"{filename} fayli hech qayerda topilmadi.")

    except FileNotFoundError as e:
        logging.error(f"{filename} fayli topilmadi: {e}")
        return {} if filename in ["movies.json", "users.json"] else []

    except json.JSONDecodeError as e:
        logging.error(f"{filename} faylida JSON formati xato: {e}")
        return {} if filename in ["movies.json", "users.json"] else []


def save_json(filename, data):
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        possible_paths = [
            os.path.join(current_dir, filename),
            os.path.join("/opt/render/project", filename),
            os.path.join("/opt/render/project", filename),
        ]
        # Birinchi topilgan yo'lga saqlash
        for path in possible_paths:
            dir_path = os.path.dirname(path)
            if os.path.exists(dir_path):
                with open(path, "w", encoding="utf-8") as file:
                    json.dump(data, file, ensure_ascii=False, indent=4)
                logging.info(f"{filename} fayliga yozildi: {path}")
                return
        logging.error(f"{filename} faylini saqlash uchun papka topilmadi.")
    except Exception as e:
        logging.error(f"{filename} fayliga yozishda xatolik: {e}")

# Fayllarni yuklash
movies_data = load_json("movies.json")
CHANNELS = load_json("channels.json")  # Public va private kanallar ro'yxati
users_data = load_json("users.json")

# Foydalanuvchilarni saqlash uchun funksiyalar
def save_users(users):
    save_json("users.json", users)

# ConversationHandler uchun holatlar
MOVIE_TITLE, MOVIE_PARTS, MOVIE_PART_URL, MOVIE_NUMBER = range(4)  # MOVIE_PART_NAME olib tashlandi
SIMPLE_MOVIE_TITLE, SIMPLE_MOVIE_URL, SIMPLE_MOVIE_NUMBER = range(4, 7)
DELETE_MOVIE = 7
REMOVE_CHANNEL = 8
BROADCAST_MESSAGE = 9
ADD_CHANNEL_TYPE, ADD_CHANNEL_ID = range(10, 12)
ADD_NEW_PART_SELECT, ADD_NEW_PART_NAME, ADD_NEW_PART_URL = range(17, 20)
POST_TO_CHANNEL, POST_TYPE, POST_TEXT, POST_MEDIA, POST_BUTTON_TEXT, POST_BUTTON_URL = range(20, 26)

# Obunani tekshirish (username yoki chat_id asosida)
async def is_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE, channel) -> bool:
    try:
        if isinstance(channel, str) and channel.startswith("@"):  # Public kanal
            chat_member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
        else:  # Private kanal (chat_id ishlatiladi)
            chat_member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
        return chat_member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logging.error(f"Obunani tekshirishda xatolik: {e}")
        return False

# Kanal ID-sini aniqlash funksiyasi
async def get_channel_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        logging.debug("Update obyektida xabar mavjud emas.")
        return
    if update.message.chat.type in ["channel", "supergroup"]:
        chat_id = update.message.chat_id
        await update.message.reply_text(f"Bu kanalning ID-si: {chat_id}")
        logging.info(f"Kanal ID-si: {chat_id}")
    else:
        await update.message.reply_text("Bu funksiya faqat kanallarda ishlaydi!")

# Start komandasi
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

        notification_message = (
            f"Yangi foydalanuvchi qo'shildi!\n"
            f"Ism: {first_name}\n"
            f"Username: @{username}\n"
            f"Profil: {profile_url}"
        )
        try:
            await context.bot.send_message(
                chat_id=NOTIFICATION_CHANNEL_ID,
                text=notification_message
            )
        except Exception as e:
            logging.error(f"Kanalga xabar yuborishda xatolik: {e}")

    if user_id in ADMIN_IDS:
        keyboard = [
            [InlineKeyboardButton("🎮 Qismli Anime qo‘shish", callback_data="add_movie_parts")],
            [InlineKeyboardButton("🎬 Oddiy Anime qo‘shish", callback_data="add_simple_movie")],
            [InlineKeyboardButton("📢 Kanal qo‘shish", callback_data="add_channel")],
            [InlineKeyboardButton("❌ Kanalni o'chirish", callback_data="remove_channel")],
            [InlineKeyboardButton("🗑 Animeni o'chirish", callback_data="delete_movie")],
            [InlineKeyboardButton("➕ Yangi qism qo‘shish", callback_data="add_new_part")],
            [InlineKeyboardButton("📤 Kanalga post yuborish", callback_data="post_to_channel")],
            [InlineKeyboardButton("👥 Foydalanuvchilar soni", callback_data="user_count")],
            [InlineKeyboardButton("📩 Foydalanuvchilarga xabar yuborish", callback_data="broadcast")],
            [InlineKeyboardButton("🔄 Botni qayta ishga tushirish", callback_data="restart_bot")],  # Yangi tugma
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Admin paneliga xush kelibsiz!", reply_markup=reply_markup)
        return

    is_all_subscribed = all([await is_subscribed(user_id, context, channel) for channel in CHANNELS])
    if is_all_subscribed:
        await update.message.reply_text("Xush kelibsiz! Botdan foydalanish uchun anime raqamini yuboring.")
    else:
        keyboard = []
        for i, channel in enumerate(CHANNELS):
            if isinstance(channel, str) and channel.startswith("@"):  # Public kanal
                keyboard.append([InlineKeyboardButton(f"{i+1}-kanalga obuna bo‘lish", url=f"https://t.me/{channel[1:]}")])
            else:  # Private kanal
                keyboard.append([InlineKeyboardButton(f"{i+1}-kanalga obuna bo‘lish", url=f"https://t.me/+{channel}")])
        keyboard.append([InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_sub")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:", reply_markup=reply_markup)

# Obunani tekshirish tugmasi
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_all_subscribed = all([await is_subscribed(user_id, context, channel) for channel in CHANNELS])
    if is_all_subscribed:
        await query.edit_message_text("✅ Siz barcha kanallarga obuna bo‘lgansiz! Botdan foydalanishingiz mumkin.")
    else:
        await query.edit_message_text("❌ Siz hali barcha kanallarga obuna bo‘lmagansiz. Iltimos, obuna bo‘ling.")

# Foydalanuvchilar sonini ko'rsatish
async def send_user_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_count = len(users_data)
    await query.edit_message_text(f"Foydalanuvchilar soni: {user_count}")

# Yangi qism qo'shish jarayonini boshlash
async def add_new_part(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not movies_data:
        await query.edit_message_text("Qism qo‘shish uchun anime mavjud emas!")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(f"{number}: {data['title']}", callback_data=f"add_part_{number}")]
        for number, data in movies_data.items() if "part_data" in data
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Yangi qism qo‘shish uchun animeni tanlang:", reply_markup=reply_markup)
    return ADD_NEW_PART_SELECT

# Kinoni tanlash
async def select_movie_for_new_part(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    movie_number = query.data.replace("add_part_", "")

    if movie_number not in movies_data or "part_data" not in movies_data[movie_number]:
        await query.edit_message_text("Anime topilmadi!")
        return ConversationHandler.END

    context.user_data["movie_to_add_part"] = movie_number
    await query.edit_message_text("Yangi qism nomini kiriting:")
    return ADD_NEW_PART_NAME

# Yangi qism URL manzilini so‘rash
async def add_new_part_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    part_name = update.message.text
    context.user_data["new_part_name"] = part_name
    await update.message.reply_text("Yangi qism URL manzilini kiriting:")
    return ADD_NEW_PART_URL

# Yangi qism ma’lumotlarini saqlash
async def add_new_part_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    part_url = update.message.text
    movie_number = context.user_data["movie_to_add_part"]
    part_name = context.user_data["new_part_name"]

    new_part_data = {
        "part_name": part_name,
        "part_url": part_url,
    }

    movies_data[movie_number]["part_data"].append(new_part_data)
    save_json("movies.json", movies_data)

    await update.message.reply_text(f"✅ Yangi qism muvaffaqiyatli qo‘shildi: {part_name}")
    return ConversationHandler.END

# Admin paneli tugmalari
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "add_movie_parts":
        await query.message.reply_text("Qismli anime qo‘shish uchun anime nomini kiriting:")
        return MOVIE_TITLE
    elif query.data == "add_simple_movie":
        await query.message.reply_text("Oddiy anime qo‘shish uchun anime nomini kiriting:")
        return SIMPLE_MOVIE_TITLE
    elif query.data == "add_channel":
        return await add_channel(update, context)
    elif query.data == "remove_channel":
        return await remove_channel(update, context)
    elif query.data == "delete_movie":
        return await delete_movie(update, context)
    elif query.data == "broadcast":
        return await broadcast(update, context)
    elif query.data == "post_to_channel":
        return await post_to_channel(update, context)
    elif query.data == "restart_bot":
        return await restart_bot(update, context)
    return ConversationHandler.END

# Botni qayta ishga tushirish
async def restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("Siz admin emassiz!")
        return

    await query.edit_message_text("Bot qayta ishga tushirilmoqda...")
    # Renderda jarayonni qayta boshlash uchun
    os._exit(0)

# Kino qo‘shish: Kino nomini so'rash
async def movie_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["movie_title"] = update.message.text
    await update.message.reply_text("Anime nechta qismdan iborat? (Raqamda kiriting, masalan: 7)")
    return MOVIE_PARTS

# Kino qo‘shish: Kino qismlar sonini so'rash
async def movie_parts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        parts = int(update.message.text)
        if parts <= 0:
            raise ValueError
        context.user_data["movie_parts"] = parts
        context.user_data["current_part"] = 1
        context.user_data["movie_part_data"] = []
        # Qism nomlarini avtomatik yaratish
        for i in range(1, parts + 1):
            context.user_data["movie_part_data"].append({
                "part_name": f"{i}-qism",
                "part_url": None
            })
        await update.message.reply_text("1-qism URL manzilini kiriting:")
        return MOVIE_PART_URL
    except ValueError:
        await update.message.reply_text("Xatolik! Iltimos, to‘g‘ri raqam kiriting:")
        return MOVIE_PARTS

# Kino qo‘shish: Har bir qismning URL manzilini so'rash
async def movie_part_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    part_url = update.message.text
    current_part = context.user_data["current_part"] - 1  # Indeks 0 dan boshlanadi
    context.user_data["movie_part_data"][current_part]["part_url"] = part_url

    if context.user_data["current_part"] < context.user_data["movie_parts"]:
        context.user_data["current_part"] += 1
        await update.message.reply_text(f"{context.user_data['current_part']}-qism URL manzilini kiriting:")
        return MOVIE_PART_URL
    else:
        await update.message.reply_text("Anime raqamini kiriting:")
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

    await update.message.reply_text(f"✅ Qismli Anime qo‘shildi! {title} ({parts} qism)")
    return ConversationHandler.END

# Oddiy kino qo'shish: Kino nomini so'rash
async def simple_movie_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["movie_title"] = update.message.text
    await update.message.reply_text("Anime URL manzilini kiriting:")
    return SIMPLE_MOVIE_URL

# Oddiy kino qo'shish: Kino URL manzilini so'rash
async def simple_movie_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["movie_url"] = update.message.text
    await update.message.reply_text("Anime raqamini kiriting:")
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

    await update.message.reply_text(f"✅ Oddiy Anime qo‘shildi! {title}")
    return ConversationHandler.END

# Kino o'chirish
async def delete_movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not movies_data:
        await query.edit_message_text("O'chirish uchun Anime mavjud emas!")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(f"{number}: {data['title']}", callback_data=f"delete_{number}")]
        for number, data in movies_data.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("O'chirish uchun Animeni tanlang:", reply_markup=reply_markup)
    return DELETE_MOVIE

# Kino o'chirishni tasdiqlash
async def confirm_delete_movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    movie_number = query.data.replace("delete_", "")

    if movie_number in movies_data:
        del movies_data[movie_number]
        save_json("movies.json", movies_data)
        await query.edit_message_text(f"✅ Anime o'chirildi: {movie_number}")
    else:
        await query.edit_message_text("Anime topilmadi!")
    return ConversationHandler.END

# Kanal qo‘shish jarayonini boshlash
async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("Siz admin emassiz!")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("📢 Public kanal", callback_data="public_channel")],
        [InlineKeyboardButton("🔒 Private kanal", callback_data="private_channel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("Qaysi turdagi kanal qo‘shmoqchisiz?", reply_markup=reply_markup)
    return ADD_CHANNEL_TYPE

# Kanal turini tanlash
async def channel_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["channel_type"] = query.data

    if query.data == "public_channel":
        await query.message.reply_text("Public kanal username’ni @belgisi bilan kiriting (masalan: @channelname):")
    else:  # private_channel
        await query.message.reply_text("Private kanalning chat ID’sini kiriting (masalan: -1001234567890):")
    return ADD_CHANNEL_ID

# Kanalni qo‘shish
async def add_channel_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("Siz admin emassiz!")
        return ConversationHandler.END

    channel_input = update.message.text.strip()
    channel_type = context.user_data.get("channel_type")

    if channel_type == "public_channel":
        if not channel_input.startswith("@"):
            await update.message.reply_text("Xatolik! Kanal username’ni @belgisi bilan kiriting.")
            return ADD_CHANNEL_ID
        channel = channel_input
    else:  # private_channel
        try:
            channel = int(channel_input)
            if channel > 0:
                await update.message.reply_text("Xatolik! Private kanal ID’si manfiy bo‘lishi kerak (masalan: -1001234567890).")
                return ADD_CHANNEL_ID
        except ValueError:
            await update.message.reply_text("Xatolik! To‘g‘ri chat ID kiriting (masalan: -1001234567890).")
            return ADD_CHANNEL_ID

    if channel in CHANNELS:
        await update.message.reply_text("Bu kanal allaqachon qo‘shilgan.")
        return ConversationHandler.END

    CHANNELS.append(channel)
    save_json("channels.json", CHANNELS)
    await update.message.reply_text(f"✅ Kanal qo‘shildi: {channel}")
    return ConversationHandler.END

# Kanalni o'chirish
async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("Siz admin emassiz!")
        return ConversationHandler.END

    if not CHANNELS:
        await query.edit_message_text("O‘chirish uchun kanal mavjud emas!")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(str(channel), callback_data=f"select_{channel}")]
        for channel in CHANNELS
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

    if channel_to_delete.startswith("@"):
        channel_to_remove = channel_to_delete
    else:
        try:
            channel_to_remove = int(channel_to_delete)
        except ValueError:
            await query.edit_message_text("Kanal ID formati noto‘g‘ri!")
            return ConversationHandler.END

    if channel_to_remove in CHANNELS:
        CHANNELS.remove(channel_to_remove)
        save_json("channels.json", CHANNELS)
        await query.edit_message_text(f"✅ Kanal o‘chirildi: {channel_to_delete}")
    else:
        await query.edit_message_text("Kanal topilmadi!")
    return ConversationHandler.END

# Kanalni o'chirishni bekor qilish
async def cancel_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Kanalni o'chirish bekor qilindi.")
    return ConversationHandler.END

# Broadcast jarayonini boshlash
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Foydalanuvchilarga yuboriladigan xabarni kiriting:")
    return BROADCAST_MESSAGE

# Broadcast xabarini yuborish
async def send_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message.text
    for user_id in users_data.keys():
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
        except Exception as e:
            logging.error(f"Xabar yuborishda xatolik {user_id}: {e}")
    await update.message.reply_text("✅ Xabar barcha foydalanuvchilarga yuborildi!")
    return ConversationHandler.END

# Kanalga post yuborish jarayonini boshlash
async def post_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not CHANNELS:
        await query.edit_message_text("Post yuborish uchun kanal mavjud emas! Avval kanal qo‘shing.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(str(channel), callback_data=f"post_select_{channel}")]
        for channel in CHANNELS
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text("Post yuborish uchun kanalni tanlang:", reply_markup=reply_markup)
    except Exception as e:
        logging.error(f"Kanal ro‘yxatini yangilashda xatolik: {e}")
        await query.message.reply_text("Xatolik yuz berdi, qaytadan urinib ko‘ring.")
        return ConversationHandler.END

    return POST_TO_CHANNEL

# Kanal tanlangandan so'ng xabar turini so'rash
async def select_channel_for_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    logging.info(f"Callback data qabul qilindi: {callback_data}")

    if not callback_data.startswith("post_select_"):
        logging.error("Noto‘g‘ri callback data formati")
        await query.edit_message_text("Noto‘g‘ri tanlov! Qaytadan urinib ko‘ring.")
        return ConversationHandler.END

    channel_id = callback_data.replace("post_select_", "")
    if channel_id.startswith("@"):
        context.user_data["selected_channel"] = channel_id
    else:
        try:
            context.user_data["selected_channel"] = int(channel_id)
        except ValueError:
            logging.error(f"Kanal ID ni raqamga aylantirib bo‘lmadi: {channel_id}")
            await query.edit_message_text("Kanal tanlashda xatolik! Qaytadan urinib ko‘ring.")
            return ConversationHandler.END

    logging.info(f"Tanlangan kanal: {context.user_data['selected_channel']}")

    keyboard = [
        [InlineKeyboardButton("📝 Faqat matn", callback_data="type_text")],
        [InlineKeyboardButton("🖼 Rasm bilan", callback_data="type_photo")],
        [InlineKeyboardButton("🎥 Video bilan", callback_data="type_video")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(
            f"Tanlangan kanal: {channel_id}\nQanday post yubormoqchisiz?",
            reply_markup=reply_markup
        )
    except Exception as e:
        logging.error(f"Xabar turini so‘rashda xatolik: {e}")
        await query.message.reply_text("Xatolik yuz berdi, qaytadan urinib ko‘ring.")
        return ConversationHandler.END

    return POST_TYPE

# Xabar turini tanlash
async def select_post_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    post_type = query.data.replace("type_", "")
    context.user_data["post_type"] = post_type

    await query.edit_message_text("Post matnini kiriting (masalan: Anime nomi, qism, fasl, janr):")
    return POST_TEXT

# Post matnini qabul qilish
async def receive_post_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["post_text"] = update.message.text

    post_type = context.user_data["post_type"]
    if post_type == "text":
        await update.message.reply_text("Tugma uchun matn kiriting (masalan: Ko‘rish, Yuklab olish):")
        return POST_BUTTON_TEXT
    else:
        await update.message.reply_text(f"{post_type.capitalize()} faylini yuboring:")
        return POST_MEDIA

# Media faylni qabul qilish
async def receive_post_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    post_type = context.user_data["post_type"]

    if post_type == "photo" and update.message.photo:
        context.user_data["post_media"] = update.message.photo[-1].file_id
    elif post_type == "video" and update.message.video:
        context.user_data["post_media"] = update.message.video.file_id
    else:
        await update.message.reply_text("Noto'g'ri fayl turi yuborildi! Iltimos, qaytadan yuboring.")
        return POST_MEDIA

    await update.message.reply_text("Tugma uchun matn kiriting (masalan: Ko‘rish, Yuklab olish):")
    return POST_BUTTON_TEXT

# Tugma matnini qabul qilish
async def receive_button_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["button_text"] = update.message.text
    await update.message.reply_text("Tugma uchun URL kiriting (masalan: https://t.me/your_channel):")
    return POST_BUTTON_URL

# Tugma URL ni qabul qilib, postni yuborish
async def send_post_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    button_url = update.message.text
    channel_id = context.user_data["selected_channel"]
    post_type = context.user_data["post_type"]
    post_text = context.user_data["post_text"]
    button_text = context.user_data["button_text"]

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"✨{button_text}✨", url=button_url)]])

    try:
        if post_type == "text":
            await context.bot.send_message(
                chat_id=channel_id,
                text=post_text,
                reply_markup=keyboard
            )
        elif post_type == "photo":
            await context.bot.send_photo(
                chat_id=channel_id,
                photo=context.user_data["post_media"],
                caption=post_text,
                reply_markup=keyboard
            )
        elif post_type == "video":
            await context.bot.send_video(
                chat_id=channel_id,
                video=context.user_data["post_media"],
                caption=post_text,
                reply_markup=keyboard
            )
        await update.message.reply_text(f"✅ Post {channel_id} kanaliga muvaffaqiyatli yuborildi!")
    except Exception as e:
        logging.error(f"Post yuborishda xatolik: {e}")
        await update.message.reply_text(f"❌ Xabar yuborishda xatolik: {str(e)}")

    return ConversationHandler.END

# Raqamni qabul qilish va video yuborish
async def handle_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if not all([await is_subscribed(user_id, context, channel) for channel in CHANNELS]):
        await update.message.reply_text("Iltimos, avval barcha kanalga obuna bo‘ling.")
        return

    number = update.message.text
    video_info = movies_data.get(number)
    if video_info:
        if "part_data" in video_info and video_info["part_data"]:
            # Birinchi qismni yuborish
            first_part = video_info["part_data"][0]
            # Sahifalash uchun ma'lumotlarni saqlash
            context.user_data["current_page"] = 0  # Birinchi sahifa
            context.user_data["movie_number"] = number
            context.user_data["selected_part_index"] = 0  # Birinchi qism tanlangan

            # Tugmalarni sahifalash bilan yaratish
            parts = video_info["part_data"]
            parts_per_page = 5  # Har bir sahifada 5 ta qism
            start_idx = context.user_data["current_page"] * parts_per_page
            end_idx = start_idx + parts_per_page
            visible_parts = parts[start_idx:end_idx]

            # Tugmalar ro'yxatini tayyorlash (tanlangan qismdan tashqari)
            keyboard = []
            current_row = []
            for i, part in enumerate(parts):
                if i != 0:  # Birinchi qismni o'tkazib yuboramiz (hozir ko'rsatilmoqda)
                    if start_idx <= i < end_idx:
                        current_row.append(InlineKeyboardButton(
                            f"{part['part_name']}", callback_data=f"part_{number}_{i}"
                        ))
                        if len(current_row) == 5:  # Har bir qatorda 5 ta tugma
                            keyboard.append(current_row)
                            current_row = []
            if current_row:  # Qolgan tugmalarni qatorga qo'shish
                keyboard.append(current_row)

            # Navigatsiya tugmalari
            nav_row = []
            total_pages = (len(parts) - 1 + parts_per_page - 1) // parts_per_page  # Sahifalar soni
            if context.user_data["current_page"] > 0:
                nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"nav_{number}_prev"))
            if context.user_data["current_page"] < total_pages - 1:
                nav_row.append(InlineKeyboardButton("➡️", callback_data=f"nav_{number}_next"))
            if nav_row:
                keyboard.append(nav_row)

            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            # Video xabarini yuborish
            message = await update.message.reply_video(
                video=first_part["part_url"],
                caption=f"📄 Anime nomi: {video_info['title']}\n🔗 Qism: {first_part['part_name']}\n👁 Ko‘rilganlar: {video_info['views']}",
                reply_markup=reply_markup
            )
            # Xabar ID sini saqlash
            context.user_data["last_message_id"] = message.message_id
            context.user_data["last_chat_id"] = message.chat_id
            context.user_data["last_movie_number"] = number

        elif "video_url" in video_info:
            await update.message.reply_video(
                video=video_info["video_url"],
                caption=f"📄 Anime nomi: {video_info['title']}\n👁 Ko‘rilganlar: {video_info['views']}",
            )
        else:
            await update.message.reply_text("Uzr, bu Animeda hech qanday ma'lumot topilmadi.")
            return

        video_info["views"] += 1
        save_json("movies.json", movies_data)
    else:
        await update.message.reply_text("Uzr, bu raqamga mos Anime topilmadi.")

# Qism tanlash tugmasi
async def handle_part_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not all([await is_subscribed(user_id, context, channel) for channel in CHANNELS]):
        await query.edit_message_text("Iltimos, avval barcha kanalga obuna bo‘ling.")
        return

    data = query.data.split("_")
    movie_number = data[1]
    part_index = int(data[2])

    video_info = movies_data.get(movie_number)
    if video_info and "part_data" in video_info and part_index < len(video_info["part_data"]):
        # Avvalgi xabarni tahrirlash (tugmalarni olib tashlash)
        last_message_id = context.user_data.get("last_message_id")
        last_chat_id = context.user_data.get("last_chat_id")
        if last_message_id and last_chat_id:
            try:
                await context.bot.edit_message_reply_markup(
                    chat_id=last_chat_id,
                    message_id=last_message_id,
                    reply_markup=None
                )
            except Exception as e:
                logging.error(f"Avvalgi xabarni tahrirlashda xatolik: {e}")

        # Tanlangan qismni yuborish
        part = video_info["part_data"][part_index]
        context.user_data["selected_part_index"] = part_index  # Tanlangan qism indeksini saqlash

        # Tugmalarni sahifalash bilan yaratish
        parts = video_info["part_data"]
        parts_per_page = 5  # Har bir sahifada 5 ta qism
        current_page = context.user_data.get("current_page", 0)
        start_idx = current_page * parts_per_page
        end_idx = start_idx + parts_per_page
        visible_parts = parts[start_idx:end_idx]

        # Tugmalar ro'yxatini tayyorlash (tanlangan qismdan tashqari)
        keyboard = []
        current_row = []
        for i, part in enumerate(parts):
            if i != part_index:  # Tanlangan qismni o'tkazib yuboramiz
                if start_idx <= i < end_idx:
                    current_row.append(InlineKeyboardButton(
                        f"{part['part_name']}", callback_data=f"part_{movie_number}_{i}"
                    ))
                    if len(current_row) == 5:  # Har bir qatorda 5 ta tugma
                        keyboard.append(current_row)
                        current_row = []
        if current_row:  # Qolgan tugmalarni qatorga qo'shish
            keyboard.append(current_row)

        # Navigatsiya tugmalari
        nav_row = []
        total_pages = (len(parts) - 1 + parts_per_page - 1) // parts_per_page  # Sahifalar soni
        if current_page > 0:
            nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"nav_{movie_number}_prev"))
        if current_page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("➡️", callback_data=f"nav_{movie_number}_next"))
        if nav_row:
            keyboard.append(nav_row)

        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        # Yangi video xabarini yuborish
        message = await query.message.reply_video(
            video=part["part_url"],
            caption=f"📄 Anime nomi: {video_info['title']}\n🔗 Qism: {part['part_name']}\n👁 Ko‘rilganlar: {video_info['views']}",
            reply_markup=reply_markup
        )
        # Yangi xabar ID sini saqlash
        context.user_data["last_message_id"] = message.message_id
        context.user_data["last_chat_id"] = message.chat_id
        context.user_data["last_movie_number"] = movie_number

        video_info["views"] += 1
        save_json("movies.json", movies_data)
    else:
        await query.message.reply_text("❌ Boshqa qism topilmadi!")

# Navigatsiya tugmalarini boshqarish
async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    movie_number = data[1]
    action = data[2]  # "prev" yoki "next"

    video_info = movies_data.get(movie_number)
    if not video_info or "part_data" not in video_info:
        await query.message.reply_text("❌ Boshqa qism topilmadi!")
        return

    # Sahifani yangilash
    current_page = context.user_data.get("current_page", 0)
    parts = video_info["part_data"]
    parts_per_page = 5
    total_pages = (len(parts) - 1 + parts_per_page - 1) // parts_per_page

    if action == "prev" and current_page > 0:
        context.user_data["current_page"] -= 1
    elif action == "next" and current_page < total_pages - 1:
        context.user_data["current_page"] += 1

    # Yangi tugmalar ro'yxatini yaratish
    current_page = context.user_data["current_page"]
    start_idx = current_page * parts_per_page
    end_idx = start_idx + parts_per_page
    visible_parts = parts[start_idx:end_idx]

    selected_part_index = context.user_data.get("selected_part_index", 0)
    keyboard = []
    current_row = []
    for i, part in enumerate(parts):
        if i != selected_part_index:  # Tanlangan qismni o'tkazib yuboramiz
            if start_idx <= i < end_idx:
                current_row.append(InlineKeyboardButton(
                    f"{part['part_name']}", callback_data=f"part_{movie_number}_{i}"
                ))
                if len(current_row) == 5:
                    keyboard.append(current_row)
                    current_row = []
    if current_row:
        keyboard.append(current_row)

    # Navigatsiya tugmalari
    nav_row = []
    if current_page > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"nav_{movie_number}_prev"))
    if current_page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"nav_{movie_number}_next"))
    if nav_row:
        keyboard.append(nav_row)

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    # Avvalgi xabarni tahrirlash
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=context.user_data["last_chat_id"],
            message_id=context.user_data["last_message_id"],
            reply_markup=reply_markup
        )
    except Exception as e:
        logging.error(f"Xabarni tahrirlashda xatolik: {e}")

# Webhook so'rovlarini qabul qilish
async def webhook_handler(request):
    update = await request.json()
    update = Update.de_json(update, application.bot)
    await application.process_update(update)
    return web.Response(text="OK")

# Botni ishga tushirish
async def main() -> None:
    global application
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler_parts = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_panel, pattern="add_movie_parts")],
        states={
            MOVIE_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, movie_title)],
            MOVIE_PARTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, movie_parts)],
            MOVIE_PART_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, movie_part_url)],
            MOVIE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, movie_number)],
        },
        fallbacks=[],
        per_message=True,
    )

    conv_handler_simple = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_panel, pattern="add_simple_movie")],
        states={
            SIMPLE_MOVIE_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, simple_movie_title)],
            SIMPLE_MOVIE_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, simple_movie_url)],
            SIMPLE_MOVIE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, simple_movie_number)],
        },
        fallbacks=[],
        per_message=True,
    )

    conv_handler_delete = ConversationHandler(
        entry_points=[CallbackQueryHandler(delete_movie, pattern="delete_movie")],
        states={
            DELETE_MOVIE: [CallbackQueryHandler(confirm_delete_movie, pattern="^delete_")],
        },
        fallbacks=[],
        per_message=True,
    )

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
        per_message=True,
    )

    conv_handler_broadcast = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast, pattern="broadcast")],
        states={
            BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_broadcast_message)],
        },
        fallbacks=[],
        per_message=True,
    )

    conv_handler_add_channel = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_channel, pattern="add_channel")],
        states={
            ADD_CHANNEL_TYPE: [CallbackQueryHandler(channel_type, pattern="^(public_channel|private_channel)$")],
            ADD_CHANNEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_channel_id)],
        },
        fallbacks=[],
        per_message=True,
    )

    conv_handler_add_new_part = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_new_part, pattern="add_new_part")],
        states={
            ADD_NEW_PART_SELECT: [CallbackQueryHandler(select_movie_for_new_part, pattern="^add_part_")],
            ADD_NEW_PART_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_new_part_name)],
            ADD_NEW_PART_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_new_part_url)],
        },
        fallbacks=[],
        per_message=True,
    )

    conv_handler_post_to_channel = ConversationHandler(
        entry_points=[CallbackQueryHandler(post_to_channel, pattern="post_to_channel")],
        states={
            POST_TO_CHANNEL: [CallbackQueryHandler(select_channel_for_post, pattern="^post_select_")],
            POST_TYPE: [CallbackQueryHandler(select_post_type, pattern="^type_")],
            POST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_post_text)],
            POST_MEDIA: [MessageHandler(filters.PHOTO | filters.VIDEO, receive_post_media)],
            POST_BUTTON_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_button_text)],
            POST_BUTTON_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_post_to_channel)],
        },
        fallbacks=[],
        per_message=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(check_subscription, pattern="check_sub"))
    application.add_handler(CallbackQueryHandler(send_user_count, pattern="user_count"))
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL, get_channel_id))
    application.add_handler(conv_handler_parts)
    application.add_handler(conv_handler_simple)
    application.add_handler(conv_handler_delete)
    application.add_handler(conv_handler_remove_channel)
    application.add_handler(conv_handler_broadcast)
    application.add_handler(conv_handler_add_channel)
    application.add_handler(conv_handler_add_new_part)
    application.add_handler(conv_handler_post_to_channel)
    application.add_handler(CallbackQueryHandler(handle_part_selection, pattern="^part_"))
    application.add_handler(CallbackQueryHandler(handle_navigation, pattern="^nav_"))
    application.add_handler(CallbackQueryHandler(admin_panel))
    application.add_handler(CallbackQueryHandler(restart_bot, pattern="restart_bot"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\d+$"), handle_number))

    # Webhookni sozlash
    await application.bot.set_webhook(url=WEBHOOK_URL)
    app = web.Application()
    app.router.add_post('/', webhook_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

    # Botni ishga tushirish
    await application.initialize()
    await application.start()
    logging.info(f"Bot webhook rejimida ishga tushdi: {WEBHOOK_URL}")

    # Serverni doimiy ishlashini ta'minlash
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    # Vaqt mintaqasini aniq belgilash
    os.environ['TZ'] = 'UTC'
    asyncio.run(main())
