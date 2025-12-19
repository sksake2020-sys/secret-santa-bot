# webhook_app.py - ПРОСТОЙ РАБОЧИЙ ВЕБХУК
from flask import Flask, request, jsonify
import asyncio
import logging
import sys
import os
import queue
import threading
import time

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

# ============== ФОНОВЫЙ ОБРАБОТЧИК ==============
def background_worker():
    """Фоновый обработчик сообщений"""
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.fsm_storage.memory import MemoryStorage
    
    # Создаем бота
    worker_bot = Bot(token=BOT_TOKEN)
    Bot.set_current(worker_bot)
    worker_storage = MemoryStorage()
    worker_dp = Dispatcher(worker_bot, worker_storage)
    
    # ============== ОБРАБОТЧИКИ ==============
    @worker_dp.message_handler(commands=['start'])
    async def handle_start(message: types.Message):
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=f"🎅 Привет, {message.from_user.first_name}!\n\n"
                 "Я — бот для Тайного Санты.\n"
                 "Используй /help для списка команд."
        )
    
    @worker_dp.message_handler(commands=['help'])
    async def handle_help(message: types.Message):
        help_text = """
🎅 Помощь:
/start - начать
/help - помощь
/new_game - создать игру
/join [код] - присоединиться
/my_target - мой получатель
        """
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=help_text
        )
    
    @worker_dp.message_handler(commands=['new_game'])
    async def handle_new_game(message: types.Message):
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text="Создание игры... (в разработке)"
        )
    
    @worker_dp.message_handler(commands=['my_target'])
    async def handle_my_target(message: types.Message):
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text="Ваш получатель... (в разработке)"
        )
    
    @worker_dp.message_handler()
    async def handle_all_messages(message: types.Message):
        if message.text:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"Вы сказали: {message.text}\nИспользуйте /help"
            )
    
    # ============== ЗАПУСК ЦИКЛА ==============
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    logger.info("✅ Фоновый воркер запущен")
    
    try:
        while True:
            try:
                update_data = update_queue.get(timeout=1)
                update_id = update_data.get('update_id', 'unknown')
                
                try:
                    update = types.Update(**update_data)
                    loop.run_until_complete(worker_dp.process_update(update))
                    logger.info(f"✅ Обработано: {update_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка: {e}")
                
                update_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"❌ Ошибка воркера: {e}")
                time.sleep(2)
                
    except Exception as e:
        logger.error(f"❌ Воркер остановлен: {e}")
    finally:
        loop.close()
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
        
        # Добавляем в очередь
        update_queue.put(update_data)
        
        logger.info(f"📥 Получен: {update_id}")
        return jsonify({'status': 'ok', 'update_id': update_id})
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
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
        temp_bot = Bot(token=BOT_TOKEN)
        
        loop.run_until_complete(temp_bot.set_webhook(WEBHOOK_URL))
        loop.close()
        
        logger.info(f"✅ Вебхук установлен")
        return f"✅ Вебхук установлен!<br>{WEBHOOK_URL}"
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
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
    """Статус"""
    import datetime
    return jsonify({
        'status': 'online',
        'time': datetime.datetime.now().isoformat(),
        'queue': update_queue.qsize(),
        'worker': worker_thread.is_alive()
    })

# ============== ЗАПУСК ==============
if __name__ == '__main__':
    print("🚀 Бот запускается...")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
