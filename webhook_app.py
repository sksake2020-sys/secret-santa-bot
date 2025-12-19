# webhook_app.py - ВЕРСИЯ ДЛЯ RAILWAY.APP
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
    # Для локальной разработки можно указать токен здесь
    BOT_TOKEN = "8572653274:AAHDvbfPcGSRzJl-RQ11m4akOW1Wq0NmXYw"  # ТОЛЬКО ДЛЯ ТЕСТА, потом удалить!

# Получаем URL Railway
RAILWAY_STATIC_URL = os.environ.get('RAILWAY_STATIC_URL')
if RAILWAY_STATIC_URL:
    WEBHOOK_HOST = RAILWAY_STATIC_URL
else:
    # После деплоя Railway даст URL типа: ваш-проект.up.railway.app
    # Временно оставьте так, потом замените на реальный
    WEBHOOK_HOST = "https://web-production-1a5d8.up.railway.app"

WEBHOOK_PATH = f'/webhook/{BOT_TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

# Для отладки
print(f"BOT_TOKEN: {'установлен' if BOT_TOKEN and BOT_TOKEN != '8572653274:AAHDvbfPcGSRzJl-RQ11m4akOW1Wq0NmXYw' else 'НЕ установлен'}")
print(f"WEBHOOK_URL: {WEBHOOK_URL}")
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

# БАЗА ДАННЫХ для Railway (PostgreSQL)
# Railway автоматически предоставляет PostgreSQL и переменную DATABASE_URL
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    # Если есть DATABASE_URL, используем PostgreSQL
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    
    from sqlalchemy import create_engine, Column, Integer, String, Boolean, Text, DateTime
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime
    
    engine = create_engine(DATABASE_URL)
    Base = declarative_base()
    
    class Game(Base):
        __tablename__ = 'games'
        id = Column(Integer, primary_key=True)
        name = Column(String(100), nullable=False)
        admin_id = Column(Integer, nullable=False)
        # ... остальные поля как в вашем database.py
    
    class Participant(Base):
        __tablename__ = 'participants'
        id = Column(Integer, primary_key=True)
        # ... остальные поля как в вашем database.py
    
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    
    logger.info("Использую PostgreSQL базу данных от Railway")
else:
    # Если нет DATABASE_URL, используем SQLite (для локальной разработки)
    logger.warning("DATABASE_URL не найден, использую SQLite")
    from database import SessionLocal, Game, Participant  # ваш старый файл

# ============== ПРОСТЫЕ ОБРАБОТЧИКИ ДЛЯ ТЕСТА ==============
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

@dp.message_handler(commands=['test'])
async def handle_test(message: types.Message):
    """Тест соединения с базой данных"""
    try:
        db = SessionLocal()
        db.execute("SELECT 1")
        await message.answer("✅ База данных работает!")
        db.close()
    except Exception as e:
        await message.answer(f"❌ Ошибка базы данных: {str(e)}")

@dp.message_handler()
async def handle_all_messages(message: types.Message):
    """Обработка всех сообщений"""
    await message.answer(f"Вы сказали: {message.text}\nИспользуйте /help")

# ============== FLASK РОУТЫ ==============
@app.route(WEBHOOK_PATH, methods=['POST'])
async def webhook():
    """Основной обработчик вебхуков от Telegram"""
    try:
        update = types.Update(**request.get_json())
        await dp.process_update(update)
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f"Ошибка в webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/')
def index():
    return "🎅 Бот 'Тайный Санта' работает на Railway!<br>Статус: ONLINE"

@app.route('/set_webhook')
async def set_webhook():
    """Установка вебхука"""
    try:
        await bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Вебхук установлен: {WEBHOOK_URL}")
        return f"✅ Вебхук установлен!<br>URL: {WEBHOOK_URL}"
    except Exception as e:
        logger.error(f"Ошибка установки вебхука: {e}")
        return f"❌ Ошибка: {str(e)}"

@app.route('/delete_webhook')
async def delete_webhook():
    """Удаление вебхука"""
    try:
        await bot.delete_webhook()
        return "✅ Вебхук удален!"
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
        'webhook_url': WEBHOOK_URL,
        'database': 'PostgreSQL' if DATABASE_URL else 'SQLite'
    })

# ============== ЗАПУСК ПРИЛОЖЕНИЯ ==============
if __name__ == '__main__':
    # Этот блок выполняется только при локальном запуске
    print("Запуск Flask приложения...")
    # Получаем порт из переменной окружения (Railway сам назначает)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
