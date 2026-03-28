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

# --- КОНФИГ ---
TOKEN = "8758417597:AAERQH3jUuduK8syNtCKW8tvHdZXTilJrF8"
ADMIN_ID = 6451702799 

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS messages (msg_id TEXT PRIMARY KEY, text TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT)''')
    conn.commit()
    conn.close()

app = Flask('')
@app.route('/')
def home(): return "PeerSpy Raw Engine Active"

def run_web():
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080))

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# --- ЛОГИКА ОБРАБОТКИ ОБНОВЛЕНИЙ ---

@dp.update()
async def raw_update_handler(update: types.Update):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    
    # 1. ПЕРЕХВАТ НОВОГО БИЗНЕС-СООБЩЕНИЯ
    if update.business_message:
        m = update.business_message
        txt = m.text or m.caption or "[Медиа]"
        cur.execute("INSERT OR REPLACE INTO messages VALUES (?, ?)", (str(m.message_id), txt))
        conn.commit()
        
        # Спасение фото по реплаю
        if m.reply_to_message and m.reply_to_message.photo:
            await bot.send_message(ADMIN_ID, "📸 <b>Обнаружено скрытое фото!</b> Пытаюсь сохранить...")
            f_id = m.reply_to_message.photo[-1].file_id
            # (Код загрузки фото...)

    # 2. ПЕРЕХВАТ ПРАВКИ БИЗНЕС-СООБЩЕНИЯ
    elif update.edited_business_message:
        m = update.edited_business_message
        new_txt = m.text or m.caption or "[Новое медиа]"
        cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(m.message_id),))
        old = cur.fetchone()
        
        if old and old[0] != new_txt:
            await bot.send_message(ADMIN_ID, 
                f"📝 <b>ИЗМЕНЕНИЕ</b>\n"
                f"────────────────────\n"
                f"<b>Было:</b> {old[0]}\n"
                f"<b>Стало:</b> {new_txt}")
        
        cur.execute("INSERT OR REPLACE INTO messages VALUES (?, ?)", (str(m.message_id), new_txt))
        conn.commit()

    # 3. ПЕРЕХВАТ УДАЛЕНИЯ В БИЗНЕСЕ
    elif update.business_deleted_messages:
        event = update.business_deleted_messages
        for m_id in event.message_ids:
            cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(m_id),))
            res = cur.fetchone()
            if res:
                await bot.send_message(ADMIN_ID, 
                    f"🗑 <b>УДАЛЕНО</b>\n"
                    f"────────────────────\n"
                    f"<b>Текст:</b> {res[0]}")

    conn.close()

# --- ОБЫЧНЫЕ КОМАНДЫ ---
@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="💎 Admin Panel", callback_data="adm"))
    await m.answer("<b>PeerSpy Raw v4.5 Active</b> 🛡", reply_markup=kb.as_markup())

async def main():
    init_db()
    Thread(target=run_web).start()
    await dp.start_polling(bot, allowed_updates=["message", "business_message", "edited_business_message", "business_deleted_messages"])

if __name__ == "__main__":
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
