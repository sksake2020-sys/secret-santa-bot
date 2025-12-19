# webhook_app.py - ПОЛНЫЙ РАБОЧИЙ КОД С ОЧЕРЕДЬЮ
from flask import Flask, request, jsonify
import asyncio
import logging
import sys
import os
import queue
import threading

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

# ============== ОЧЕРЕДЬ ДЛЯ ОБНОВЛЕНИЙ ==============
update_queue = queue.Queue()

# ============== ФОНОВЫЙ ОБРАБОТЧИК ==============
def background_worker():
    """Фоновый воркер, который обрабатывает обновления из очереди"""
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.fsm_storage.memory import MemoryStorage
    
    # Создаем бота для этого потока
    worker_bot = Bot(token=BOT_TOKEN)
    Bot.set_current(worker_bot)
    worker_storage = MemoryStorage()
    worker_dp = Dispatcher(worker_bot, worker_storage)
    
    # ============== ВАШИ ОБРАБОТЧИКИ КОМАНД ==============
    @worker_dp.message_handler(commands=['start'])
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
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=f"🎅 Привет, {message.from_user.first_name}! 👋\n\n"
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
    
    @worker_dp.message_handler(commands=['help'])
    async def handle_help(message: types.Message):
        """Обработчик команды /help"""
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
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=help_text,
            parse_mode="Markdown"
        )
    
    # Обработчики кнопок главного меню
    @worker_dp.message_handler(lambda message: message.text == "🎮 Создать игру")
    async def handle_create_game_button(message: types.Message):
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text="🎄 *Давайте создадим новую игру Тайного Санты!*\n\n"
                 "Введите *название* для вашей игры (например, 'Корпоратив 2024' или 'Семейный Новый Год'):",
            parse_mode="Markdown",
            reply_markup=types.ReplyKeyboardRemove()
        )
    
    @worker_dp.message_handler(lambda message: message.text == "🎅 Присоединиться")
    async def handle_join_button(message: types.Message):
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text="Для присоединения к игре:\n"
                 "1. Получите код игры от друга\n"
                 "2. Используйте команду /join <код>\n\n"
                 "Или нажмите на кнопку-приглашение, которую вам отправили.",
            reply_markup=types.ReplyKeyboardRemove()
        )
    
    @worker_dp.message_handler(lambda message: message.text == "❓ Помощь")
    async def handle_help_button(message: types.Message):
        await handle_help(message)
    
    @worker_dp.message_handler(lambda message: message.text == "📋 Мои игры")
    async def handle_my_games_button(message: types.Message):
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text="Функция 'Мои игры' в разработке...\n"
                 "Скоро здесь будет список ваших игр!",
            reply_markup=types.ReplyKeyboardRemove()
        )
    
    # Обработчик всех остальных сообщений
    @worker_dp.message_handler()
    async def handle_all_messages(message: types.Message):
        if message.text and not message.text.startswith('/'):
            # Проверяем, может это пожелания участника
            from database import SessionLocal, Participant, Game
            
            db = SessionLocal()
            try:
                participant = db.query(Participant).join(Game).filter(
                    Participant.user_id == message.from_user.id,
                    Participant.wishlist.is_(None),
                    Game.is_active == True,
                    Game.is_started == False
                ).first()
                
                if participant:
                    participant.wishlist = message.text
                    db.commit()
                    await worker_bot.send_message(
                        chat_id=message.chat.id,
                        text="✅ Ваши пожелания сохранены! Спасибо.\n\n"
                             "Теперь дождитесь, пока создатель игры запустит распределение."
                    )
                else:
                    await worker_bot.send_message(
                        chat_id=message.chat.id,
                        text=f"Вы сказали: {message.text}\n\nИспользуйте /help для списка команд."
                    )
            except Exception as e:
                logger.error(f"Ошибка обработки сообщения: {e}")
                await worker_bot.send_message(
                    chat_id=message.chat.id,
                    text=f"Вы сказали: {message.text}\n\nИспользуйте /help для списка команд."
                )
            finally:
                db.close()
        else:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"Команда {message.text} в разработке. Используйте /help"
            )
    
    # ============== ОБРАБОТКА CALLBACK-QUERY (инлайн кнопок) ==============
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    @worker_dp.callback_query_handler(lambda c: c.data.startswith('join_game_'))
    async def process_join_game(callback_query: types.CallbackQuery):
        """Обработчик присоединения по инлайн-кнопке"""
        from database import SessionLocal, Game, Participant
        
        try:
            game_id = int(callback_query.data.split('_')[2])
            db = SessionLocal()
            
            game = db.query(Game).filter(Game.id == game_id, Game.is_active == True).first()
            
            if not game:
                await worker_bot.answer_callback_query(
                    callback_query.id,
                    "Игра не найдена или уже завершена!",
                    show_alert=True
                )
                return
            
            if game.is_started:
                await worker_bot.answer_callback_query(
                    callback_query.id,
                    "Игра уже началась, присоединиться нельзя!",
                    show_alert=True
                )
                return
            
            # Проверяем, не участвует ли уже
            existing = db.query(Participant).filter(
                Participant.game_id == game_id,
                Participant.user_id == callback_query.from_user.id
            ).first()
            
            if existing:
                await worker_bot.answer_callback_query(
                    callback_query.id,
                    "Вы уже в игре!",
                    show_alert=True
                )
                return
            
            # Добавляем участника
            new_participant = Participant(
                game_id=game_id,
                user_id=callback_query.from_user.id,
                username=callback_query.from_user.username,
                full_name=callback_query.from_user.full_name
            )
            db.add(new_participant)
            db.commit()
            
            await worker_bot.answer_callback_query(
                callback_query.id,
                f"Вы присоединились к игре '{game.name}'!",
                show_alert=True
            )
            
            # Просим указать пожелания
            await worker_bot.send_message(
                callback_query.from_user.id,
                f"🎉 Вы присоединились к игре *«{game.name}»*!\n\n"
                f"*Создатель:* {game.admin_username or 'Неизвестно'}\n"
                f"*Бюджет:* {game.gift_price}\n\n"
                f"📝 Пожалуйста, напишите *ваши пожелания* к подарку.\n"
                f"Что вам нравится? (Это поможет вашему Тайному Санте)",
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Ошибка присоединения: {e}")
            await worker_bot.answer_callback_query(
                callback_query.id,
                "Произошла ошибка!",
                show_alert=True
            )
        finally:
            try:
                db.close()
            except:
                pass
    
    # Event loop для этого потока
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    logger.info("✅ Фоновый воркер запущен")
    
    # Бесконечный цикл обработки очереди
    while True:
        try:
            update_data = update_queue.get(timeout=1)
            update_id = update_data.get('update_id', 'unknown')
            
            try:
                update = types.Update(**update_data)
                loop.run_until_complete(worker_dp.process_update(update))
                logger.info(f"✅ Обработано update: {update_id}")
            except Exception as e:
                logger.error(f"❌ Ошибка обработки update {update_id}: {e}")
            
            update_queue.task_done()
            
        except queue.Empty:
            continue  # Очередь пуста, ждем дальше
        except Exception as e:
            logger.error(f"❌ Критическая ошибка воркера: {e}")
            import time
            time.sleep(5)  # Пауза перед повторной попыткой

# Запускаем фоновый воркер
worker_thread = threading.Thread(target=background_worker, daemon=True)
worker_thread.start()
logger.info("✅ Фоновый поток запущен")

# ============== FLASK РОУТЫ ==============
@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    """Основной обработчик вебхуков - только добавляет в очередь"""
    try:
        update_data = request.get_json()
        update_id = update_data.get('update_id', 'unknown')
        
        # Просто добавляем в очередь
        update_queue.put(update_data)
        
        logger.info(f"📥 Update {update_id} добавлен в очередь")
        return jsonify({'status': 'queued', 'update_id': update_id})
            
    except Exception as e:
        logger.error(f"❌ Ошибка в webhook: {e}")
        return jsonify({'status': 'error'}), 500

@app.route('/')
def index():
    return "🎅 Бот 'Тайный Санта' работает на Railway!<br>Статус: ONLINE<br><a href='/set_webhook'>Установить вебхук</a>"

@app.route('/set_webhook')
def set_webhook():
    """Установка вебхука"""
    try:
        # Создаем временный event loop для установки вебхука
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        from aiogram import Bot
        temp_bot = Bot(token=BOT_TOKEN)
        
        loop.run_until_complete(temp_bot.set_webhook(WEBHOOK_URL))
        loop.close()
        
        logger.info(f"✅ Вебхук установлен: {WEBHOOK_URL}")
        return f"✅ Вебхук установлен!<br>URL: {WEBHOOK_URL}"
    except Exception as e:
        logger.error(f"❌ Ошибка установки вебхука: {e}")
        return f"❌ Ошибка: {str(e)}"

@app.route('/delete_webhook')
def delete_webhook():
    """Удаление вебхука"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        from aiogram import Bot
        temp_bot = Bot(token=BOT_TOKEN)
        
        loop.run_until_complete(temp_bot.delete_webhook())
        loop.close()
        
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
        'queue_size': update_queue.qsize(),
        'background_worker': worker_thread.is_alive()
    })

# ============== ТЕСТОВЫЕ РОУТЫ ==============
@app.route('/test')
def test():
    """Тестовая страница"""
    return "Бот работает! 🎅"

@app.route('/db-test')
def db_test():
    """Тест базы данных"""
    try:
        from database import SessionLocal
        db = SessionLocal()
        result = db.execute("SELECT 1 as test").fetchone()
        db.close()
        return f"✅ База данных работает: {result[0]}"
    except Exception as e:
        return f"❌ Ошибка БД: {str(e)}"

# ============== ЗАПУСК ПРИЛОЖЕНИЯ ==============
if __name__ == '__main__':
    print("🚀 Запуск Flask приложения...")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
