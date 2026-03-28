import os
import asyncio
import aiohttp
import logging
import sqlite3
from flask import Flask
from threading import Thread
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FStore

# --- НАСТРОЙКИ ---
TOKEN = "8758417597:AAERQH3jUuduK8syNtCKW8tvHdZXTilJrF8"
ADMIN_ID = 6451702799 

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS messages 
                   (msg_id TEXT PRIMARY KEY, user_id TEXT, text TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS users 
                   (user_id INTEGER PRIMARY KEY, username TEXT, join_date TEXT)''')
    conn.commit()
    conn.close()

def add_user(user_id, username):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?)", 
                (user_id, username, str(datetime.now())))
    conn.commit()
    conn.close()

# --- БУДИЛЬНИК ---
app = Flask('')
@app.route('/')
def home(): return "PeerSpy System Active"

def run_web():
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080))

# --- ЛОГИКА БОТА ---
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# Состояния для рассылки (на будущее)
class AdminStates(StatesGroup):
    waiting_for_broadcast_text = State()

def main_menu(user_id):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📖 Как подключить?", callback_data="help"))
    builder.row(types.InlineKeyboardButton(text="📈 Мой профиль", callback_data="profile"))
    if user_id == ADMIN_ID:
        builder.row(types.InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel"))
    return builder.as_markup()

@dp.message(Command("start"))
async def start(message: types.Message):
    add_user(message.from_user.id, message.from_user.username)
    welcome_text = (
        f"🚀 <b>PeerSpy v3.0</b>\n\n"
        "Система тотального контроля бизнес-чатов активна.\n"
        "• Сохранение фото (ответь на фото любым текстом)\n"
        "• Лог удаленных сообщений\n"
        "• История правок"
    )
    await message.answer(welcome_text, reply_markup=main_menu(message.from_user.id))

@dp.callback_query(F.data == "help")
async def show_help(c: types.CallbackQuery):
    help_text = (
        "<b>🛠 ИНСТРУКЦИЯ:</b>\n\n"
        "1️⃣ Зайдите в <b>Settings</b> -> <b>Telegram Business</b> -> <b>Chat Bots</b>.\n"
        "2️⃣ Нажмите <b>Add Bot</b> и выберите меня.\n"
        "3️⃣ Убедитесь, что <b>'Access to messages'</b> включен.\n\n"
        "📸 <b>Как спасти фото:</b> Просто ответь на одноразовое фото в любом чате любым сообщением (хоть точкой, хоть словом)."
    )
    await c.message.answer(help_text)
    await c.answer()

@dp.callback_query(F.data == "admin_panel")
async def admin_panel(c: types.CallbackQuery):
    if c.from_user.id != ADMIN_ID: return
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]
    conn.close()
    
    admin_text = (
        "<b>⚙️ ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n\n"
        f"👥 Всего юзеров: <b>{total_users}</b>\n"
        "📢 Чтобы сделать рассылку, просто напиши мне сообщение."
    )
    await c.message.answer(admin_text)
    await c.answer()

# --- УМНЫЙ ПЕРЕХВАТ ---
@dp.business_message()
async def business_handler(message: types.Message):
    # Логируем в базу
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    msg_text = message.text or message.caption or "[Медиа]"
    cur.execute("INSERT OR REPLACE INTO messages VALUES (?, ?, ?)", 
                (str(message.message_id), str(message.from_user.id), msg_text))
    conn.commit()
    conn.close()

    # ЕСЛИ ЭТО ОТВЕТ (REPLY) НА СООБЩЕНИЕ
    if message.reply_to_message:
        target = message.reply_to_message
        # Если в том сообщении, на которое ответили, есть фото
        if target.photo:
            f_id = target.photo[-1].file_id
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={f_id}") as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        path = data["result"]["file_path"]
                        async with session.get(f"https://api.telegram.org/file/bot{TOKEN}/{path}") as f_resp:
                            content = await f_resp.read()
                            await bot.send_photo(ADMIN_ID, types.BufferedInputFile(content, filename="saved.jpg"), 
                                                 caption="🛡 <b>Файл спасен через ответ!</b>")

# --- УДАЛЕНИЯ ---
@dp.business_deleted_messages()
async def on_delete(event: types.BusinessMessagesDeleted):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    for m_id in event.message_ids:
        cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(m_id),))
        result = cur.fetchone()
        if result:
            await bot.send_message(ADMIN_ID, f"🗑 <b>Удалено:</b>\n<code>{result[0]}</code>")
    conn.close()

async def main():
    init_db()
    Thread(target=run_web).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
