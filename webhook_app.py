# webhook_app.py - ИСПРАВЛЕННЫЙ ВЕБХУК
from flask import Flask, request, jsonify
import asyncio
import logging
import sys
import os
import queue
import threading
import time
import aiohttp
import signal
import atexit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============== НАСТРОЙКИ ==============
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен!")

WEBHOOK_HOST = "https://web-production-1a5d8.up.railway.app"
WEBHOOK_PATH = f'/webhook/{BOT_TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

logger.info(f"BOT_TOKEN: {'установлен' if BOT_TOKEN else 'НЕТ'}")
logger.info(f"WEBHOOK_HOST: {WEBHOOK_HOST}")

# ============== ОЧЕРЕДЬ ==============
update_queue = queue.Queue()

# ============== ГЛОБАЛЬНЫЕ РЕСУРСЫ ==============
worker_running = True
bot_instance = None
dp_instance = None
event_loop = None

# ============== КОРРЕКТНОЕ ЗАВЕРШЕНИЕ ==============
def cleanup():
    """Корректное завершение всех ресурсов"""
    global worker_running

    logger.info("🔄 Начинаю cleanup...")
    worker_running = False  # Этот флаг остановит цикл воркера
    logger.info("✅ Флаг завершения установлен")
# ============== ФОНОВЫЙ ОБРАБОТЧИК ==============
def background_worker():
    """Фоновый обработчик сообщений"""
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.fsm_storage.memory import MemoryStorage
    
    global worker_running, bot_instance, dp_instance, event_loop
    
    # Создаем бота
    bot_instance = Bot(token=BOT_TOKEN)
    Bot.set_current(bot_instance)
    worker_storage = MemoryStorage()
    dp_instance = Dispatcher(bot_instance, worker_storage)
    
    # ============== ОБРАБОТЧИКИ ==============
    @dp_instance.message_handler(commands=['start'])
    async def handle_start(message: types.Message):
        await bot_instance.send_message(
            chat_id=message.chat.id,
            text=f"🎅 Привет, {message.from_user.first_name}!\n\n"
                 "Я — бот для Тайного Санты.\n"
                 "Используй /help для списка команд."
        )
    
    @dp_instance.message_handler(commands=['help'])
    async def handle_help(message: types.Message):
        help_text = """
🎅 Помощь:
/start - начать
/help - помощь
/new_game - создать игру
/join [код] - присоединиться
/my_target - мой получатель
        """
        await bot_instance.send_message(
            chat_id=message.chat.id,
            text=help_text
        )
    
    @dp_instance.message_handler(commands=['new_game'])
    async def handle_new_game(message: types.Message):
        await bot_instance.send_message(
            chat_id=message.chat.id,
            text="Создание игры... (в разработке)"
        )
    
    @dp_instance.message_handler(commands=['my_target'])
    async def handle_my_target(message: types.Message):
        await bot_instance.send_message(
            chat_id=message.chat.id,
            text="Ваш получатель... (в разработке)"
        )
    
    @dp_instance.message_handler()
    async def handle_all_messages(message: types.Message):
        if message.text:
            await bot_instance.send_message(
                chat_id=message.chat.id,
                text=f"Вы сказали: {message.text}\nИспользуйте /help"
            )
    
    # ============== ЗАПУСК ЦИКЛА ==============
    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)
    
    logger.info("✅ Фоновый воркер запущен")
    
    try:
        while worker_running:
            try:
                update_data = update_queue.get(timeout=1)
                update_id = update_data.get('update_id', 'unknown')
                
                try:
                    update = types.Update(**update_data)
                    event_loop.run_until_complete(dp_instance.process_update(update))
                    logger.info(f"✅ Обработано: {update_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка обработки: {e}")
                
                update_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"❌ Ошибка воркера: {e}")
                time.sleep(2)
                
    except Exception as e:
        logger.error(f"❌ Воркер остановлен: {e}")
    finally:
        # Корректное завершение
        try:
            if event_loop and not event_loop.is_closed():
                # Закрываем сессии внутри event loop
                event_loop.run_until_complete(bot_instance.session.close())
                event_loop.close()
                logger.info("✅ Event loop закрыт")
        except Exception as e:
            logger.error(f"❌ Ошибка при закрытии event loop: {e}")
        
        logger.info("✅ Воркер завершен")

# Запускаем фоновый поток
worker_thread = threading.Thread(target=background_worker, daemon=True)
worker_thread.start()
logger.info("✅ Фоновый поток запущен")

# ============== FLASK РОУТЫ ==============
@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    """Обработчик вебхуков"""
    try:
        update_data = request.get_json()
        update_id = update_data.get('update_id', 'unknown')
        
        # Проверяем, что воркер жив
        if not worker_thread.is_alive():
            logger.error("❌ Воркер не работает!")
            return jsonify({'status': 'worker_down'}), 500
        
        # Добавляем в очередь
        update_queue.put(update_data)
        
        logger.info(f"📥 Получен: {update_id}")
        return jsonify({'status': 'ok', 'update_id': update_id})
            
    except Exception as e:
        logger.error(f"❌ Ошибка вебхука: {e}")
        return jsonify({'status': 'error'}), 500

@app.route('/')
def index():
    return "🎅 Бот работает!<br><a href='/set_webhook'>Установить вебхук</a>"

@app.route('/set_webhook')
def set_webhook():
    """Установка вебхука"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        from aiogram import Bot
        
        # Используем контекстный менеджер для бота
        async def set_wh():
            async with Bot(token=BOT_TOKEN) as temp_bot:
                await temp_bot.set_webhook(WEBHOOK_URL)
        
        loop.run_until_complete(set_wh())
        loop.close()
        
        logger.info(f"✅ Вебхук установлен")
        return f"✅ Вебхук установлен!<br>{WEBHOOK_URL}"
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
        
        # Используем контекстный менеджер
        async def delete_wh():
            async with Bot(token=BOT_TOKEN) as temp_bot:
                await temp_bot.delete_webhook()
                await temp_bot.close()
        
        loop.run_until_complete(delete_wh())
        loop.close()
        
        return "✅ Вебхук удален!"
    except Exception as e:
        logger.error(f"❌ Ошибка удаления вебхука: {e}")
        return f"❌ Ошибка: {str(e)}"

@app.route('/status')
def status():
    """Статус"""
    import datetime
    return jsonify({
        'status': 'online',
        'time': datetime.datetime.now().isoformat(),
        'queue': update_queue.qsize(),
        'worker_alive': worker_thread.is_alive(),
        'worker_running': worker_running
    })

@app.route('/health')
def health():
    """Health check для Railway"""
    if worker_thread.is_alive():
        return jsonify({'status': 'healthy'}), 200
    else:
        return jsonify({'status': 'unhealthy'}), 500

# ============== ОБРАБОТЧИК СИГНАЛОВ ==============
def handle_shutdown(signum, frame):
    """Обработчик сигналов завершения"""
    logger.info(f"Получен сигнал {signum}, завершаю работу...")
    cleanup()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)

# ============== ЗАПУСК ==============
if __name__ == '__main__':
    print("🚀 Бот запускается...")
    
    # Регистрируем cleanup при выходе
    atexit.register(cleanup)
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
