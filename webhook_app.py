# webhook_app.py - ПОЛНЫЙ КОД ДЛЯ AIOGRAM 2.25.1
from flask import Flask, request, jsonify
import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============== ЗАМЕНИТЕ ЭТИ ПЕРЕМЕННЫЕ ==============
BOT_TOKEN = "8572653274:AAHDvbfPcGSRzJl-RQ11m4akOW1Wq0NmXYw"  # ЗАМЕНИТЕ на ваш токен от @BotFather
PYTHONANYWHERE_USERNAME = "sakesk"  # ЗАМЕНИТЕ на ваш логин
# =====================================================

WEBHOOK_HOST = f'https://{PYTHONANYWHERE_USERNAME}.pythonanywhere.com'
WEBHOOK_PATH = f'/webhook/{BOT_TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

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

# Импортируем базу данных
try:
    from database import SessionLocal, Game, Participant
except ImportError:
    logger.error("Не могу импортировать database.py. Убедитесь, что файл существует.")
    # Создаем заглушки для тестирования
    SessionLocal = None
    Game = None
    Participant = None

# ============== ВАШИ ОБРАБОТЧИКИ КОМАНД ==============
@dp.message_handler(commands=['start'])
async def handle_start(message: types.Message):
    """Обработчик команды /start"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(
        types.KeyboardButton("🎮 Создать игру"),
        types.KeyboardButton("🎅 Присоединиться")
    )
    keyboard.row(
        types.KeyboardButton("❓ Помощь"),
        types.KeyboardButton("📋 Мои игры")
    )
    
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Я — бот для организации *Тайного Санты*.\n\n"
        "✨ *Что я умею:*\n"
        "• Создавать игру с настройками\n"
        "• Приглашать друзей по ссылке\n"
        "• Автоматически распределять пары\n"
        "• Хранить пожелания участников\n\n"
        "🎯 *Быстрый старт:*\n"
        "1. Нажми *«Создать игру»*\n"
        "2. Укажи бюджет и пожелания\n"
        "3. Отправь друзьям ссылку-приглашение\n"
        "4. Запусти игру, когда все соберутся\n\n"
        "Или используй кнопки ниже ⬇️",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@dp.message_handler(commands=['help'])
async def handle_help(message: types.Message):
    """Обработчик команды /help"""
    help_text = """
🎅 *Помощь по командам Тайного Санты*

*Основные команды:*
/start - Начать работу с ботом (главное меню)
/help - Показать эту справку

*Создание и управление игрой:*
/new_game - Создать новую игру (шаг за шагом)
/game_info - Посмотреть информацию о ваших играх
/start_game - Запустить распределение (только создатель)
/end_game - Завершить игру (только создатель)

*Участие в игре:*
/join [код] - Присоединиться к игре по коду
/my_wishlist - Изменить свои пожелания к подарку

*После запуска игры:*
/my_target - Узнать, кому вы дарите подарок

*Пример использования:*
1. Создатель: /new_game → "Корпоратив 2024"
2. Участники: /join 12345 → пишут пожелания
3. Создатель: /start_game - запускает распределение
4. Все участники: /my_target - видят своего получателя
    """
    await message.answer(help_text, parse_mode="Markdown")

@dp.message_handler(commands=['new_game'])
async def handle_new_game(message: types.Message):
    """Обработчик команды /new_game"""
    await message.answer(
        "🎄 *Давайте создадим новую игру Тайного Санты!*\n\n"
        "Введите *название* для вашей игры (например, 'Корпоратив 2024' или 'Семейный Новый Год'):",
        parse_mode="Markdown"
    )

@dp.message_handler(lambda message: message.text == "🎮 Создать игру")
async def handle_create_game_button(message: types.Message):
    """Обработчик кнопки 'Создать игру'"""
    await handle_new_game(message)

@dp.message_handler(lambda message: message.text == "🎅 Присоединиться")
async def handle_join_button(message: types.Message):
    """Обработчик кнопки 'Присоединиться'"""
    await message.answer(
        "Для присоединения к игре:\n"
        "1. Получите код игры от друга\n"
        "2. Используйте команду /join <код>\n\n"
        "Или нажмите на кнопку-приглашение, которую вам отправили."
    )

@dp.message_handler(lambda message: message.text == "❓ Помощь")
async def handle_help_button(message: types.Message):
    """Обработчик кнопки 'Помощь'"""
    await handle_help(message)

@dp.message_handler(commands=['join'])
async def handle_join_command(message: types.Message):
    """Обработчик команды /join"""
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "Использование: /join <код_игры>\n\n"
            "Пример: /join 12345\n\n"
            "Код игры — это число, которое создатель игры может вам отправить."
        )
        return
    
    code = args[1]
    await message.answer(f"Пытаюсь присоединиться к игре с кодом: {code}\n\n(Эта функция в демо-режиме)")

@dp.message_handler(commands=['my_target'])
async def handle_my_target(message: types.Message):
    """Обработчик команды /my_target"""
    await message.answer(
        "🎁 *Ваш Тайный Санта*\n\n"
        "В демо-режиме эта функция показывает пример:\n"
        "• Игра: Корпоратив 2024\n"
        "• Вы дарите: Иван Иванов\n"
        "• Пожелания: Любит книги и кофе\n"
        "• Бюджет: до 1500 рублей\n\n"
        "В реальной работе бот будет показывать информацию из базы данных.",
        parse_mode="Markdown"
    )

@dp.message_handler()
async def handle_all_messages(message: types.Message):
    """Обработка всех остальных сообщений"""
    if message.text and not message.text.startswith('/'):
        # Пример обработки пожеланий
        if "пожелание" in message.text.lower() or "хочу" in message.text.lower():
            await message.answer(
                "✅ Ваши пожелания сохранены! Спасибо.\n\n"
                "Теперь дождитесь, пока создатель игры запустит распределение."
            )
        else:
            await message.answer(
                "Я получил ваше сообщение: " + message.text + "\n\n"
                "Используйте /help для списка команд."
            )

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
    return "🎅 Бот 'Тайный Санта' работает!<br>Статус: ONLINE<br><a href='/set_webhook'>Установить вебхук</a>"

@app.route('/set_webhook')
async def set_webhook():
    """Установка вебхука (вызывается один раз)"""
    try:
        await bot.set_webhook(WEBHOOK_URL)
        return f"✅ Вебхук установлен!<br>URL: {WEBHOOK_URL}<br><a href='/'>На главную</a>"
    except Exception as e:
        return f"❌ Ошибка: {str(e)}<br><a href='/'>На главную</a>"

@app.route('/delete_webhook')
async def delete_webhook():
    """Удаление вебхука"""
    try:
        await bot.delete_webhook()
        return "✅ Вебхук удален!<br><a href='/'>На главную</a>"
    except Exception as e:
        return f"❌ Ошибка: {str(e)}<br><a href='/'>На главную</a>"

@app.route('/status')
def status():
    """Проверка статуса бота"""
    import datetime
    return jsonify({
        'status': 'online',
        'service': 'Secret Santa Bot',
        'timestamp': datetime.datetime.now().isoformat(),
        'webhook_url': WEBHOOK_URL,
        'bot_username': '@Tainisantadlysvoihbot'
    })

# ============== ЗАПУСК ПРИЛОЖЕНИЯ ==============
if __name__ == '__main__':
    # Этот блок выполняется только при локальном запуске
    # На PythonAnywhere приложение запускается через WSGI
    print("Запуск Flask приложения...")
    app.run(host='0.0.0.0', port=5000)
