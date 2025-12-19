# webhook_app.py - СИНХРОННАЯ ВЕРСИЯ ДЛЯ FLASK
from flask import Flask, request, jsonify
import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============== НАСТРОЙКИ ДЛЯ RAILWAY ==============
import os

# Получаем токен из переменных окружения Railway
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен! Добавьте его в Railway Variables.")

# Получаем URL Railway
RAILWAY_STATIC_URL = os.environ.get('RAILWAY_STATIC_URL')
if RAILWAY_STATIC_URL:
    WEBHOOK_HOST = RAILWAY_STATIC_URL
else:
    # Явно указываем URL
    WEBHOOK_HOST = "https://web-production-1a5d8.up.railway.app"

# Убедимся, что есть https://
if not WEBHOOK_HOST.startswith('http'):
    WEBHOOK_HOST = f"https://{WEBHOOK_HOST}"

WEBHOOK_PATH = f'/webhook/{BOT_TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

logger.info(f"BOT_TOKEN: {'установлен' if BOT_TOKEN else 'НЕ установлен'}")
logger.info(f"WEBHOOK_HOST: {WEBHOOK_HOST}")
# ===================================================

# ИМПОРТЫ ДЛЯ AIOGRAM 2.25.1
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor

# Инициализация для aiogram 2.25.1
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Импорт базы данных
try:
    from database import SessionLocal, Game, Participant
    logger.info("База данных импортирована успешно")
except ImportError as e:
    logger.error(f"Ошибка импорта database.py: {e}")
    SessionLocal = None
    Game = None
    Participant = None

# ============== ПРОСТЫЕ ОБРАБОТЧИКИ ==============
@dp.message_handler(commands=['start'])
async def handle_start(message: types.Message):
    """Обработчик команды /start"""
    await message.answer(
        f"🎅 Привет, {message.from_user.first_name}!\n\n"
        f"Бот работает на Railway!\n"
        f"Используй /help для списка команд."
    )

@dp.message_handler(commands=['help'])
async def handle_help(message: types.Message):
    """Обработчик команды /help"""
    await message.answer(
        "Помощь:\n"
        "/start - начать\n"
        "/help - помощь\n"
        "/test - тест базы данных\n"
        "Бот работает на Railway!"
    )

@dp.message_handler()
async def handle_all_messages(message: types.Message):
    """Обработка всех сообщений"""
    await message.answer(f"Вы сказали: {message.text}\nИспользуйте /help")

# ============== СИНХРОННЫЕ FLASK РОУТЫ ==============
@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    """Основной обработчик вебхуков от Telegram"""
    try:
        update = types.Update(**request.get_json())
        
        # Создаем event loop для асинхронного вызова
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(dp.process_update(update))
            return jsonify({'status': 'ok'})
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"Ошибка в webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/')
def index():
    return "🎅 Бот 'Тайный Санта' работает на Railway!<br>Статус: ONLINE<br><a href='/set_webhook'>Установить вебхук</a>"

@app.route('/set_webhook')
def set_webhook():
    """Установка вебхука"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(bot.set_webhook(WEBHOOK_URL))
            logger.info(f"Вебхук установлен: {WEBHOOK_URL}")
            return f"✅ Вебхук установлен!<br>URL: {WEBHOOK_URL}"
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"Ошибка установки вебхука: {e}")
        return f"❌ Ошибка: {str(e)}"

@app.route('/delete_webhook')
def delete_webhook():
    """Удаление вебхука"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(bot.delete_webhook())
            return "✅ Вебхук удален!"
        finally:
            loop.close()
            
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"

@app.route('/status')
def status():
    """Проверка статуса бота"""
    import datetime
    return jsonify({
        'status': 'online',
        'service': 'Secret Santa Bot on Railway',
        'timestamp': datetime.datetime.now().isoformat(),
        'webhook_url_set': True,
        'host': WEBHOOK_HOST
    })

# ============== ЗАПУСК ПРИЛОЖЕНИЯ ==============
if __name__ == '__main__':
    print("Запуск Flask приложения...")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
