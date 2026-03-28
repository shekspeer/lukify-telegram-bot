import os
import asyncio
import aiohttp
import logging
from flask import Flask
from threading import Thread
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# --- НАСТРОЙКИ ---
TOKEN = "8758417597:AAERQH3jUuduK8syNtCKW8tvHdZXTilJrF8"
ADMIN_ID = 6451702799

# --- БУДИЛЬНИК (чтобы Render не спал) ---
app = Flask('')
@app.route('/')
def home(): return "Бот работает!"

def run_web():
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080))

# --- ЛОГИКА БОТА ---
bot = Bot(token=TOKEN, default=types.DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("🚀 <b>PeerSpy активен!</b>\nОтветь точкой на одноразку в бизнес-чате.")

@dp.business_message()
async def interceptor(message: types.Message):
    target = message.reply_to_message if message.reply_to_message else message
    if target.photo:
        f_id = target.photo[-1].file_id
        async with aiohttp.ClientSession() as session:
            # Тот самый баг getFile
            async with session.get(f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={f_id}") as resp:
                data = await resp.json()
                if data.get("ok"):
                    path = data["result"]["file_path"]
                    f_url = f"https://api.telegram.org/file/bot{TOKEN}/{path}"
                    async with session.get(f_url) as f_resp:
                        content = await f_resp.read()
                        photo = types.BufferedInputFile(content, filename="safe.jpg")
                        await bot.send_photo(ADMIN_ID, photo, caption="🛡️ <b>Файл спасен!</b>")

async def main():
    # Запускаем веб-сервер в отдельном потоке
    Thread(target=run_web).start()
    print("🚀 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
