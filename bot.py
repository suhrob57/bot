import logging
import json
import asyncio
import nest_asyncio
import os
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
from dotenv import load_dotenv
from aiohttp import web
import uuid

# .env faylidan ma'lumotlarni yuklash
load_dotenv()

# nest_asyncio ni faollashtirish
nest_asyncio.apply()

# Bot sozlamalari
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")) if os.getenv("ADMIN_IDS") else [])
NOTIFICATION_CHANNEL_ID = os.getenv("NOTIFICATION_CHANNEL_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 10000))

# Logger sozlamalari
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# JSON fayl operatsiyalari
def load_json(filename):
    file_path = os.path.join(os.getcwd(), filename)
    try:
        if not os.path.exists(file_path):
            default_data = {} if filename in ["movies.json", "users.json"] else []
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump(default_data, file, ensure_ascii=False, indent=4)
            logger.info(f"{filename} fayli yaratildi: {file_path}")
            return default_data

        with open(file_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as e:
        logger.error(f"{filename} faylini o'qishda xatolik: {e}")
        return {} if filename in ["movies.json", "users.json"] else []

def save_json(filename, data):
    file_path = os.path.join(os.getcwd(), filename)
    try:
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
        logger.info(f"{filename} fayliga muvaffaqiyatli yozildi")
    except Exception as e:
        logger.error(f"{filename} fayliga yozishda xatolik: {e}")
        raise

# Ma'lumotlarni yuklash
movies_data = load_json("movies.json")
CHANNELS = load_json("channels.json")
users_data = load_json("users.json")

# ConversationHandler holatlari
MOVIE_TITLE, MOVIE_PARTS, MOVIE_PART_URL, MOVIE_NUMBER = range(4)
SIMPLE_MOVIE_TITLE, SIMPLE_MOVIE_URL, SIMPLE_MOVIE_NUMBER = range(4, 7)
DELETE_MOVIE = 7
REMOVE_CHANNEL = 8
BROADCAST_MESSAGE = 9
ADD_CHANNEL_TYPE, ADD_CHANNEL_ID = range(10, 12)
ADD_NEW_PART_SELECT, ADD_NEW_PART_NAME, ADD_NEW_PART_URL = range(17, 20)
POST_TO_CHANNEL, POST_TYPE, POST_TEXT, POST_MEDIA, POST_BUTTON_TEXT, POST_BUTTON_URL = range(20, 26)

async def is_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE, channel) -> bool:
    try:
        chat_member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
        return chat_member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logger.error(f"Obunani tekshirishda xatolik: {e}")
        return False

async def get_channel_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.chat.type in ["channel", "supergroup"]:
        chat_id = update.message.chat_id
        await update.message.reply_text(f"Bu kanalning ID-si: {chat_id}")
    else:
        await update.message.reply_text("Bu funksiya faqat kanallarda ishlaydi!")

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
        save_json("users.json", users_data)
        
        try:
            await context.bot.send_message(
                chat_id=NOTIFICATION_CHANNEL_ID,
                text=f"Yangi foydalanuvchi:\nIsm: {first_name}\nUsername: @{username}\nProfil: {profile_url}"
            )
        except Exception as e:
            logger.error(f"Kanalga xabar yuborishda xatolik: {e}")

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
            [InlineKeyboardButton("📩 Broadcast", callback_data="broadcast")],
            [InlineKeyboardButton("🔄 Botni qayta ishga tushirish", callback_data="restart_bot")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Admin paneliga xush kelibsiz!", reply_markup=reply_markup)
        return

    is_all_subscribed = all([await is_subscribed(user_id, context, channel) for channel in CHANNELS])
    if is_all_subscribed:
        await update.message.reply_text("Xush kelibsiz! Anime raqamini yuboring.")
    else:
        keyboard = [[InlineKeyboardButton(f"{i+1}-kanal", url=f"https://t.me/{channel[1:]}" if channel.startswith("@") else f"https://t.me/+{channel}")]
                   for i, channel in enumerate(CHANNELS)]
        keyboard.append([InlineKeyboardButton("✅ Tekshirish", callback_data="check_sub")])
        await update.message.reply_text("Botdan foydalanish uchun kanallarga obuna bo‘ling:", reply_markup=InlineKeyboardMarkup(keyboard))

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_all_subscribed = all([await is_subscribed(user_id, context, channel) for channel in CHANNELS])
    await query.edit_message_text("✅ Barcha kanallarga obunasiz!" if is_all_subscribed else "❌ Iltimos, barcha kanallarga obuna bo‘ling.")

async def send_user_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(f"Foydalanuvchilar soni: {len(users_data)}")

async def add_new_part(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not movies_data:
        await query.edit_message_text("Anime mavjud emas!")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(f"{number}: {data['title']}", callback_data=f"add_part_{number}")]
                for number, data in movies_data.items() if "part_data" in data]
    await query.edit_message_text("Yangi qism qo‘shish uchun animeni tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_NEW_PART_SELECT

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

async def add_new_part_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_part_name"] = update.message.text
    await update.message.reply_text("Yangi qism URL manzilini kiriting:")
    return ADD_NEW_PART_URL

async def add_new_part_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    part_url = update.message.text
    movie_number = context.user_data["movie_to_add_part"]
    part_name = context.user_data["new_part_name"]

    movies_data[movie_number]["part_data"].append({
        "part_name": part_name,
        "part_url": part_url,
    })
    save_json("movies.json", movies_data)
    await update.message.reply_text(f"✅ Yangi qism qo‘shildi: {part_name}")
    return ConversationHandler.END

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    handlers = {
        "add_movie_parts": (MOVIE_TITLE, "Qismli anime nomini kiriting:"),
        "add_simple_movie": (SIMPLE_MOVIE_TITLE, "Oddiy anime nomini kiriting:"),
        "add_channel": (await add_channel(update, context), None),
        "remove_channel": (await remove_channel(update, context), None),
        "delete_movie": (await delete_movie(update, context), None),
        "broadcast": (await broadcast(update, context), None),
        "post_to_channel": (await post_to_channel(update, context), None),
        "restart_bot": (await restart_bot(update, context), None)
    }
    
    if query.data in handlers:
        state, message = handlers[query.data]
        if message:
            await query.message.reply_text(message)
        return state
    return ConversationHandler.END

async def restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text("Siz admin emassiz!")
        return
    await query.edit_message_text("Bot qayta ishga tushirilmoqda...")
    os._exit(0)

async def movie_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["movie_title"] = update.message.text
    await update.message.reply_text("Anime nechta qismdan iborat? (Raqamda kiriting)")
    return MOVIE_PARTS

async def movie_parts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        parts = int(update.message.text)
        if parts <= 0:
            raise ValueError
        context.user_data["movie_parts"] = parts
        context.user_data["current_part"] = 1
        context.user_data["movie_part_data"] = [{"part_name": f"{i}-qism", "part_url": None} for i in range(1, parts + 1)]
        await update.message.reply_text("1-qism URL manzilini kiriting:")
        return MOVIE_PART_URL
    except ValueError:
        await update.message.reply_text("Iltimos, to‘g‘ri raqam kiriting:")
        return MOVIE_PARTS

async def movie_part_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    part_url = update.message.text
    current_part = context.user_data["current_part"] - 1
    context.user_data["movie_part_data"][current_part]["part_url"] = part_url

    if context.user_data["current_part"] < context.user_data["movie_parts"]:
        context.user_data["current_part"] += 1
        await update.message.reply_text(f"{context.user_data['current_part']}-qism URL manzilini kiriting:")
        return MOVIE_PART_URL
    await update.message.reply_text("Anime raqamini kiriting:")
    return MOVIE_NUMBER

async def movie_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    number = update.message.text
    if number in movies_data:
        await update.message.reply_text("Bu raqam allaqachon ishlatilgan! Boshqa raqam kiriting:")
        return MOVIE_NUMBER

    movies_data[number] = {
        "title": context.user_data["movie_title"],
        "parts": context.user_data["movie_parts"],
        "part_data": context.user_data["movie_part_data"],
        "views": 0,
    }
    save_json("movies.json", movies_data)
    await update.message.reply_text(f"✅ Qismli Anime qo‘shildi: {context.user_data['movie_title']}")
    return ConversationHandler.END

async def simple_movie_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["movie_title"] = update.message.text
    await update.message.reply_text("Anime URL manzilini kiriting:")
    return SIMPLE_MOVIE_URL

async def simple_movie_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["movie_url"] = update.message.text
    await update.message.reply_text("Anime raqamini kiriting:")
    return SIMPLE_MOVIE_NUMBER

async def simple_movie_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    number = update.message.text
    if number in movies_data:
        await update.message.reply_text("Bu raqam allaqachon ishlatilgan! Boshqa raqam kiriting:")
        return SIMPLE_MOVIE_NUMBER

    movies_data[number] = {
        "title": context.user_data["movie_title"],
        "video_url": context.user_data["movie_url"],
        "views": 0,
    }
    save_json("movies.json", movies_data)
    await update.message.reply_text(f"✅ Oddiy Anime qo‘shildi: {context.user_data['movie_title']}")
    return ConversationHandler.END

async def delete_movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not movies_data:
        await query.edit_message_text("O'chirish uchun anime mavjud emas!")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(f"{number}: {data['title']}", callback_data=f"delete_{number}")]
                for number, data in movies_data.items()]
    await query.edit_message_text("O'chirish uchun animeni tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
    return DELETE_MOVIE

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

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text("Siz admin emassiz!")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("📢 Public kanal", callback_data="public_channel")],
        [InlineKeyboardButton("🔒 Private kanal", callback_data="private_channel")],
    ]
    await query.message.reply_text("Kanal turini tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_CHANNEL_TYPE

async def channel_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["channel_type"] = query.data
    await query.message.reply_text(
        "Public kanal username’ni @ bilan kiriting (@channelname) yoki Private kanal ID’sini kiriting (-1001234567890):"
    )
    return ADD_CHANNEL_ID

async def add_channel_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("Siz admin emassiz!")
        return ConversationHandler.END

    channel_input = update.message.text.strip()
    channel_type = context.user_data.get("channel_type")

    if channel_type == "public_channel":
        if not channel_input.startswith("@") or len(channel_input) < 2:
            await update.message.reply_text("Iltimos, to‘g‘ri public kanal username kiriting (@channelname):")
            return ADD_CHANNEL_ID
        channel = channel_input
    else:
        try:
            channel = int(channel_input)
            if channel >= 0:
                await update.message.reply_text("Private kanal ID’si manfiy bo‘lishi kerak (-1001234567890):")
                return ADD_CHANNEL_ID
        except ValueError:
            await update.message.reply_text("Iltimos, to‘g‘ri kanal ID kiriting (-1001234567890):")
            return ADD_CHANNEL_ID

    if channel in CHANNELS:
        await update.message.reply_text("Bu kanal allaqachon qo‘shilgan!")
        return ConversationHandler.END

    try:
        # Kanal mavjudligini tekshirish
        await context.bot.get_chat(channel)
        CHANNELS.append(channel)
        save_json("channels.json", CHANNELS)
        await update.message.reply_text(f"✅ Kanal qo‘shildi: {channel}")
    except Exception as e:
        logger.error(f"Kanal qo‘shishda xatolik: {e}")
        await update.message.reply_text(f"❌ Kanal qo‘shishda xatolik: {str(e)}")
        return ADD_CHANNEL_ID

    return ConversationHandler.END

async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text("Siz admin emassiz!")
        return ConversationHandler.END

    if not CHANNELS:
        await query.edit_message_text("Kanal mavjud emas!")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(str(channel), callback_data=f"select_{channel}")]
                for channel in CHANNELS]
    await query.edit_message_text("O‘chirish uchun kanalni tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
    return REMOVE_CHANNEL

async def select_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    channel_to_delete = query.data.replace("select_", "")
    keyboard = [
        [InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"confirm_delete_{channel_to_delete}")],
        [InlineKeyboardButton("❌ Yo'q", callback_data="cancel_delete")],
    ]
    await query.edit_message_text(f"Kanalni o'chirishni tasdiqlaysizmi: {channel_to_delete}?", reply_markup=InlineKeyboardMarkup(keyboard))
    return REMOVE_CHANNEL

async def confirm_delete_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    channel_to_delete = query.data.replace("confirm_delete_", "")

    try:
        channel_to_remove = channel_to_delete if channel_to_delete.startswith("@") else int(channel_to_delete)
        if channel_to_remove in CHANNELS:
            CHANNELS.remove(channel_to_remove)
            save_json("channels.json", CHANNELS)
            await query.edit_message_text(f"✅ Kanal o‘chirildi: {channel_to_delete}")
        else:
            await query.edit_message_text("Kanal topilmadi!")
    except ValueError:
        await query.edit_message_text("Kanal ID formati noto‘g‘ri!")
    return ConversationHandler.END

async def cancel_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Kanalni o'chirish bekor qilindi.")
    return ConversationHandler.END

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Broadcast xabar matnini kiriting:")
    return BROADCAST_MESSAGE

async def send_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message.text
    success_count = 0
    for user_id in users_data.keys():
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
            success_count += 1
        except Exception as e:
            logger.error(f"Xabar yuborishda xatolik {user_id}: {e}")
    await update.message.reply_text(f"✅ Xabar {success_count} foydalanuvchiga yuborildi!")
    return ConversationHandler.END

async def post_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not CHANNELS:
        await query.edit_message_text("Kanal mavjud emas! Avval kanal qo‘shing.")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(str(channel), callback_data=f"post_select_{channel}")]
                for channel in CHANNELS]
    await query.edit_message_text("Post yuborish uchun kanalni tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
    return POST_TO_CHANNEL

async def select_channel_for_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    channel_id = query.data.replace("post_select_", "")
    try:
        context.user_data["selected_channel"] = channel_id if channel_id.startswith("@") else int(channel_id)
        keyboard = [
            [InlineKeyboardButton("📝 Faqat matn", callback_data="type_text")],
            [InlineKeyboardButton("🖼 Rasm bilan", callback_data="type_photo")],
            [InlineKeyboardButton("🎥 Video bilan", callback_data="type_video")],
        ]
        await query.edit_message_text(f"Tanlangan kanal: {channel_id}\nPost turini tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
        return POST_TYPE
    except ValueError:
        await query.edit_message_text("Kanal ID formati noto‘g‘ri!")
        return ConversationHandler.END

async def select_post_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["post_type"] = query.data.replace("type_", "")
    await query.edit_message_text("Post matnini kiriting:")
    return POST_TEXT

async def receive_post_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["post_text"] = update.message.text
    post_type = context.user_data["post_type"]
    if post_type == "text":
        await update.message.reply_text("Tugma matnini kiriting (Ko‘rish):")
        return POST_BUTTON_TEXT
    await update.message.reply_text(f"{post_type.capitalize()} faylini yuboring:")
    return POST_MEDIA

async def receive_post_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    post_type = context.user_data["post_type"]
    if (post_type == "photo" and update.message.photo) or (post_type == "video" and update.message.video):
        context.user_data["post_media"] = update.message.photo[-1].file_id if post_type == "photo" else update.message.video.file_id
        await update.message.reply_text("Tugma matnini kiriting (Ko‘rish):")
        return POST_BUTTON_TEXT
    await update.message.reply_text("Noto'g'ri fayl turi! Qaytadan yuboring.")
    return POST_MEDIA

async def receive_button_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["button_text"] = update.message.text
    await update.message.reply_text("Tugma URL manzilini kiriting:")
    return POST_BUTTON_URL

async def send_post_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    button_url = update.message.text
    channel_id = context.user_data["selected_channel"]
    post_type = context.user_data["post_type"]
    post_text = context.user_data["post_text"]
    button_text = context.user_data["button_text"]

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"✨{button_text}✨", url=button_url)]])
    try:
        if post_type == "text":
            await context.bot.send_message(chat_id=channel_id, text=post_text, reply_markup=keyboard)
        elif post_type == "photo":
            await context.bot.send_photo(chat_id=channel_id, photo=context.user_data["post_media"], caption=post_text, reply_markup=keyboard)
        elif post_type == "video":
            await context.bot.send_video(chat_id=channel_id, video=context.user_data["post_media"], caption=post_text, reply_markup=keyboard)
        await update.message.reply_text(f"✅ Post {channel_id} kanaliga yuborildi!")
    except Exception as e:
        logger.error(f"Post yuborishda xatolik: {e}")
        await update.message.reply_text(f"❌ Xatolik: {str(e)}")
    return ConversationHandler.END

async def handle_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if not all([await is_subscribed(user_id, context, channel) for channel in CHANNELS]):
        await update.message.reply_text("Avval barcha kanallarga obuna bo‘ling.")
        return

    number = update.message.text
    video_info = movies_data.get(number)
    if not video_info:
        await update.message.reply_text("Bu raqamga mos anime topilmadi.")
        return

    if "part_data" in video_info:
        context.user_data["current_page"] = 0
        context.user_data["movie_number"] = number
        context.user_data["selected_part_index"] = 0
        parts = video_info["part_data"]
        parts_per_page = 5
        start_idx = context.user_data["current_page"] * parts_per_page
        end_idx = start_idx + parts_per_page
        visible_parts = parts[start_idx:end_idx]

        keyboard = []
        for i, part in enumerate(parts[start_idx + 1:end_idx], start=start_idx + 1):
            keyboard.append([InlineKeyboardButton(f"{part['part_name']}", callback_data=f"part_{number}_{i}")])

        nav_row = []
        total_pages = (len(parts) + parts_per_page - 1) // parts_per_page
        if context.user_data["current_page"] > 0:
            nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"nav_{number}_prev"))
        if context.user_data["current_page"] < total_pages - 1:
            nav_row.append(InlineKeyboardButton("➡️", callback_data=f"nav_{number}_next"))
        if nav_row:
            keyboard.append(nav_row)

        message = await update.message.reply_video(
            video=parts[0]["part_url"],
            caption=f"📄 {video_info['title']}\n🔗 {parts[0]['part_name']}\n👁 {video_info['views']}",
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )
        context.user_data["last_message_id"] = message.message_id
        context.user_data["last_chat_id"] = message.chat_id
    else:
        await update.message.reply_video(
            video=video_info["video_url"],
            caption=f"📄 {video_info['title']}\n👁 {video_info['views']}"
        )

    video_info["views"] += 1
    save_json("movies.json", movies_data)

async def handle_part_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if not all([await is_subscribed(user_id, context, channel) for channel in CHANNELS]):
        await query.edit_message_text("Avval barcha kanallarga obuna bo‘ling.")
        return

    data = query.data.split("_")
    movie_number, part_index = data[1], int(data[2])
    video_info = movies_data.get(movie_number)
    if not video_info or "part_data" not in video_info or part_index >= len(video_info["part_data"]):
        await query.message.reply_text("Qism topilmadi!")
        return

    if context.user_data.get("last_message_id") and context.user_data.get("last_chat_id"):
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=context.user_data["last_chat_id"],
                message_id=context.user_data["last_message_id"],
                reply_markup=None
            )
        except Exception as e:
            logger.error(f"Xabarni tahrirlashda xatolik: {e}")

    part = video_info["part_data"][part_index]
    context.user_data["selected_part_index"] = part_index
    parts = video_info["part_data"]
    parts_per_page = 5
    current_page = context.user_data.get("current_page", 0)
    start_idx = current_page * parts_per_page
    end_idx = start_idx + parts_per_page

    keyboard = []
    for i, p in enumerate(parts):
        if i != part_index and start_idx <= i < end_idx:
            keyboard.append([InlineKeyboardButton(f"{p['part_name']}", callback_data=f"part_{movie_number}_{i}")])

    nav_row = []
    total_pages = (len(parts) + parts_per_page - 1) // parts_per_page
    if current_page > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"nav_{movie_number}_prev"))
    if current_page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"nav_{movie_number}_next"))
    if nav_row:
        keyboard.append(nav_row)

    message = await query.message.reply_video(
        video=part["part_url"],
        caption=f"📄 {video_info['title']}\n🔗 {part['part_name']}\n👁 {video_info['views']}",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )
    context.user_data["last_message_id"] = message.message_id
    context.user_data["last_chat_id"] = message.chat_id
    video_info["views"] += 1
    save_json("movies.json", movies_data)

async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    movie_number, action = data[1], data[2]
    video_info = movies_data.get(movie_number)
    if not video_info or "part_data" not in video_info:
        await query.message.reply_text("Qism topilmadi!")
        return

    current_page = context.user_data.get("current_page", 0)
    parts_per_page = 5
    total_pages = (len(video_info["part_data"]) + parts_per_page - 1) // parts_per_page
    if action == "prev" and current_page > 0:
        context.user_data["current_page"] -= 1
    elif action == "next" and current_page < total_pages - 1:
        context.user_data["current_page"] += 1

    current_page = context.user_data["current_page"]
    start_idx = current_page * parts_per_page
    end_idx = start_idx + parts_per_page
    selected_part_index = context.user_data.get("selected_part_index", 0)

    keyboard = []
    for i, part in enumerate(video_info["part_data"]):
        if i != selected_part_index and start_idx <= i < end_idx:
            keyboard.append([InlineKeyboardButton(f"{part['part_name']}", callback_data=f"part_{movie_number}_{i}")])

    nav_row = []
    if current_page > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"nav_{movie_number}_prev"))
    if current_page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"nav_{movie_number}_next"))
    if nav_row:
        keyboard.append(nav_row)

    try:
        await context.bot.edit_message_reply_markup(
            chat_id=context.user_data["last_chat_id"],
            message_id=context.user_data["last_message_id"],
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )
    except Exception as e:
        logger.error(f"Xabarni tahrirlashda xatolik: {e}")

async def webhook_handler(request):
    try:
        update = await request.json()
        update = Update.de_json(update, application.bot)
        await application.process_update(update)
        return web.Response(text="OK")
    except Exception as e:
        logger.error(f"Webhook xatoligi: {e}")
        return web.Response(status=500)

async def main() -> None:
    global application
    application = Application.builder().token(BOT_TOKEN).build()

    # Conversation Handlers
    conv_handler_parts = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_panel, pattern="^add_movie_parts$")],
        states={
            MOVIE_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, movie_title)],
            MOVIE_PARTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, movie_parts)],
            MOVIE_PART_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, movie_part_url)],
            MOVIE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, movie_number)],
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
        per_message=True,
    )

    conv_handler_simple = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_panel, pattern="^add_simple_movie$")],
        states={
            SIMPLE_MOVIE_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, simple_movie_title)],
            SIMPLE_MOVIE_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, simple_movie_url)],
            SIMPLE_MOVIE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, simple_movie_number)],
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
        per_message=True,
    )

    conv_handler_delete = ConversationHandler(
        entry_points=[CallbackQueryHandler(delete_movie, pattern="^delete_movie$")],
        states={
            DELETE_MOVIE: [CallbackQueryHandler(confirm_delete_movie, pattern="^delete_")],
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
        per_message=True,
    )

    conv_handler_remove_channel = ConversationHandler(
        entry_points=[CallbackQueryHandler(remove_channel, pattern="^remove_channel$")],
        states={
            REMOVE_CHANNEL: [
                CallbackQueryHandler(select_channel, pattern="^select_"),
                CallbackQueryHandler(confirm_delete_channel, pattern="^confirm_delete_"),
                CallbackQueryHandler(cancel_delete, pattern="^cancel_delete$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
        per_message=True,
    )

    conv_handler_broadcast = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast, pattern="^broadcast$")],
        states={
            BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_broadcast_message)],
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
        per_message=True,
    )

    conv_handler_add_channel = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_channel, pattern="^add_channel$")],
        states={
            ADD_CHANNEL_TYPE: [CallbackQueryHandler(channel_type, pattern="^(public_channel|private_channel)$")],
            ADD_CHANNEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_channel_id)],
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
        per_message=True,
    )

    conv_handler_add_new_part = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_new_part, pattern="^add_new_part$")],
        states={
            ADD_NEW_PART_SELECT: [CallbackQueryHandler(select_movie_for_new_part, pattern="^add_part_")],
            ADD_NEW_PART_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_new_part_name)],
            ADD_NEW_PART_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_new_part_url)],
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
        per_message=True,
    )

    conv_handler_post_to_channel = ConversationHandler(
        entry_points=[CallbackQueryHandler(post_to_channel, pattern="^post_to_channel$")],
        states={
            POST_TO_CHANNEL: [CallbackQueryHandler(select_channel_for_post, pattern="^post_select_")],
            POST_TYPE: [CallbackQueryHandler(select_post_type, pattern="^type_")],
            POST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_post_text)],
            POST_MEDIA: [MessageHandler(filters.PHOTO | filters.VIDEO, receive_post_media)],
            POST_BUTTON_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_button_text)],
            POST_BUTTON_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_post_to_channel)],
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
        per_message=True,
    )

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(check_subscription, pattern="^check_sub$"))
    application.add_handler(CallbackQueryHandler(send_user_count, pattern="^user_count$"))
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
    application.add_handler(CallbackQueryHandler(restart_bot, pattern="^restart_bot$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\d+$"), handle_number))

    # Webhook sozlash
    try:
        await application.bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook o'rnatildi: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"Webhook o'rnatishda xatolik: {e}")
        raise

    app = web.Application()
    app.router.add_post('/', webhook_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

    await application.initialize()
    await application.start()
    logger.info("Bot ishga tushdi")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    os.environ['TZ'] = 'UTC'
    asyncio.run(main())
