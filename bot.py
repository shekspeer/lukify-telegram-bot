import asyncio
import sqlite3
import aiohttp
import logging
from io import BytesIO
from datetime import datetime
from html import escape
from telebot.async_telebot import AsyncTeleBot
from telebot.types import BusinessMessagesDeleted, InlineKeyboardMarkup, InlineKeyboardButton

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = "8758417597:AAEpQYYX7Mu2NTM-9ABAT5gDv3_oxF7H7dY"
OWNER_ID = 6451702799

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = AsyncTeleBot(TOKEN, parse_mode="HTML")

# ========== БАЗА ДАННЫХ ==========
def init_db():
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                chat_id INTEGER,
                user_name TEXT,
                content_type TEXT,
                content TEXT,
                file_id TEXT,
                caption TEXT,
                edited_at TEXT,
                deleted_at TEXT,
                saved_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                user_name TEXT,
                first_seen TEXT,
                last_seen TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_photo', '')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_text', '')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('channel_link', '')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('help_text', '')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('required_channel', '')")
        conn.commit()

init_db()

# ========== ФУНКЦИИ БАЗЫ ДАННЫХ ==========
def save_msg(chat_id, msg_id, user_name, content_type, content, file_id=None, caption=None):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO messages 
            (message_id, chat_id, user_name, content_type, content, file_id, caption, saved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (msg_id, chat_id, user_name, content_type, content, file_id, caption, datetime.now().isoformat()))
        conn.commit()

def get_msg(chat_id, msg_id):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_name, content_type, content, file_id, caption
            FROM messages WHERE chat_id=? AND message_id=?
        """, (chat_id, msg_id))
        return cursor.fetchone()

def update_edit(chat_id, msg_id, new_content):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE messages SET content=?, edited_at=? WHERE chat_id=? AND message_id=?
        """, (new_content, datetime.now().isoformat(), chat_id, msg_id))
        conn.commit()

def mark_deleted(chat_id, msg_id):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE messages SET deleted_at=? WHERE chat_id=? AND message_id=?
        """, (datetime.now().isoformat(), chat_id, msg_id))
        conn.commit()

def update_user(user_id, user_name):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO users (user_id, user_name, last_seen)
            VALUES (?, ?, ?)
        """, (user_id, user_name, datetime.now().isoformat()))
        conn.commit()

def get_all_users():
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        return [row[0] for row in cursor.fetchall()]

def get_statistics():
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM messages WHERE content_type='photo'")
        photos = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM messages WHERE edited_at IS NOT NULL")
        edited = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM messages WHERE deleted_at IS NOT NULL")
        deleted = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users")
        users = cursor.fetchone()[0]
        return total, photos, edited, deleted, users

def get_setting(key):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = cursor.fetchone()
        return row[0] if row else ""

def set_setting(key, value):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
async def download_photo(file_id):
    async with aiohttp.ClientSession() as session:
        url = f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={file_id}"
        async with session.get(url) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise Exception(f"Ошибка getFile: {data}")
            file_path = data["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        async with session.get(file_url) as file_resp:
            if file_resp.status != 200:
                raise Exception(f"Ошибка скачивания: {file_resp.status}")
            return await file_resp.read()

async def is_subscribed(user_id, channel):
    if not channel:
        return True
    channel = channel.lstrip('@')
    try:
        member = await bot.get_chat_member(f"@{channel}", user_id)
        subscribed = member.status in ["member", "creator", "administrator"]
        logger.info(f"Проверка подписки {user_id} на @{channel}: статус {member.status} -> {subscribed}")
        return subscribed
    except Exception as e:
        logger.error(f"Ошибка проверки подписки для {user_id} на @{channel}: {e}")
        return False

# Состояния пользователей
user_states = {}

def set_state(user_id, state):
    user_states[user_id] = state

def get_state(user_id):
    return user_states.get(user_id)

# ========== ОБРАБОТЧИКИ БИЗНЕС-СООБЩЕНИЙ ==========
@bot.business_message_handler(content_types=[
    "text", "photo", "voice", "video",
    "video_note", "animation", "sticker"
])
async def handle_message(msg):
    user_name = msg.from_user.first_name if msg.from_user else "Пользователь"
    user_id = msg.from_user.id
    update_user(user_id, user_name)

    content_type = msg.content_type
    text = msg.text or msg.caption or ""
    file_id = None
    caption = None

    if msg.photo:
        file_id = msg.photo[-1].file_id
        caption = msg.caption
    elif msg.video:
        file_id = msg.video.file_id
        caption = msg.caption
    elif msg.animation:
        file_id = msg.animation.file_id
        caption = msg.caption
    elif msg.video_note:
        file_id = msg.video_note.file_id
    elif msg.voice:
        file_id = msg.voice.file_id
    elif msg.sticker:
        file_id = msg.sticker.file_id

    save_msg(msg.chat.id, msg.message_id, user_name, content_type, text, file_id, caption)

    # Если это ответ владельца на фото – сохраняем и присылаем
    if msg.reply_to_message and msg.from_user.id == OWNER_ID:
        target = msg.reply_to_message
        if target.photo:
            try:
                photo_bytes = await download_photo(target.photo[-1].file_id)
                photo_file = BytesIO(photo_bytes)
                photo_file.name = "recovered.jpg"
                await bot.send_photo(
                    OWNER_ID,
                    photo_file,
                    caption=f"📸 Фото, на которое вы ответили (от {target.from_user.first_name})"
                )
            except Exception as e:
                await bot.send_message(OWNER_ID, f"❌ Ошибка сохранения фото: {e}")

@bot.edited_business_message_handler(content_types=["text"])
async def handle_edit(msg):
    old = get_msg(msg.chat.id, msg.message_id)
    if old:
        user_name, content_type, old_content, file_id, caption = old
        if old_content != msg.text:
            await bot.send_message(
                OWNER_ID,
                f"<b>✏️ {user_name} изменил(а) сообщение:</b>\n\n"
                f"<b>Было:</b>\n<blockquote>{escape(old_content)}</blockquote>\n\n"
                f"<b>Стало:</b>\n<blockquote>{escape(msg.text)}</blockquote>"
            )
    update_edit(msg.chat.id, msg.message_id, msg.text or "")

@bot.deleted_business_messages_handler()
async def handle_delete(event: BusinessMessagesDeleted):
    chat = event.chat
    for msg_id in event.message_ids:
        old = get_msg(chat.id, msg_id)
        if not old:
            continue
        user_name, content_type, content, file_id, caption = old
        mark_deleted(chat.id, msg_id)

        if content_type == "text":
            await bot.send_message(
                OWNER_ID,
                f"<b>🗑️ {user_name} удалил(а) сообщение:</b>\n\n<blockquote>{escape(content)}</blockquote>"
            )
        elif file_id:
            cap_text = f"<b>🗑️ {user_name} удалил(а) {content_type}</b>"
            if caption:
                cap_text += f"\n\n<blockquote>{escape(caption)}</blockquote>"
            try:
                if content_type == "photo":
                    await bot.send_photo(OWNER_ID, file_id, caption=cap_text)
                elif content_type == "video":
                    await bot.send_video(OWNER_ID, file_id, caption=cap_text)
                elif content_type == "animation":
                    await bot.send_animation(OWNER_ID, file_id, caption=cap_text)
                elif content_type == "video_note":
                    await bot.send_video_note(OWNER_ID, file_id)
                    await bot.send_message(OWNER_ID, f"<b>🗑️ {user_name} удалил(а) видеосообщение</b>")
                elif content_type == "voice":
                    await bot.send_voice(OWNER_ID, file_id, caption=cap_text)
                elif content_type == "sticker":
                    await bot.send_sticker(OWNER_ID, file_id)
                    await bot.send_message(OWNER_ID, f"<b>🗑️ {user_name} удалил(а) стикер</b>")
            except Exception as e:
                await bot.send_message(OWNER_ID, f"❌ Не удалось отправить файл: {e}")

# ========== АДМИН-ПАНЕЛЬ ==========
def admin_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📊 Статистика", callback_data="stats"),
        InlineKeyboardButton("📢 Рассылка", callback_data="broadcast")
    )
    keyboard.add(
        InlineKeyboardButton("🖼 Приветственное фото", callback_data="set_welcome_photo"),
        InlineKeyboardButton("📝 Текст приветствия", callback_data="set_welcome_text")
    )
    keyboard.add(
        InlineKeyboardButton("🔗 Ссылка на канал", callback_data="set_channel_link"),
        InlineKeyboardButton("🔒 Обязательный канал", callback_data="set_required_channel")
    )
    keyboard.add(
        InlineKeyboardButton("📥 Экспорт базы", callback_data="export"),
        InlineKeyboardButton("🗑 Очистить статистику", callback_data="clear_stats")
    )
    return keyboard

def back_button():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin"))
    return keyboard

# ========== КОМАНДЫ ==========
@bot.message_handler(commands=['admin'])
async def admin_panel(message):
    if message.from_user.id != OWNER_ID:
        await bot.reply_to(message, "⛔ Нет доступа")
        return
    await bot.send_message(OWNER_ID, "🔐 <b>Админ-панель</b>", reply_markup=admin_keyboard())

@bot.message_handler(commands=['start'])
async def start_cmd(message):
    user_id = message.from_user.id
    required_channel = get_setting("required_channel")
    if user_id != OWNER_ID and required_channel:
        if not await is_subscribed(user_id, required_channel):
            keyboard = InlineKeyboardMarkup()
            channel_username = required_channel.lstrip('@')
            channel_link = f"https://t.me/{channel_username}"
            keyboard.add(InlineKeyboardButton("🔔 Подписаться на канал", url=channel_link))
            keyboard.add(InlineKeyboardButton("✅ Я подписался", callback_data="check_subscription"))
            await bot.send_message(
                message.chat.id,
                f"❌ Для использования бота необходимо подписаться на наш канал:\n\n👉 @{channel_username}\n\nПосле подписки нажмите кнопку ниже.",
                reply_markup=keyboard
            )
            return

    welcome_photo = get_setting("welcome_photo")
    welcome_text = get_setting("welcome_text")
    channel_link = get_setting("channel_link")

    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("📘 Как подключить бота?", callback_data="help"))
    if channel_link:
        keyboard.add(InlineKeyboardButton("📢 Наш канал", url=channel_link))

    if welcome_photo:
        try:
            await bot.send_photo(
                message.chat.id,
                welcome_photo,
                caption=welcome_text or "Добро пожаловать!",
                reply_markup=keyboard
            )
        except:
            await bot.send_message(
                message.chat.id,
                welcome_text or "Добро пожаловать! Я бот для сохранения бизнес-сообщений.",
                reply_markup=keyboard
            )
    else:
        await bot.send_message(
            message.chat.id,
            welcome_text or "Добро пожаловать! Я бот для сохранения бизнес-сообщений.",
            reply_markup=keyboard
        )

@bot.message_handler(commands=['confirm_clear'])
async def confirm_clear_command(message):
    if message.from_user.id != OWNER_ID:
        return
    with sqlite3.connect("bot_data.db") as conn:
        conn.execute("DELETE FROM messages")
        conn.commit()
    await bot.send_message(OWNER_ID, "✅ Все сообщения удалены.", reply_markup=admin_keyboard())

# ========== ОБРАБОТЧИКИ КОЛБЭКОВ (два отдельных) ==========
# 1. Публичные колбэки (не требующие OWNER_ID)
@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
async def check_subscription_callback(call):
    logger.info(f"Колбэк check_subscription от {call.from_user.id}")
    user_id = call.from_user.id
    required_channel = get_setting("required_channel")
    if not required_channel:
        await bot.answer_callback_query(call.id, "Канал не задан", show_alert=True)
        return

    await asyncio.sleep(2.5)

    subscribed = False
    for attempt in range(3):
        subscribed = await is_subscribed(user_id, required_channel)
        if subscribed:
            break
        await asyncio.sleep(1.5)

    if subscribed:
        try:
            await bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            logger.error(f"Не удалось удалить сообщение: {e}")

        welcome_photo = get_setting("welcome_photo")
        welcome_text = get_setting("welcome_text")
        channel_link = get_setting("channel_link")

        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("📘 Как подключить бота?", callback_data="help"))
        if channel_link:
            keyboard.add(InlineKeyboardButton("📢 Наш канал", url=channel_link))

        if welcome_photo:
            try:
                await bot.send_photo(
                    call.message.chat.id,
                    welcome_photo,
                    caption=welcome_text or "Добро пожаловать!",
                    reply_markup=keyboard
                )
            except:
                await bot.send_message(
                    call.message.chat.id,
                    welcome_text or "Добро пожаловать! Я бот для сохранения бизнес-сообщений.",
                    reply_markup=keyboard
                )
        else:
            await bot.send_message(
                call.message.chat.id,
                welcome_text or "Добро пожаловать! Я бот для сохранения бизнес-сообщений.",
                reply_markup=keyboard
            )
        await bot.answer_callback_query(call.id, "✅ Доступ открыт!", show_alert=True)
    else:
        await bot.send_message(OWNER_ID, f"⚠️ Пользователь {user_id} нажал кнопку, но подписка не обнаружена. Канал: {required_channel}")
        await bot.answer_callback_query(call.id, "❌ Подписка не подтверждена. Попробуйте через минуту.", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data == "help")
async def help_callback(call):
    help_text = get_setting("help_text")
    if not help_text:
        help_text = (
            "🔧 <b>Как подключить бота в Telegram Business:</b>\n\n"
            "1. Откройте настройки Telegram Business.\n"
            "2. Выберите раздел «Боты».\n"
            "3. Добавьте этого бота, указав его @username.\n"
            "4. Настройте права: бот должен видеть все сообщения (Manage messages).\n"
            "5. Теперь бот будет сохранять все бизнес-сообщения, а при удалении/изменении присылать копии."
        )
    await bot.send_message(call.message.chat.id, help_text, parse_mode="HTML")
    await bot.answer_callback_query(call.id)

# 2. Админские колбэки (только для OWNER_ID)
@bot.callback_query_handler(func=lambda call: call.from_user.id == OWNER_ID and call.data.startswith(("stats", "broadcast", "set_", "export", "clear_stats", "back_to_admin")))
async def admin_callback(call):
    logger.info(f"Админский колбэк {call.data} от {call.from_user.id}")
    await bot.answer_callback_query(call.id)

    if call.data == "stats":
        total, photos, edited, deleted, users = get_statistics()
        text = (f"📊 <b>Статистика</b>\n\n"
                f"📝 Всего сообщений: {total}\n"
                f"📸 Фото: {photos}\n"
                f"✏️ Изменённых: {edited}\n"
                f"🗑 Удалённых: {deleted}\n"
                f"👥 Пользователей: {users}")
        await bot.edit_message_text(text, OWNER_ID, call.message.message_id, parse_mode="HTML", reply_markup=back_button())
    elif call.data == "broadcast":
        await bot.edit_message_text(
            "📢 <b>Рассылка</b>\n\nОтправьте сообщение (текст, фото, видео, документ). Оно будет разослано всем пользователям.",
            OWNER_ID, call.message.message_id, parse_mode="HTML", reply_markup=back_button()
        )
        set_state(OWNER_ID, "waiting_broadcast")
    elif call.data == "set_welcome_photo":
        await bot.edit_message_text(
            "🖼 Отправьте фото, которое будет использоваться как приветственное.",
            OWNER_ID, call.message.message_id, reply_markup=back_button()
        )
        set_state(OWNER_ID, "waiting_welcome_photo")
    elif call.data == "set_welcome_text":
        await bot.edit_message_text(
            "📝 Отправьте текст приветствия (можно с HTML).",
            OWNER_ID, call.message.message_id, reply_markup=back_button()
        )
        set_state(OWNER_ID, "waiting_welcome_text")
    elif call.data == "set_channel_link":
        await bot.edit_message_text(
            "🔗 Отправьте ссылку на канал (например, https://t.me/username).",
            OWNER_ID, call.message.message_id, reply_markup=back_button()
        )
        set_state(OWNER_ID, "waiting_channel_link")
    elif call.data == "set_required_channel":
        await bot.edit_message_text(
            "🔒 Отправьте username канала, на который нужно подписаться (например, @my_channel).\n"
            "Бот должен быть администратором канала, чтобы проверять подписку.\n"
            "Оставьте пустое сообщение, чтобы отключить проверку.",
            OWNER_ID, call.message.message_id, reply_markup=back_button()
        )
        set_state(OWNER_ID, "waiting_required_channel")
    elif call.data == "export":
        try:
            with open("bot_data.db", "rb") as f:
                await bot.send_document(OWNER_ID, f, caption="📦 Экспорт базы данных")
            await bot.edit_message_text("✅ База отправлена", OWNER_ID, call.message.message_id, reply_markup=back_button())
        except Exception as e:
            await bot.edit_message_text(f"❌ Ошибка: {e}", OWNER_ID, call.message.message_id, reply_markup=back_button())
    elif call.data == "clear_stats":
        await bot.edit_message_text(
            "⚠️ <b>Очистка статистики</b>\n\nВы уверены? Это удалит все сохранённые сообщения из базы.\n"
            "Введите <code>/confirm_clear</code> для подтверждения.",
            OWNER_ID, call.message.message_id, parse_mode="HTML", reply_markup=back_button()
        )
        set_state(OWNER_ID, "waiting_clear_confirm")
    elif call.data == "back_to_admin":
        await bot.edit_message_text("🔐 <b>Админ-панель</b>", OWNER_ID, call.message.message_id, parse_mode="HTML", reply_markup=admin_keyboard())
        set_state(OWNER_ID, None)

# ========== ОБРАБОТЧИК ВСЕХ СООБЩЕНИЙ ОТ АДМИНА ==========
@bot.message_handler(content_types=['text', 'photo', 'video', 'document'])
async def handle_admin_input(message):
    if message.from_user.id != OWNER_ID:
        return
    if message.text and message.text.startswith('/'):
        return
    state = get_state(OWNER_ID)
    if state == "waiting_broadcast":
        await broadcast_message(message)
        set_state(OWNER_ID, None)
        await bot.send_message(OWNER_ID, "✅ Рассылка завершена", reply_markup=admin_keyboard())
    elif state == "waiting_welcome_photo" and message.photo:
        file_id = message.photo[-1].file_id
        set_setting("welcome_photo", file_id)
        await bot.send_message(OWNER_ID, "✅ Приветственное фото сохранено.", reply_markup=admin_keyboard())
        set_state(OWNER_ID, None)
    elif state == "waiting_welcome_text" and message.text:
        set_setting("welcome_text", message.text)
        await bot.send_message(OWNER_ID, "✅ Текст приветствия сохранён.", reply_markup=admin_keyboard())
        set_state(OWNER_ID, None)
    elif state == "waiting_channel_link" and message.text:
        set_setting("channel_link", message.text)
        await bot.send_message(OWNER_ID, "✅ Ссылка на канал сохранена.", reply_markup=admin_keyboard())
        set_state(OWNER_ID, None)
    elif state == "waiting_required_channel":
        channel = message.text.strip()
        if not channel:
            set_setting("required_channel", "")
            await bot.send_message(OWNER_ID, "✅ Проверка подписки отключена.", reply_markup=admin_keyboard())
        else:
            set_setting("required_channel", channel)
            await bot.send_message(OWNER_ID, f"✅ Обязательный канал установлен: {channel}.", reply_markup=admin_keyboard())
        set_state(OWNER_ID, None)
    elif state == "waiting_clear_confirm":
        if message.text == "/confirm_clear":
            with sqlite3.connect("bot_data.db") as conn:
                conn.execute("DELETE FROM messages")
                conn.commit()
            await bot.send_message(OWNER_ID, "✅ Все сообщения удалены.", reply_markup=admin_keyboard())
        else:
            await bot.send_message(OWNER_ID, "❌ Отменено. Введите /confirm_clear для подтверждения.", reply_markup=admin_keyboard())
        set_state(OWNER_ID, None)

async def broadcast_message(msg):
    users = get_all_users()
    if not users:
        await bot.send_message(OWNER_ID, "Нет пользователей для рассылки.")
        return
    success = 0
    for uid in users:
        try:
            if msg.photo:
                await bot.send_photo(uid, msg.photo[-1].file_id, caption=msg.caption)
            elif msg.video:
                await bot.send_video(uid, msg.video.file_id, caption=msg.caption)
            elif msg.document:
                await bot.send_document(uid, msg.document.file_id, caption=msg.caption)
            elif msg.text:
                await bot.send_message(uid, msg.text, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            print(f"Ошибка рассылки пользователю {uid}: {e}")
    await bot.send_message(OWNER_ID, f"✅ Отправлено: {success}/{len(users)}")

# ========== ЗАПУСК ==========
async def main():
    print("Бот запущен с исправленной админ-панелью и проверкой подписки")
    await bot.infinity_polling(
        allowed_updates=[
            "business_message",
            "edited_business_message",
            "deleted_business_messages",
            "message",
            "callback_query"
        ],
        skip_pending=True
    )

if __name__ == "__main__":
    asyncio.run(main())
