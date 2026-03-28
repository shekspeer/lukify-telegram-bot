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
def home(): return "System Online"

def run_web():
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080))

# --- БОТ ---
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

# --- ОБРАБОТЧИКИ ---

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
    
    await message.answer(f"👋 <b>PeerSpy v3.9</b>\nБизнес-мониторинг активен.", reply_markup=kb.as_markup())

# УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК (Для сообщений и правок)
async def universal_biz_handler(event: types.Message):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    
    msg_id = str(event.message_id)
    new_text = event.text or event.caption or "[Медиа]"
    
    # Проверяем на правку
    cur.execute("SELECT text FROM messages WHERE msg_id=?", (msg_id,))
    old = cur.fetchone()
    
    if old and old[0] != new_text:
        await bot.send_message(ADMIN_ID, f"✏️ <b>Изменено:</b>\nБыло: {old[0]}\nСтало: {new_text}")
    
    # Сохраняем актуальную версию
    cur.execute("INSERT OR REPLACE INTO messages VALUES (?, ?, ?)", (msg_id, str(event.from_user.id), new_text))
    conn.commit()
    conn.close()

    # Сохранение фото
    if event.reply_to_message and event.reply_to_message.photo:
        f_id = event.reply_to_message.photo[-1].file_id
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={f_id}") as r:
                res = await r.json()
                if res.get("ok"):
                    path = res["result"]["file_path"]
                    async with s.get(f"https://api.telegram.org/file/bot{TOKEN}/{path}") as fr:
                        await bot.send_photo(ADMIN_ID, types.BufferedInputFile(await fr.read(), filename="s.jpg"), caption="📸 <b>Фото спасено!</b>")

# Обработчик удалений (только если поддерживается, иначе игнорируем)
async def delete_handler(event: types.BusinessMessagesDeleted):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    for m_id in event.message_ids:
        cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(m_id),))
        res = cur.fetchone()
        if res:
            await bot.send_message(ADMIN_ID, f"🗑 <b>Удалено:</b>\n{res[0]}")
    conn.close()

# --- РЕГИСТРАЦИЯ БЕЗ ОПАСНЫХ АТРИБУТОВ ---
router.message.register(cmd_start, Command("start"))

# Регистрируем ТОЛЬКО business_message. 
# В современных версиях aiogram правки (edited) прилетают в этот же канал, если не указано иное.
router.business_message.register(universal_biz_handler)

# Удаления регистрируем через проверку наличия атрибута (чтобы не упасть)
if hasattr(router, 'business_deleted_messages'):
    router.business_deleted_messages.register(delete_handler)

# Коллбэки
router.callback_query.register(lambda c: c.message.answer("Инструкция: Настройки -> Business"), F.data == "help")
router.callback_query.register(lambda c: c.message.answer("Админка в разработке"), F.data == "admin")

async def main():
    init_db()
    dp.include_router(router)
    Thread(target=run_web).start()
    print("🚀 БОТ ЗАПУЩЕН!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
