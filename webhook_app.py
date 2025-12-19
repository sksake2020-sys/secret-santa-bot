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

# ============== ИНИЦИАЛИЗАЦИЯ AIOGRAM ==============
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor

# Инициализация для aiogram 2.25.1
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# КРИТИЧЕСКИ ВАЖНО: Устанавливаем текущий экземпляр бота
Bot.set_current(bot)  # ← ЭТА СТРОКА ИСПРАВЛЯЕТ ОШИБКУ
# ===================================================
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
# ============== ОСНОВНЫЕ КОМАНДЫ ==============
@dp.message_handler(commands=['start'])
async def handle_start(message: types.Message):
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
    help_text = """
🎅 *Помощь по командам Тайного Санты*

*Основные команды:*
/start - Начать работу с ботом
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
    """
    await message.answer(help_text, parse_mode="Markdown")

@dp.message_handler(lambda message: message.text == "🎮 Создать игру")
async def handle_create_game_button(message: types.Message):
    await message.answer(
        "🎄 *Давайте создадим новую игру Тайного Санты!*\n\n"
        "Введите *название* для вашей игры (например, 'Корпоратив 2024' или 'Семейный Новый Год'):",
        parse_mode="Markdown",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message_handler(lambda message: message.text == "🎅 Присоединиться")
async def handle_join_button(message: types.Message):
    await message.answer(
        "Для присоединения к игре:\n"
        "1. Получите код игры от друга\n"
        "2. Используйте команду /join <код>\n\n"
        "Или нажмите на кнопку-приглашение, которую вам отправили.",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message_handler(lambda message: message.text == "❓ Помощь")
async def handle_help_button(message: types.Message):
    await handle_help(message)

@dp.message_handler(lambda message: message.text == "📋 Мои игры")
async def handle_my_games_button(message: types.Message):
    await message.answer(
        "Функция 'Мои игры' в разработке...\n"
        "Скоро здесь будет список ваших игр!",
        reply_markup=types.ReplyKeyboardRemove()
    )

# Обработчик команды /new_game (с FSM состояниями)
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

class GameCreation(StatesGroup):
    waiting_for_name = State()
    waiting_for_price = State()
    waiting_for_wishlist = State()

@dp.message_handler(commands=['new_game'])
async def cmd_new_game(message: types.Message):
    await GameCreation.waiting_for_name.set()
    await message.answer(
        "🎄 *Давайте создадим новую игру Тайного Санты!*\n\n"
        "Введите *название* для вашей игры:",
        parse_mode="Markdown",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message_handler(state=GameCreation.waiting_for_name)
async def process_game_name(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['name'] = message.text
    
    await GameCreation.next()
    await message.answer(
        "💰 Теперь укажите *ограничение по цене* подарка.\n\n"
        "Например: 'до 1500 рублей', 'в районе 2000₽' или 'без ограничений'.",
        parse_mode="Markdown"
    )

@dp.message_handler(state=GameCreation.waiting_for_price)
async def process_game_price(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['price'] = message.text
    
    await GameCreation.next()
    await message.answer(
        "📝 Отлично! Теперь напишите *ваши пожелания* к подарку.\n\n"
        "Что вам нравится? (хобби, размер одежды, любимые сладости, цвета и т.д.)",
        parse_mode="Markdown"
    )

@dp.message_handler(state=GameCreation.waiting_for_wishlist)
async def process_game_wishlist(message: types.Message, state: FSMContext):
    from database import SessionLocal, Game, Participant
    
    db = SessionLocal()
    try:
        async with state.proxy() as data:
            # Создаем игру
            new_game = Game(
                name=data['name'],
                admin_id=message.from_user.id,
                admin_username=message.from_user.username,
                chat_id=str(message.chat.id),
                gift_price=data['price'],
                wishlist=message.text
            )
            db.add(new_game)
            db.commit()
            db.refresh(new_game)
            
            # Добавляем создателя как первого участника
            creator = Participant(
                game_id=new_game.id,
                user_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                wishlist=message.text
            )
            db.add(creator)
            db.commit()
            
            # Инлайн-кнопка для приглашения
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            invite_keyboard = InlineKeyboardMarkup()
            invite_button = InlineKeyboardButton(
                text="🎅 Присоединиться к игре!",
                callback_data=f"join_game_{new_game.id}"
            )
            invite_keyboard.add(invite_button)
            
            await message.answer(
                f"✅ *Игра создана!*\n\n"
                f"*Название:* {data['name']}\n"
                f"*Код игры:* `{new_game.id}`\n"
                f"*Бюджет:* {data['price']}\n"
                f"*Создатель:* {message.from_user.full_name}\n\n"
                f"*Чтобы присоединиться, участники могут:*\n"
                f"1. Нажать кнопку ниже👇\n"
                f"2. Использовать команду `/join {new_game.id}`\n\n"
                f"*Когда все соберутся, запустите распределение командой:* /start_game",
                parse_mode="Markdown",
                reply_markup=invite_keyboard
            )
            
    except Exception as e:
        logger.error(f"Ошибка создания игры: {e}")
        await message.answer("❌ При создании игры произошла ошибка. Попробуйте еще раз.")
    finally:
        db.close()
        await state.finish()

# ============== СИНХРОННЫЕ FLASK РОУТЫ ==============
@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    """Основной обработчик вебхуков от Telegram"""
    try:
        update = types.Update(**request.get_json())
        
        # Получаем текущий event loop или создаем новый
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Создаем новую задачу в существующем loop
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Запускаем асинхронную функцию
        loop.run_until_complete(dp.process_update(bot=bot, update=update))
        return jsonify({'status': 'ok'})
            
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
