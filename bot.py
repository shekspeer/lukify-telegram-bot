import asyncio
import sqlite3
import aiohttp
import logging
import os
import time
import random
from io import BytesIO
from datetime import datetime, timedelta
from html import escape
from telebot.async_telebot import AsyncTeleBot
from telebot.types import BusinessMessagesDeleted, InlineKeyboardMarkup, InlineKeyboardButton
from commands import process_command

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = "8758417597:AAEpQYYX7Mu2NTM-9ABAT5gDv3_oxF7H7dY"
ADMIN_IDS = [6451702799]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = AsyncTeleBot(TOKEN, parse_mode="HTML")

MEDIA_DIR = "saved_media"
os.makedirs(MEDIA_DIR, exist_ok=True)

# ========== БАЗА ДАННЫХ ==========
def init_db():
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                chat_id INTEGER,
                user_id INTEGER,
                user_name TEXT,
                content_type TEXT,
                content TEXT,
                file_id TEXT,
                caption TEXT,
                local_path TEXT,
                edited_at TEXT,
                deleted_at TEXT,
                saved_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                user_name TEXT,
                username TEXT,
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
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                first_seen TEXT,
                last_seen TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscription_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                event_type TEXT,
                timestamp TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                content_type TEXT DEFAULT 'text',
                text TEXT,
                file_id TEXT,
                caption TEXT,
                end_time TEXT,
                winners_count INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 1,
                created_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS giveaway_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                giveaway_id INTEGER,
                user_id INTEGER,
                join_time TEXT,
                FOREIGN KEY(giveaway_id) REFERENCES giveaways(id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                url TEXT
            )
        """)
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_photo', '')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_text', '')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('channel_link', '')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('help_text', '')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('required_channel', '')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('keep_days', '7')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('post_link', '')")
        conn.commit()

init_db()

# ========== ФУНКЦИИ БАЗЫ ДАННЫХ ==========
def save_msg(chat_id, msg_id, user_id, user_name, content_type, content, file_id=None, caption=None, local_path=None):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO messages 
            (message_id, chat_id, user_id, user_name, content_type, content, file_id, caption, local_path, saved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (msg_id, chat_id, user_id, user_name, content_type, content, file_id, caption, local_path, datetime.now().isoformat()))
        conn.commit()

def get_msg(chat_id, msg_id):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_id, user_name, content_type, content, file_id, caption, local_path
            FROM messages WHERE chat_id=? AND message_id=?
        """, (chat_id, msg_id))
        return cursor.fetchone()

def get_msg_local_path(chat_id, msg_id):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT local_path FROM messages WHERE chat_id=? AND message_id=?", (chat_id, msg_id))
        row = cursor.fetchone()
        return row[0] if row else None

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

def update_user(user_id, user_name, username):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT OR REPLACE INTO users (user_id, user_name, username, first_seen, last_seen)
            VALUES (?, ?, ?, COALESCE((SELECT first_seen FROM users WHERE user_id=?), ?), ?)
        """, (user_id, user_name, username, user_id, now, now))
        conn.commit()

def add_chat(chat_id):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT OR IGNORE INTO chats (chat_id, first_seen, last_seen)
            VALUES (?, ?, ?)
        """, (chat_id, now, now))
        cursor.execute("""
            UPDATE chats SET last_seen = ? WHERE chat_id = ?
        """, (now, chat_id))
        conn.commit()

def add_subscription_event(user_id, event_type):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subscription_events (user_id, event_type, timestamp)
            VALUES (?, ?, ?)
        """, (user_id, event_type, datetime.now().isoformat()))
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
        cursor.execute("SELECT COUNT(*) FROM chats")
        chats = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM subscription_events WHERE event_type='subscribe'")
        subscriptions = cursor.fetchone()[0]
        return total, photos, edited, deleted, users, chats, subscriptions

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

# ========== ФУНКЦИИ ДЛЯ РЕКЛАМЫ ==========
def add_ad(text, url=None):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO ads (text, url) VALUES (?, ?)", (text, url))
        conn.commit()
        return cursor.lastrowid

def get_all_ads():
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, text, url FROM ads ORDER BY id")
        return cursor.fetchall()

def delete_ad(ad_id):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ads WHERE id=?", (ad_id,))
        conn.commit()

def get_ad_footer():
    ads = get_all_ads()
    if not ads:
        return ""
    parts = []
    for ad_id, text, url in ads:
        if url:
            parts.append(f'<a href="{url}">{text}</a>')
        else:
            parts.append(text)
    return "\n\n" + "\n".join(parts)

# ========== ФУНКЦИИ ДЛЯ РОЗЫГРЫШЕЙ ==========
def create_giveaway(chat_id, message_id, content_type, text, file_id=None, caption=None, end_time=None, winners_count=1):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO giveaways (chat_id, message_id, content_type, text, file_id, caption, end_time, winners_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (chat_id, message_id, content_type, text, file_id, caption, end_time, winners_count, datetime.now().isoformat()))
        conn.commit()
        return cursor.lastrowid

def add_participant(giveaway_id, user_id):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM giveaway_participants WHERE giveaway_id=? AND user_id=?", (giveaway_id, user_id))
        if cursor.fetchone():
            return False
        cursor.execute("INSERT INTO giveaway_participants (giveaway_id, user_id, join_time) VALUES (?, ?, ?)",
                       (giveaway_id, user_id, datetime.now().isoformat()))
        conn.commit()
        return True

def get_participants(giveaway_id):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM giveaway_participants WHERE giveaway_id=?", (giveaway_id,))
        return [row[0] for row in cursor.fetchall()]

def get_participants_count(giveaway_id):
    return len(get_participants(giveaway_id))

def end_giveaway(giveaway_id, winners_count=None):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id, message_id, winners_count, text FROM giveaways WHERE id=?", (giveaway_id,))
        row = cursor.fetchone()
        if not row:
            return None
        chat_id, msg_id, wc, text = row
        if winners_count is None:
            winners_count = wc
        participants = get_participants(giveaway_id)
        if not participants:
            result_text = "В розыгрыше никто не участвовал."
            winners = []
        else:
            winners = random.sample(participants, min(winners_count, len(participants)))
            winner_mentions = []
            for uid in winners:
                with sqlite3.connect("bot_data.db") as conn2:
                    cursor2 = conn2.cursor()
                    cursor2.execute("SELECT user_name FROM users WHERE user_id=?", (uid,))
                    row2 = cursor2.fetchone()
                    name = row2[0] if row2 else str(uid)
                winner_mentions.append(f'<a href="tg://user?id={uid}">{escape(name)}</a>')
            result_text = f"🎉 Победители: {', '.join(winner_mentions)}"
        cursor.execute("UPDATE giveaways SET is_active=0 WHERE id=?", (giveaway_id,))
        conn.commit()
        bot.loop.create_task(send_giveaway_result(chat_id, msg_id, result_text, winners))
        return winners

async def send_giveaway_result(chat_id, message_id, result_text, winners):
    try:
        await bot.edit_message_text(
            f"{result_text}\n\nРозыгрыш завершён.",
            chat_id=chat_id,
            message_id=message_id,
            parse_mode="HTML"
        )
        for uid in winners:
            with sqlite3.connect("bot_data.db") as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
                if cursor.fetchone():
                    try:
                        await bot.send_message(
                            uid,
                            f"🎉 Поздравляем! Вы выиграли в розыгрыше!\n\n{result_text}",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"Не удалось уведомить победителя {uid}: {e}")
    except Exception as e:
        logger.error(f"Ошибка при отправке результата розыгрыша: {e}")

# ========== АВТОМАТИЧЕСКАЯ ОЧИСТКА И ПРОВЕРКА РОЗЫГРЫШЕЙ ==========
async def cleanup_old_files():
    while True:
        try:
            keep_days = int(get_setting("keep_days"))
            if keep_days <= 0:
                await asyncio.sleep(86400)
                continue
            cutoff = datetime.now() - timedelta(days=keep_days)
            cutoff_str = cutoff.isoformat()
            with sqlite3.connect("bot_data.db") as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT local_path FROM messages WHERE saved_at < ? AND local_path IS NOT NULL", (cutoff_str,))
                rows = cursor.fetchall()
                for row in rows:
                    path = row[0]
                    if path and os.path.exists(path):
                        os.remove(path)
                cursor.execute("DELETE FROM messages WHERE saved_at < ?", (cutoff_str,))
                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка при очистке: {e}")
        await asyncio.sleep(86400)

async def check_giveaways():
    while True:
        try:
            with sqlite3.connect("bot_data.db") as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                cursor.execute("SELECT id, end_time FROM giveaways WHERE is_active=1 AND end_time <= ?", (now,))
                rows = cursor.fetchall()
                for gw_id, end_time_str in rows:
                    end_giveaway(gw_id)
        except Exception as e:
            logger.error(f"Ошибка в check_giveaways: {e}")
        await asyncio.sleep(60)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
async def download_media(file_id, ext):
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
            content = await file_resp.read()
            local_path = os.path.join(MEDIA_DIR, f"{file_id}.{ext}")
            with open(local_path, "wb") as f:
                f.write(content)
            return local_path

async def is_subscribed(user_id, channel):
    if not channel:
        return True
    channel = channel.lstrip('@')
    try:
        member = await bot.get_chat_member(f"@{channel}", user_id)
        return member.status in ["member", "creator", "administrator"]
    except Exception:
        return False

last_reminder = {}
async def send_reminder_if_unsubscribed(user_id, required_channel):
    if not required_channel:
        return True
    if user_id in ADMIN_IDS:
        return True
    if await is_subscribed(user_id, required_channel):
        return True
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if not cursor.fetchone():
            return False
    now = time.time()
    last = last_reminder.get(user_id, 0)
    if now - last > 3600:
        last_reminder[user_id] = now
        channel_username = required_channel.lstrip('@')
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔔 Подписаться", url=f"https://t.me/{channel_username}"))
        keyboard.add(InlineKeyboardButton("✅ Я подписался", callback_data="check_subscription"))
        try:
            await bot.send_message(
                user_id,
                f"⚠️ <b>Вы отписались от канала @{channel_username}</b>\n\n"
                f"Чтобы получать уведомления о событиях, подпишитесь снова.",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception:
            pass
    return False

async def safe_send_message(user_id, text, parse_mode="HTML", **kwargs):
    logger.info(f"Отправляем HTML: {text[:200]}")
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if not cursor.fetchone():
            logger.warning(f"Попытка отправить сообщение неактивированному пользователю {user_id}")
            return
    required_channel = get_setting("required_channel")
    if not await send_reminder_if_unsubscribed(user_id, required_channel):
        return
    try:
        return await bot.send_message(user_id, text, parse_mode=parse_mode, **kwargs)
    except Exception as e:
        if "can't initiate conversation" in str(e):
            logger.warning(f"Не удалось отправить сообщение в личку {user_id}: {e}")
        else:
            raise

user_states = {}
user_giveaway_data = {}
def set_state(user_id, state):
    user_states[user_id] = state
def get_state(user_id):
    return user_states.get(user_id)

processed_replies = set()

def highlight_diff(old_text, new_text):
    import re
    tokens_old = re.findall(r'\b\w+\b|[^\w\s]|\s+', old_text)
    tokens_new = re.findall(r'\b\w+\b|[^\w\s]|\s+', new_text)
    max_len = max(len(tokens_old), len(tokens_new))
    tokens_old += [''] * (max_len - len(tokens_old))
    tokens_new += [''] * (max_len - len(tokens_new))
    result = []
    for i in range(max_len):
        if tokens_old[i] == tokens_new[i]:
            result.append(tokens_new[i])
        else:
            if tokens_old[i] and not tokens_new[i]:
                result.append(f'<del>{tokens_old[i]}</del>')
            elif not tokens_old[i] and tokens_new[i]:
                result.append(f'<ins>{tokens_new[i]}</ins>')
            else:
                result.append(f'<del>{tokens_old[i]}</del> <ins>{tokens_new[i]}</ins>')
    return ''.join(result)

# ========== ОБРАБОТЧИКИ БИЗНЕС-СООБЩЕНИЙ ==========
@bot.business_message_handler(content_types=["text", "photo", "voice", "video", "video_note", "animation", "sticker"])
async def handle_message(msg):
    # Обработка команд
    if msg.text and msg.text.startswith('.'):
        await process_command(bot, msg)
        return  # не сохраняем команду в базу

    if not msg.business_connection_id:
        return
    business_connection = await bot.get_business_connection(msg.business_connection_id)
    owner_id = business_connection.user_chat_id
    add_chat(msg.chat.id)

    logger.info(f"Бизнес-сообщение: user={msg.from_user.id}, chat={msg.chat.id}, owner={owner_id}")

    user_id = msg.from_user.id
    user_name = msg.from_user.first_name or str(user_id)
    username = msg.from_user.username
    update_user(user_id, user_name, username)

    content_type = msg.content_type
    text = msg.text or msg.caption or ""
    file_id = None
    caption = msg.caption
    local_path = None

    if msg.photo:
        file_id = msg.photo[-1].file_id
        content_type = "photo"
        try:
            local_path = await download_media(file_id, "jpg")
            logger.info(f"Фото сохранено: {local_path}")
        except Exception as e:
            logger.error(f"Ошибка сохранения фото: {e}")
    elif msg.video:
        file_id = msg.video.file_id
        content_type = "video"
    elif msg.video_note:
        file_id = msg.video_note.file_id
        content_type = "video_note"
        try:
            local_path = await download_media(file_id, "mp4")
        except Exception as e:
            logger.error(f"Ошибка сохранения видеосообщения: {e}")
    elif msg.voice:
        file_id = msg.voice.file_id
        content_type = "voice"
        try:
            local_path = await download_media(file_id, "ogg")
        except Exception as e:
            logger.error(f"Ошибка сохранения голосового: {e}")
    elif msg.sticker:
        file_id = msg.sticker.file_id
        content_type = "sticker"

    save_msg(msg.chat.id, msg.message_id, user_id, user_name, content_type, text, file_id, caption, local_path)

    # Ответ на фото (только для исчезающих)
    if msg.reply_to_message and msg.reply_to_message.photo:
        if not getattr(msg.reply_to_message, 'has_protected_content', False):
            return
        reply_key = (msg.chat.id, msg.message_id)
        if reply_key in processed_replies:
            return
        processed_replies.add(reply_key)
        if len(processed_replies) > 1000:
            processed_replies.clear()
        required_channel = get_setting("required_channel")
        if await send_reminder_if_unsubscribed(msg.from_user.id, required_channel):
            try:
                local_path = get_msg_local_path(msg.chat.id, msg.reply_to_message.message_id)
                logger.info(f"Поиск фото для ответа: chat_id={msg.chat.id}, msg_id={msg.reply_to_message.message_id}, local_path={local_path}")
                if local_path and os.path.exists(local_path):
                    with open(local_path, "rb") as f:
                        mention = f'<a href="tg://user?id={msg.reply_to_message.from_user.id}">{escape(msg.reply_to_message.from_user.first_name)}</a>'
                        footer = get_ad_footer()
                        await bot.send_photo(
                            msg.from_user.id,
                            f,
                            caption=f"📸 Фото, на которое вы ответили (от {mention}){footer}",
                            parse_mode="HTML"
                        )
                else:
                    logger.warning(f"Локальный файл не найден, пробуем скачать file_id={msg.reply_to_message.photo[-1].file_id}")
                    try:
                        tmp_path = await download_media(msg.reply_to_message.photo[-1].file_id, "jpg")
                        with open(tmp_path, "rb") as f:
                            mention = f'<a href="tg://user?id={msg.reply_to_message.from_user.id}">{escape(msg.reply_to_message.from_user.first_name)}</a>'
                            footer = get_ad_footer()
                            await bot.send_photo(
                                msg.from_user.id,
                                f,
                                caption=f"📸 Фото, на которое вы ответили (от {mention}){footer}",
                                parse_mode="HTML"
                            )
                        os.remove(tmp_path)
                    except Exception as e2:
                        await bot.send_message(msg.from_user.id, f"❌ Не удалось сохранить фото: {e2}")
            except Exception as e:
                logger.error(f"Ошибка при отправке фото: {e}")
                await bot.send_message(msg.from_user.id, f"❌ Не удалось сохранить фото: {str(e)}")

@bot.edited_business_message_handler(content_types=["text"])
async def handle_edit(msg):
    if not msg.business_connection_id:
        return
    business_connection = await bot.get_business_connection(msg.business_connection_id)
    owner_id = business_connection.user_chat_id
    # logger.info(f"handle_edit: owner_id={owner_id}, chat_id={msg.chat.id}")  # закомментировано, чтобы не спамить

    old = get_msg(msg.chat.id, msg.message_id)
    if not old:
        return
    user_id, user_name, content_type, old_content, file_id, caption, local_path = old
    if content_type != "text" or old_content == msg.text:
        return

    if user_id != owner_id:
        required_channel = get_setting("required_channel")
        if await send_reminder_if_unsubscribed(owner_id, required_channel):
            mention = f'<a href="tg://user?id={user_id}">{escape(user_name)}</a>'
            diff_text = (f"✏️ <b>{mention} изменил(а) сообщение:</b>\n\n"
                         f"<b>Было:</b>\n<blockquote><b>{escape(old_content)}</b></blockquote>\n\n"
                         f"<b>Стало:</b>\n<blockquote><b>{escape(msg.text)}</b></blockquote>\n"
                         f"\n<b>Изменилось:</b>\n<blockquote>{highlight_diff(old_content, msg.text)}</blockquote>")
            footer = get_ad_footer()
            await safe_send_message(owner_id, diff_text + footer, parse_mode="HTML")
    update_edit(msg.chat.id, msg.message_id, msg.text)

@bot.deleted_business_messages_handler()
async def handle_delete(event: BusinessMessagesDeleted):
    if not event.business_connection_id:
        return
    business_connection = await bot.get_business_connection(event.business_connection_id)
    owner_id = business_connection.user_chat_id
    logger.info(f"handle_delete: owner_id={owner_id}, chat_id={event.chat.id}")

    for msg_id in event.message_ids:
        old = get_msg(event.chat.id, msg_id)
        if not old:
            continue
        user_id, user_name, content_type, content, file_id, caption, local_path = old
        mark_deleted(event.chat.id, msg_id)

        if user_id != owner_id:
            required_channel = get_setting("required_channel")
            if not await send_reminder_if_unsubscribed(owner_id, required_channel):
                continue
            mention = f'<a href="tg://user?id={user_id}">{escape(user_name)}</a>'
            footer = get_ad_footer()
            if content_type == "text":
                await safe_send_message(
                    owner_id,
                    f"🗑️ <b>{mention} удалил(а) сообщение:</b>\n\n<blockquote>{escape(content)}</blockquote>{footer}",
                    parse_mode="HTML"
                )
            elif local_path and os.path.exists(local_path):
                try:
                    with open(local_path, "rb") as f:
                        if content_type == "photo":
                            cap_text = f"🗑️ {mention} удалил(а) фото"
                            if caption:
                                cap_text += f"\n\n<blockquote>{escape(caption)}</blockquote>"
                            await bot.send_photo(owner_id, f, caption=cap_text + footer, parse_mode="HTML")
                        elif content_type == "video":
                            cap_text = f"🗑️ {mention} удалил(а) видео"
                            if caption:
                                cap_text += f"\n\n<blockquote>{escape(caption)}</blockquote>"
                            await bot.send_video(owner_id, f, caption=cap_text + footer, parse_mode="HTML")
                        elif content_type == "video_note":
                            await bot.send_video_note(owner_id, f)
                            await safe_send_message(owner_id, f"🗑️ {mention} удалил(а) видеосообщение{footer}", parse_mode="HTML")
                        elif content_type == "voice":
                            await bot.send_voice(owner_id, f, caption=f"🗑️ {mention} удалил(а) голосовое{footer}", parse_mode="HTML")
                        else:
                            await bot.send_document(owner_id, f, caption=f"🗑️ {mention} удалил(а) {content_type}{footer}")
                except Exception as e:
                    await safe_send_message(owner_id, f"❌ Не удалось отправить удалённый файл: {e}")
            elif file_id:
                try:
                    if content_type == "photo":
                        cap_text = f"🗑️ {mention} удалил(а) фото"
                        if caption:
                            cap_text += f"\n\n<blockquote>{escape(caption)}</blockquote>"
                        await bot.send_photo(owner_id, file_id, caption=cap_text + footer, parse_mode="HTML")
                    elif content_type == "video":
                        cap_text = f"🗑️ {mention} удалил(а) видео"
                        if caption:
                            cap_text += f"\n\n<blockquote>{escape(caption)}</blockquote>"
                        await bot.send_video(owner_id, file_id, caption=cap_text + footer, parse_mode="HTML")
                    elif content_type == "video_note":
                        await bot.send_video_note(owner_id, file_id)
                        await safe_send_message(owner_id, f"🗑️ {mention} удалил(а) видеосообщение{footer}", parse_mode="HTML")
                    elif content_type == "voice":
                        await bot.send_voice(owner_id, file_id, caption=f"🗑️ {mention} удалил(а) голосовое{footer}", parse_mode="HTML")
                except Exception as e:
                    await safe_send_message(owner_id, f"❌ Не удалось отправить файл: {e}")
            else:
                await safe_send_message(owner_id, f"⚠️ Нет данных для восстановления удалённого {content_type} от {mention}{footer}")

# ========== АДМИН-ПАНЕЛЬ ==========
def admin_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
        InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")
    )
    keyboard.add(
        InlineKeyboardButton("🖼 Приветственное фото", callback_data="admin_set_welcome_photo"),
        InlineKeyboardButton("📝 Текст приветствия", callback_data="admin_set_welcome_text")
    )
    keyboard.add(
        InlineKeyboardButton("🔗 Ссылка на канал", callback_data="admin_set_channel_link"),
        InlineKeyboardButton("🔒 Обязательный канал", callback_data="admin_set_required_channel")
    )
    keyboard.add(
        InlineKeyboardButton("📘 Пост/инструкция", callback_data="admin_set_post_link"),
        InlineKeyboardButton("📥 Экспорт базы", callback_data="admin_export_db")
    )
    keyboard.add(
        InlineKeyboardButton("🗑 Очистить статистику", callback_data="admin_clear_stats"),
        InlineKeyboardButton("⏰ Время хранения (дни)", callback_data="admin_set_keep_days")
    )
    keyboard.add(
        InlineKeyboardButton("📢 Управление рекламой", callback_data="admin_manage_ads"),
        InlineKeyboardButton("🎁 Создать розыгрыш", callback_data="admin_create_giveaway")
    )
    return keyboard

def back_button():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin"))
    return keyboard

def ads_management_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("➕ Добавить рекламу", callback_data="admin_add_ad"))
    keyboard.add(InlineKeyboardButton("📋 Список рекламы", callback_data="admin_list_ads"))
    keyboard.add(InlineKeyboardButton("❌ Удалить рекламу", callback_data="admin_delete_ad"))
    keyboard.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin"))
    return keyboard

@bot.message_handler(commands=['admin'])
async def admin_panel(message):
    if message.from_user.id not in ADMIN_IDS:
        await bot.reply_to(message, "⛔ Нет доступа")
        return
    await bot.send_message(message.chat.id, "🔐 <b>Админ-панель</b>", reply_markup=admin_keyboard(), parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
async def admin_callback(call):
    if call.from_user.id not in ADMIN_IDS:
        await bot.answer_callback_query(call.id, "Нет доступа", show_alert=True)
        return
    await bot.answer_callback_query(call.id)

    data = call.data
    if data == "admin_stats":
        total, photos, edited, deleted, users, chats, subscriptions = get_statistics()
        text = (f"📊 <b>Статистика</b>\n\n"
                f"📝 Всего сообщений: {total}\n"
                f"📸 Фото: {photos}\n"
                f"✏️ Изменённых: {edited}\n"
                f"🗑 Удалённых: {deleted}\n"
                f"👥 Пользователей: {users}\n"
                f"💼 Бизнес-чатов: {chats}\n"
                f"🔔 Подписок на канал: {subscriptions}")
        await bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=back_button())
    elif data == "admin_broadcast":
        await bot.edit_message_text(
            "📢 <b>Рассылка</b>\n\nОтправьте сообщение (текст, фото, видео, документ). Оно будет разослано всем пользователям.",
            call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=back_button()
        )
        set_state(call.from_user.id, "waiting_broadcast")
    elif data == "admin_set_welcome_photo":
        await bot.edit_message_text(
            "🖼 Отправьте фото для приветствия.", call.message.chat.id, call.message.message_id, reply_markup=back_button()
        )
        set_state(call.from_user.id, "waiting_welcome_photo")
    elif data == "admin_set_welcome_text":
        await bot.edit_message_text(
            "📝 Отправьте текст приветствия (можно HTML).", call.message.chat.id, call.message.message_id, reply_markup=back_button()
        )
        set_state(call.from_user.id, "waiting_welcome_text")
    elif data == "admin_set_channel_link":
        await bot.edit_message_text(
            "🔗 Отправьте ссылку на канал (https://t.me/...).", call.message.chat.id, call.message.message_id, reply_markup=back_button()
        )
        set_state(call.from_user.id, "waiting_channel_link")
    elif data == "admin_set_required_channel":
        await bot.edit_message_text(
            "🔒 Отправьте username канала (например, @channel). Пустое сообщение – отключить.",
            call.message.chat.id, call.message.message_id, reply_markup=back_button()
        )
        set_state(call.from_user.id, "waiting_required_channel")
    elif data == "admin_set_post_link":
        await bot.edit_message_text(
            "📘 Отправьте ссылку на пост/инструкцию (https://t.me/...).",
            call.message.chat.id, call.message.message_id, reply_markup=back_button()
        )
        set_state(call.from_user.id, "waiting_post_link")
    elif data == "admin_export_db":
        if os.path.exists("bot_data.db"):
            with open("bot_data.db", "rb") as f:
                await bot.send_document(call.from_user.id, f, caption="📦 Экспорт базы данных")
            await bot.edit_message_text("✅ База отправлена", call.message.chat.id, call.message.message_id, reply_markup=back_button())
        else:
            await bot.edit_message_text("❌ База не найдена", call.message.chat.id, call.message.message_id, reply_markup=back_button())
    elif data == "admin_clear_stats":
        await bot.edit_message_text(
            "⚠️ <b>Очистка статистики</b>\n\nВы уверены? Это удалит все сохранённые сообщения.\nВведите <code>/confirm_clear</code> для подтверждения.",
            call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=back_button()
        )
        set_state(call.from_user.id, "waiting_clear_confirm")
    elif data == "admin_set_keep_days":
        await bot.edit_message_text(
            "⏰ Отправьте число (количество дней), сколько хранить файлы и записи в БД.\n0 – отключить автоочистку.",
            call.message.chat.id, call.message.message_id, reply_markup=back_button()
        )
        set_state(call.from_user.id, "waiting_keep_days")
    elif data == "admin_manage_ads":
        await bot.edit_message_text("📢 <b>Управление рекламой</b>\n\nВыберите действие:", call.message.chat.id, call.message.message_id, reply_markup=ads_management_keyboard(), parse_mode="HTML")
    elif data == "admin_add_ad":
        await bot.edit_message_text(
            "➕ <b>Добавление рекламы</b>\n\nОтправьте текст рекламного блока (можно HTML).\nДля отмены введите /cancel.",
            call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=back_button()
        )
        set_state(call.from_user.id, "waiting_ad_text")
    elif data == "admin_list_ads":
        ads = get_all_ads()
        if not ads:
            await bot.edit_message_text("📋 Список рекламы пуст.", call.message.chat.id, call.message.message_id, reply_markup=back_button())
        else:
            lines = ["<b>Список рекламы:</b>\n"]
            for ad_id, text, url in ads:
                line = f"<b>{ad_id}</b>. {text[:50]}"
                if url:
                    line += f" (<a href='{url}'>ссылка</a>)"
                lines.append(line)
            await bot.edit_message_text("\n".join(lines), call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=back_button())
    elif data == "admin_delete_ad":
        ads = get_all_ads()
        if not ads:
            await bot.edit_message_text("❌ Нет рекламных блоков для удаления.", call.message.chat.id, call.message.message_id, reply_markup=back_button())
        else:
            lines = ["<b>Выберите ID для удаления.</b>\nОтправьте номер ID.\n\nСписок:"]
            for ad_id, text, url in ads:
                line = f"<b>{ad_id}</b>. {text[:50]}"
                if url:
                    line += f" (<a href='{url}'>ссылка</a>)"
                lines.append(line)
            await bot.edit_message_text("\n".join(lines), call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=back_button())
            set_state(call.from_user.id, "waiting_ad_delete_id")
    elif data == "back_to_admin":
        await bot.edit_message_text("🔐 <b>Админ-панель</b>", call.message.chat.id, call.message.message_id, reply_markup=admin_keyboard(), parse_mode="HTML")
        set_state(call.from_user.id, None)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_admin")
async def back_to_admin_callback(call):
    if call.from_user.id not in ADMIN_IDS:
        await bot.answer_callback_query(call.id, "Нет доступа", show_alert=True)
        return
    await bot.edit_message_text("🔐 <b>Админ-панель</b>", call.message.chat.id, call.message.message_id, reply_markup=admin_keyboard(), parse_mode="HTML")
    set_state(call.from_user.id, None)
    await bot.answer_callback_query(call.id)

@bot.message_handler(commands=['confirm_clear'])
async def confirm_clear(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    with sqlite3.connect("bot_data.db") as conn:
        conn.execute("DELETE FROM messages")
        conn.commit()
    await bot.reply_to(message, "✅ Все сообщения удалены.", reply_markup=admin_keyboard())

# ========== ОБРАБОТЧИК ВВОДА ОТ АДМИНА ==========
@bot.message_handler(content_types=['text', 'photo', 'video', 'document'], func=lambda msg: msg.text is None or not msg.text.startswith('/'))
async def handle_admin_input(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    state = get_state(message.from_user.id)
    if not state:
        return

    if state == "waiting_broadcast":
        users = get_all_users()
        if not users:
            await bot.send_message(message.chat.id, "Нет пользователей для рассылки.")
            set_state(message.from_user.id, None)
            return
        success = 0
        for uid in users:
            try:
                if message.photo:
                    await bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption)
                elif message.video:
                    await bot.send_video(uid, message.video.file_id, caption=message.caption)
                elif message.document:
                    await bot.send_document(uid, message.document.file_id, caption=message.caption)
                elif message.text:
                    await bot.send_message(uid, message.text, parse_mode="HTML")
                success += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass
        await bot.send_message(message.chat.id, f"✅ Отправлено: {success}/{len(users)}")
        set_state(message.from_user.id, None)
    elif state == "waiting_welcome_photo" and message.photo:
        set_setting("welcome_photo", message.photo[-1].file_id)
        await bot.send_message(message.chat.id, "✅ Приветственное фото сохранено.")
        set_state(message.from_user.id, None)
    elif state == "waiting_welcome_text" and message.text:
        set_setting("welcome_text", message.text)
        await bot.send_message(message.chat.id, "✅ Текст приветствия сохранён.")
        set_state(message.from_user.id, None)
    elif state == "waiting_channel_link" and message.text:
        set_setting("channel_link", message.text)
        await bot.send_message(message.chat.id, "✅ Ссылка на канал сохранена.")
        set_state(message.from_user.id, None)
    elif state == "waiting_required_channel":
        channel = message.text.strip()
        if not channel:
            set_setting("required_channel", "")
            await bot.send_message(message.chat.id, "✅ Проверка подписки отключена.")
        else:
            set_setting("required_channel", channel)
            await bot.send_message(message.chat.id, f"✅ Обязательный канал установлен: {channel}")
        set_state(message.from_user.id, None)
    elif state == "waiting_post_link" and message.text:
        set_setting("post_link", message.text)
        await bot.send_message(message.chat.id, "✅ Ссылка на пост/инструкцию сохранена.")
        set_state(message.from_user.id, None)
    elif state == "waiting_keep_days" and message.text:
        try:
            days = int(message.text.strip())
            set_setting("keep_days", str(days))
            await bot.send_message(message.chat.id, f"✅ Время хранения установлено: {days} дней.")
        except:
            await bot.send_message(message.chat.id, "❌ Ошибка: введите целое число.")
        set_state(message.from_user.id, None)
    elif state == "waiting_ad_text" and message.text:
        user_giveaway_data[message.from_user.id] = {"ad_text": message.text}
        set_state(message.from_user.id, "waiting_ad_url")
        await bot.send_message(message.chat.id, "Теперь отправьте URL рекламной ссылки (или /skip, чтобы пропустить).")
        return
    elif state == "waiting_ad_url" and message.text:
        ad_text = user_giveaway_data.get(message.from_user.id, {}).get("ad_text")
        if not ad_text:
            await bot.send_message(message.chat.id, "❌ Ошибка: текст рекламы не найден. Попробуйте заново.")
            set_state(message.from_user.id, None)
            return
        url = None
        if message.text.strip() != "/skip":
            url = message.text.strip()
        new_id = add_ad(ad_text, url)
        await bot.send_message(message.chat.id, f"✅ Рекламный блок добавлен. ID: {new_id}")
        if message.from_user.id in user_giveaway_data:
            del user_giveaway_data[message.from_user.id]
        set_state(message.from_user.id, None)
        await bot.send_message(message.chat.id, "🔐 Админ-панель", reply_markup=admin_keyboard(), parse_mode="HTML")
    elif state == "waiting_ad_url" and message.text and message.text.startswith('/'):
        set_state(message.from_user.id, None)
        await bot.send_message(message.chat.id, "❌ Добавление отменено.")
    elif state == "waiting_ad_delete_id" and message.text:
        try:
            ad_id = int(message.text.strip())
            delete_ad(ad_id)
            await bot.send_message(message.chat.id, f"✅ Рекламный блок {ad_id} удалён.")
        except Exception as e:
            await bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
        set_state(message.from_user.id, None)
        await bot.send_message(message.chat.id, "🔐 Админ-панель", reply_markup=admin_keyboard(), parse_mode="HTML")
    elif state == "waiting_clear_confirm":
        if message.text == "/confirm_clear":
            with sqlite3.connect("bot_data.db") as conn:
                conn.execute("DELETE FROM messages")
                conn.commit()
            await bot.send_message(message.chat.id, "✅ Все сообщения удалены.")
        else:
            await bot.send_message(message.chat.id, "❌ Отменено. Введите /confirm_clear для подтверждения.")
        set_state(message.from_user.id, None)

# ========== ОБРАБОТЧИК УЧАСТИЯ В РОЗЫГРЫШЕ ==========
@bot.callback_query_handler(func=lambda call: call.data == "giveaway_join")
async def giveaway_join_callback(call):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, end_time FROM giveaways WHERE chat_id=? AND message_id=? AND is_active=1", (call.message.chat.id, call.message.message_id))
        row = cursor.fetchone()
        if not row:
            await bot.answer_callback_query(call.id, "Розыгрыш не найден или уже завершён", show_alert=True)
            return
        giveaway_id, end_time_str = row
        end_time = datetime.fromisoformat(end_time_str)
        if datetime.now() > end_time:
            await bot.answer_callback_query(call.id, "Розыгрыш уже завершён", show_alert=True)
            return

    user_id = call.from_user.id
    required_channel = get_setting("required_channel")
    if not required_channel:
        await bot.answer_callback_query(call.id, "Не задан обязательный канал", show_alert=True)
        return

    if not await is_subscribed(user_id, required_channel):
        keyboard = InlineKeyboardMarkup()
        channel_username = required_channel.lstrip('@')
        keyboard.add(InlineKeyboardButton("🔔 Подписаться", url=f"https://t.me/{channel_username}"))
        keyboard.add(InlineKeyboardButton("✅ Я подписался", callback_data="check_subscription"))
        await bot.send_message(
            user_id,
            f"❌ Для участия в розыгрыше подпишитесь на канал @{channel_username}.\nПосле подписки нажмите кнопку ниже.",
            reply_markup=keyboard
        )
        await bot.answer_callback_query(call.id, "Требуется подписка на канал", show_alert=True)
        return

    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if not cursor.fetchone():
            await bot.answer_callback_query(call.id, "Сначала активируйте бота: отправьте /start", show_alert=True)
            return

    success = add_participant(giveaway_id, user_id)
    if success:
        participants_count = get_participants_count(giveaway_id)
        new_keyboard = InlineKeyboardMarkup()
        new_keyboard.add(InlineKeyboardButton(f"🎉 Участвовать ({participants_count})", callback_data="giveaway_join"))
        try:
            await bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=new_keyboard
            )
        except Exception as e:
            logger.error(f"Не удалось обновить клавиатуру: {e}")
        await bot.answer_callback_query(call.id, "✅ Вы участвуете в розыгрыше!", show_alert=False)
    else:
        await bot.answer_callback_query(call.id, "Вы уже участвуете в этом розыгрыше.", show_alert=False)

# ========== ПРИВЕТСТВИЕ ==========
@bot.message_handler(commands=['start'])
async def start_command(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or str(user_id)
    username = message.from_user.username
    update_user(user_id, user_name, username)

    required_channel = get_setting("required_channel")
    if user_id not in ADMIN_IDS and required_channel and not await is_subscribed(user_id, required_channel):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔔 Подписаться", url=f"https://t.me/{required_channel.lstrip('@')}"))
        keyboard.add(InlineKeyboardButton("✅ Я подписался", callback_data="check_subscription"))
        await bot.send_message(message.chat.id,
            f"❌ Для использования бота подпишитесь на канал @{required_channel.lstrip('@')}",
            reply_markup=keyboard
        )
        return

    welcome_photo = get_setting("welcome_photo")
    welcome_text = get_setting("welcome_text")
    channel_link = get_setting("channel_link")
    post_link = get_setting("post_link")
    
    bot_user = await bot.get_me()
    bot_username = bot_user.username
    
    keyboard = InlineKeyboardMarkup()
    if post_link:
        keyboard.add(InlineKeyboardButton("📘 Как подключить бота?", url=post_link))
    else:
        keyboard.add(InlineKeyboardButton("📘 Как подключить бота?", callback_data="help"))
    keyboard.add(InlineKeyboardButton("🤖 Скопировать username бота", callback_data="copy_username"))
    if channel_link:
        keyboard.add(InlineKeyboardButton("📢 Наш канал", url=channel_link))

    if welcome_photo:
        try:
            await bot.send_photo(
                message.chat.id, 
                welcome_photo, 
                caption=welcome_text or f"Добро пожаловать!\n\n<b>Username бота:</b> @{bot_username}",
                reply_markup=keyboard
            )
        except Exception:
            await bot.send_message(
                message.chat.id, 
                welcome_text or f"Добро пожаловать! Я бот для сохранения бизнес-сообщений.\n\n<b>Username бота:</b> @{bot_username}", 
                reply_markup=keyboard,
                parse_mode="HTML"
            )
    else:
        default_text = f"Добро пожаловать! Я бот для сохранения бизнес-сообщений.\n\n<b>Username бота:</b> @{bot_username}\n\nНажмите кнопку ниже, чтобы скопировать username и добавить меня в свой бизнес-аккаунт."
        await bot.send_message(
            message.chat.id, 
            welcome_text or default_text, 
            reply_markup=keyboard,
            parse_mode="HTML"
        )

# ========== КОЛБЭКИ ==========
@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
async def check_subscription_callback(call):
    user_id = call.from_user.id
    required_channel = get_setting("required_channel")
    if not required_channel:
        await bot.answer_callback_query(call.id, "Канал не задан", show_alert=True)
        return
    await asyncio.sleep(2)
    if await is_subscribed(user_id, required_channel):
        add_subscription_event(user_id, "subscribe")
        await bot.delete_message(call.message.chat.id, call.message.message_id)
        await start_command(call.message)
        await bot.answer_callback_query(call.id, "✅ Доступ открыт!", show_alert=True)
    else:
        await bot.answer_callback_query(call.id, "❌ Вы ещё не подписаны", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data == "help")
async def help_callback(call):
    help_text = get_setting("help_text")
    if not help_text:
        help_text = (
            "🔧 <b>Как подключить бота в Telegram Business:</b>\n\n"
            "1. Откройте настройки Telegram Business.\n"
            "2. Выберите раздел «Боты».\n"
            "3. Добавьте этого бота.\n"
            "4. Настройте права: бот должен видеть все сообщения (Manage messages).\n"
            "5. Теперь бот будет сохранять все бизнес-сообщения, а при удалении/изменении присылать копии."
        )
    await bot.send_message(call.message.chat.id, help_text, parse_mode="HTML")
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "copy_username")
async def copy_username_callback(call):
    bot_user = await bot.get_me()
    bot_username = bot_user.username
    msg = await bot.send_message(
        call.message.chat.id,
        f"<b>Username бота:</b> <code>@{bot_username}</code>\n\n"
        f"Выделите текст выше и скопируйте его.",
        parse_mode="HTML"
    )
    await asyncio.sleep(10)
    try:
        await bot.delete_message(call.message.chat.id, msg.message_id)
    except:
        pass
    await bot.answer_callback_query(call.id)

# ========== ЗАПУСК ==========
async def main():
    print("Бот запущен.")
    asyncio.create_task(cleanup_old_files()) 
            "business_message",
            "edited_business_message",
            "deleted_business_messages",
            "message",
            "callback_query"
        ]
    )

if __name__ == "__main__":
    asyncio.run(main())
