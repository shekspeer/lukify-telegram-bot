import os
import asyncio
import aiohttp
import logging
import sqlite3
from flask import Flask
from threading import Thread
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties

# --- КОНФИГ ---
# ВСТАВЬ СЮДА НОВЫЙ ТОКЕН ИЗ BOTFATHER!
TOKEN = "8758417597:AAGehESdxFCGN4SWZAROc4SFTL1-nlQPDBw"
ADMIN_ID = 6451702799 

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS messages (msg_id TEXT PRIMARY KEY, text TEXT)''')
    conn.commit()
    conn.close()

# --- ВЕБ-СЕРВЕР ---
app = Flask('')
@app.route('/')
def home(): return "PeerSpy v6.0: System Online"

def run_web():
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080))

# --- ЯДРО ---
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

@dp.update()
async def on_update(update: types.Update):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    try:
        # ПЕРЕХВАТ БИЗНЕС-ЛОГИКИ
        msg = update.business_message or update.edited_business_message
        if msg:
            m_id = str(msg.message_id)
            txt = msg.text or msg.caption or "[Медиа]"
            
            cur.execute("SELECT text FROM messages WHERE msg_id=?", (m_id,))
            old = cur.fetchone()
            if old and old[0] != txt:
                await bot.send_message(ADMIN_ID, f"📝 <b>ИЗМЕНЕНО</b>\n───\n<b>Было:</b> {old[0]}\n<b>Стало:</b> {txt}")
            
            cur.execute("INSERT OR REPLACE INTO messages VALUES (?, ?)", (m_id, txt))
            conn.commit()

        # ПЕРЕХВАТ УДАЛЕНИЙ
        elif update.business_deleted_messages:
            for m_id in update.business_deleted_messages.message_ids:
                cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(m_id),))
                res = cur.fetchone()
                if res:
                    await bot.send_message(ADMIN_ID, f"🗑 <b>УДАЛЕНО</b>\n───\n{res[0]}")

        # СТАРТ
        elif update.message and update.message.text == "/start":
            await update.message.answer("🚀 <b>PeerSpy v6.0 Active!</b>\nКонфликтов больше нет.")

    except Exception as e:
        logging.error(f"Error: {e}")
    finally:
        conn.close()

async def main():
    init_db()
    Thread(target=run_web).start()
    
    # ЭТА СТРОЧКА УБИВАЕТ КОНФЛИКТЫ И ОЧЕРЕДИ
    await bot.delete_webhook(drop_pending_updates=True) 
    
    print("🚀 БОТ ЗАПУСКАЕТСЯ БЕЗ ХВОСТОВ...")
    await dp.start_polling(bot, allowed_updates=["message", "business_message", "edited_business_message", "business_deleted_messages"])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
