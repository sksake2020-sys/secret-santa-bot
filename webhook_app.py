# webhook_app.py - ТАЙНЫЙ САНТА
from flask import Flask, request, jsonify
import asyncio
import logging
import sys
import os
import queue
import threading
import time
import random
import string
from datetime import datetime
import json
from collections import defaultdict

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

# ============== ХРАНИЛИЩЕ ДАННЫХ ==============
# В production замените на базу данных (SQLite/PostgreSQL)
games_db = {}  # game_code -> game_data
users_db = {}  # user_id -> user_data
waiting_games = {}  # game_code -> timestamp (для очистки)

# Структура game_data:
# {
#     'code': 'ABC123',
#     'creator_id': 123456789,
#     'creator_name': 'Иван',
#     'status': 'waiting',  # waiting, started, finished
#     'participants': [user_id1, user_id2, ...],
#     'wishlist': {user_id: "Хочу книгу", ...},
#     'pairs': {santa_id: receiver_id, ...},  # после жеребьевки
#     'max_price': None,
#     'created_at': timestamp,
#     'started_at': None,
#     'location': None
# }

class GameManager:
    @staticmethod
    def generate_code():
        """Генерация кода игры (6 символов)"""
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    
    @staticmethod
    def create_game(creator_id, creator_name, max_price=None, location=None):
        """Создание новой игры"""
        code = GameManager.generate_code()
        while code in games_db:
            code = GameManager.generate_code()
        
        game = {
            'code': code,
            'creator_id': creator_id,
            'creator_name': creator_name,
            'status': 'waiting',
            'participants': [creator_id],
            'wishlist': {},
            'pairs': {},
            'max_price': max_price,
            'created_at': datetime.now().isoformat(),
            'started_at': None,
            'location': location
        }
        
        games_db[code] = game
        waiting_games[code] = time.time()
        
        # Сохраняем игру для создателя
        if creator_id not in users_db:
            users_db[creator_id] = {'games': [], 'current_game': None}
        users_db[creator_id]['current_game'] = code
        
        return game
    
    @staticmethod
    def join_game(user_id, user_name, code):
        """Присоединение к игре"""
        code = code.upper()
        if code not in games_db:
            return None, "Игра не найдена"
        
        game = games_db[code]
        
        if game['status'] != 'waiting':
            return None, "Игра уже началась"
        
        if user_id in game['participants']:
            return None, "Вы уже в игре"
        
        if len(game['participants']) >= 50:  # Лимит участников
            return None, "Достигнут лимит участников"
        
        game['participants'].append(user_id)
        
        # Сохраняем игру для участника
        if user_id not in users_db:
            users_db[user_id] = {'games': [], 'current_game': None}
        users_db[user_id]['current_game'] = code
        
        # Обновляем timestamp ожидания
        waiting_games[code] = time.time()
        
        return game, "Успешно присоединились"
    
    @staticmethod
    def start_game(code, creator_id):
        """Начало игры (жеребьевка)"""
        code = code.upper()
        if code not in games_db:
            return False, "Игра не найдена"
        
        game = games_db[code]
        
        if game['creator_id'] != creator_id:
            return False, "Только создатель может начать игру"
        
        if game['status'] != 'waiting':
            return False, "Игра уже началась"
        
        if len(game['participants']) < 2:
            return False, "Нужно минимум 3 участника"
        
        # Жеребьевка
        participants = game['participants'].copy()
        random.shuffle(participants)
        
        pairs = {}
        for i in range(len(participants)):
            santa = participants[i]
            receiver = participants[(i + 1) % len(participants)]
            pairs[santa] = receiver
        
        game['pairs'] = pairs
        game['status'] = 'started'
        game['started_at'] = datetime.now().isoformat()
        
        # Удаляем из ожидания
        if code in waiting_games:
            del waiting_games[code]
        
        return True, "Игра началась! Пары распределены."
    
    @staticmethod
    def get_my_target(user_id):
        """Получение цели для Санты"""
        if user_id not in users_db:
            return None, "Вы не участвуете в играх"
        
        current_game = users_db[user_id].get('current_game')
        if not current_game or current_game not in games_db:
            return None, "Вы не в активной игре"
        
        game = games_db[current_game]
        if game['status'] != 'started':
            return None, "Игра еще не началась"
        
        if user_id not in game['pairs']:
            return None, "Ошибка: вы не в парах"
        
        target_id = game['pairs'][user_id]
        
        # Получаем информацию о цели
        target_info = game['wishlist'].get(target_id, "Пожелания не указаны")
        
        return target_id, target_info
    
    @staticmethod
    def set_wishlist(user_id, wish):
        """Установка пожеланий"""
        if user_id not in users_db:
            return False, "Вы не участвуете в играх"
        
        current_game = users_db[user_id].get('current_game')
        if not current_game or current_game not in games_db:
            return False, "Вы не в активной игре"
        
        game = games_db[current_game]
        game['wishlist'][user_id] = wish
        
        return True, "Пожелания сохранены"
    
    @staticmethod
    def get_game_info(code):
        """Получение информации об игре"""
        code = code.upper()
        if code not in games_db:
            return None
        
        game = games_db[code].copy()
        # Не показываем пары и пожелания в общем доступе
        if 'pairs' in game:
            del game['pairs']
        if 'wishlist' in game:
            game['wishlist'] = list(game['wishlist'].keys())  # Только ID
        
        return game
    
    @staticmethod
    def cleanup_old_games():
        """Очистка старых неактивных игр (раз в час)"""
        current_time = time.time()
        codes_to_remove = []
        
        for code, timestamp in waiting_games.items():
            if current_time - timestamp > 24 * 3600:  # 24 часа
                codes_to_remove.append(code)
        
        for code in codes_to_remove:
            if code in games_db and games_db[code]['status'] == 'waiting':
                del games_db[code]
            if code in waiting_games:
                del waiting_games[code]
            logger.info(f"Удалена старая игра: {code}")

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
                 "Я — бот для Тайного Санты.\n\n"
                 "🎮 Основные команды:\n"
                 "/new_game - создать новую игру\n"
                 "/join [код] - присоединиться к игре\n"
                 "/my_game - информация о текущей игре\n"
                 "/wish [текст] - указать пожелания для подарка\n"
                 "/start_game - начать игру (для создателя)\n"
                 "/my_target - кто мой получатель подарка?\n"
                 "/help - полная помощь\n"
                 "/leave_game - выйти из текущей игры"
        )
    
    @worker_dp.message_handler(commands=['help'])
    async def handle_help(message: types.Message):
        help_text = """
🎅 *ТАЙНЫЙ САНТА - ПОМОЩЬ*

🎮 *Управление играми:*
/new_game - создать новую игру
/join [КОД] - присоединиться к игре по коду
/my_game - информация о текущей игре
/start_game - начать игру (только создатель)
/leave_game - выйти из игры

🎁 *Подарки:*
/wish [текст] - указать пожелания для подарка
/my_target - узнать, кому вы дарите подарок

📊 *Информация:*
/players - список участников текущей игры
/games - список ваших игр
/status - статус бота

🔧 *Техническое:*
/set_webhook - установить вебхук (админам)
/delete_webhook - удалить вебхук

💡 *Примеры:*
`/join ABC123` - присоединиться к игре ABC123
`/wish Хочу новую книгу фэнтези` - указать пожелания
        """
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=help_text,
            parse_mode='Markdown'
        )
    
    @worker_dp.message_handler(commands=['new_game'])
    async def handle_new_game(message: types.Message):
        user_id = message.from_user.id
        user_name = message.from_user.first_name
        
        # Очистка старых игр
        GameManager.cleanup_old_games()
        
        # Создаем игру
        game = GameManager.create_game(user_id, user_name)
        
        response = (
            f"🎮 *Игра создана!*\n\n"
            f"📋 Код игры: `{game['code']}`\n"
            f"👑 Создатель: {user_name}\n"
            f"👥 Участников: 1\n"
            f"📌 Статус: Ожидание игроков\n\n"
            f"*Отправьте этот код друзьям:*\n"
            f"`{game['code']}`\n\n"
            f"Для присоединения нужно отправить:\n"
            f"`/join {game['code']}`\n\n"
            f"Когда все присоединятся, нажмите /start_game"
        )
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode='Markdown'
        )
    
    @worker_dp.message_handler(commands=['join'])
    async def handle_join(message: types.Message):
        text = message.text.strip()
        parts = text.split()
        
        if len(parts) < 2:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Укажите код игры:\n`/join ABC123`",
                parse_mode='Markdown'
            )
            return
        
        code = parts[1]
        user_id = message.from_user.id
        user_name = message.from_user.first_name
        
        game, result = GameManager.join_game(user_id, user_name, code)
        
        if game:
            response = (
                f"✅ *Вы присоединились к игре!*\n\n"
                f"📋 Код игры: `{game['code']}`\n"
                f"👑 Создатель: {game['creator_name']}\n"
                f"👥 Участников: {len(game['participants'])}\n"
                f"📌 Статус: {game['status']}\n\n"
                f"Используйте /wish чтобы указать пожелания.\n"
                f"Создатель запустит игру командой /start_game"
            )
        else:
            response = f"❌ {result}"
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode='Markdown'
        )
    
    @worker_dp.message_handler(commands=['my_game'])
    async def handle_my_game(message: types.Message):
        user_id = message.from_user.id
        
        if user_id not in users_db or not users_db[user_id].get('current_game'):
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Вы не участвуете в игре.\nСоздайте новую /new_game или присоединитесь /join"
            )
            return
        
        game_code = users_db[user_id]['current_game']
        game = games_db.get(game_code)
        
        if not game:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Игра не найдена"
            )
            return
        
        participants_count = len(game['participants'])
        status_text = {
            'waiting': '⏳ Ожидание игроков',
            'started': '🎮 Игра началась',
            'finished': '🏁 Игра завершена'
        }.get(game['status'], game['status'])
        
        is_creator = game['creator_id'] == user_id
        
        response = (
            f"🎮 *Ваша игра*\n\n"
            f"📋 Код: `{game['code']}`\n"
            f"👑 Создатель: {game['creator_name']}\n"
            f"👥 Участников: {participants_count}\n"
            f"📌 Статус: {status_text}\n"
            f"📅 Создана: {game['created_at'][:10]}\n"
        )
        
        if game['max_price']:
            response += f"💰 Лимит цены: {game['max_price']} руб.\n"
        
        if game['location']:
            response += f"📍 Локация: {game['location']}\n"
        
        response += "\n"
        
        if game['status'] == 'waiting':
            response += f"*Пригласите друзей:*\n`{game['code']}`\n\n"
            if is_creator:
                if participants_count >= 3:
                    response += "✅ Можно начинать игру: /start_game\n"
                else:
                    response += f"❌ Нужно еще {3 - participants_count} игрока\n"
            else:
                response += "Ожидайте начала игры от создателя.\n"
        
        elif game['status'] == 'started':
            response += "🎁 Игра началась! Узнайте своего получателя: /my_target\n"
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode='Markdown'
        )
    
    @worker_dp.message_handler(commands=['start_game'])
    async def handle_start_game(message: types.Message):
        user_id = message.from_user.id
        
        if user_id not in users_db or not users_db[user_id].get('current_game'):
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Вы не участвуете в игре"
            )
            return
        
        game_code = users_db[user_id]['current_game']
        success, result = GameManager.start_game(game_code, user_id)
        
        if success:
            # Получаем обновленную игру
            game = games_db[game_code]
            
            # Отправляем сообщение каждому участнику
            for participant_id in game['participants']:
                target_id, target_info = GameManager.get_my_target(participant_id)
                
                if target_id:
                    try:
                        # Получаем имя получателя
                        await worker_bot.send_message(
                            chat_id=participant_id,
                            text=(
                                f"🎉 *Игра началась!*\n\n"
                                f"Вы — Тайный Санта для:\n"
                                f"👤 *{target_id}*\n\n"
                                f"🎁 *Пожелания получателя:*\n"
                                f"{target_info}\n\n"
                                f"Хорошей игры! 🎅"
                            ),
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logger.error(f"Не удалось отправить сообщение {participant_id}: {e}")
            
            # Отправляем создателю общее сообщение
            await worker_bot.send_message(
                chat_id=user_id,
                text=(
                    f"✅ *Игра началась!*\n\n"
                    f"Все участники получили свои цели.\n"
                    f"👥 Участников: {len(game['participants'])}\n\n"
                    f"Проверить своего получателя: /my_target"
                ),
                parse_mode='Markdown'
            )
        else:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"❌ {result}"
            )
    
    @worker_dp.message_handler(commands=['my_target'])
    async def handle_my_target(message: types.Message):
        user_id = message.from_user.id
        
        target_id, target_info = GameManager.get_my_target(user_id)
        
        if target_id:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=(
                    f"🎅 *Ваш получатель:*\n\n"
                    f"👤 ID: `{target_id}`\n\n"
                    f"🎁 *Пожелания:*\n"
                    f"{target_info}\n\n"
                    f"Удачи в выборе подарка! 🎄"
                ),
                parse_mode='Markdown'
            )
        else:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"❌ {target_info}"
            )
    
    @worker_dp.message_handler(commands=['wish'])
    async def handle_wish(message: types.Message):
        text = message.text.strip()
        
        if len(text) < 6:  # "/wish" + минимум 1 символ
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Укажите ваши пожелания:\n`/wish Хочу новую книгу`",
                parse_mode='Markdown'
            )
            return
        
        wish = text[6:].strip()  # Убираем "/wish "
        user_id = message.from_user.id
        
        success, result = GameManager.set_wishlist(user_id, wish)
        
        if success:
            response = f"✅ *Пожелания сохранены!*\n\n{wish}"
        else:
            response = f"❌ {result}"
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode='Markdown'
        )
    
    @worker_dp.message_handler(commands=['players'])
    async def handle_players(message: types.Message):
        user_id = message.from_user.id
        
        if user_id not in users_db or not users_db[user_id].get('current_game'):
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Вы не участвуете в игре"
            )
            return
        
        game_code = users_db[user_id]['current_game']
        game = games_db.get(game_code)
        
        if not game:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Игра не найдена"
            )
            return
        
        participants_text = f"👥 *Участники ({len(game['participants'])}):*\n\n"
        
        for i, participant_id in enumerate(game['participants'], 1):
            is_creator = participant_id == game['creator_id']
            creator_mark = " 👑" if is_creator else ""
            
            # Проверяем есть ли пожелания
            has_wish = participant_id in game['wishlist']
            wish_mark = " 📝" if has_wish else ""
            
            participants_text += f"{i}. `{participant_id}`{creator_mark}{wish_mark}\n"
        
        participants_text += "\n"
        participants_text += f"📝 - указал пожелания\n"
        participants_text += f"👑 - создатель игры\n\n"
        
        if game['status'] == 'waiting':
            participants_text += f"*Пригласительный код:*\n`{game['code']}`"
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=participants_text,
            parse_mode='Markdown'
        )
    
    @worker_dp.message_handler(commands=['leave_game'])
    async def handle_leave_game(message: types.Message):
        user_id = message.from_user.id
        
        if user_id not in users_db or not users_db[user_id].get('current_game'):
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Вы не участвуете в игре"
            )
            return
        
        game_code = users_db[user_id]['current_game']
        game = games_db.get(game_code)
        
        if not game:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Игра не найдена"
            )
            return
        
        # Если создатель выходит - удаляем игру
        if game['creator_id'] == user_id:
            del games_db[game_code]
            if game_code in waiting_games:
                del waiting_games[game_code]
            
            # Уведомляем участников
            for participant_id in game['participants']:
                if participant_id != user_id:
                    try:
                        await worker_bot.send_message(
                            chat_id=participant_id,
                            text="❌ Игра удалена создателем"
                        )
                    except:
                        pass
            
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="✅ Игра удалена (вы были создателем)"
            )
        else:
            # Удаляем участника
            if user_id in game['participants']:
                game['participants'].remove(user_id)
            
            if user_id in game['wishlist']:
                del game['wishlist'][user_id]
            
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="✅ Вы вышли из игры"
            )
        
        # Очищаем текущую игру у пользователя
        users_db[user_id]['current_game'] = None
    
    @worker_dp.message_handler(commands=['games'])
    async def handle_games(message: types.Message):
        user_id = message.from_user.id
        
        if user_id not in users_db:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Вы не участвуете в играх"
            )
            return
        
        # Ищем игры где пользователь участник
        user_games = []
        for code, game in games_db.items():
            if user_id in game['participants']:
                user_games.append(game)
        
        if not user_games:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Вы не участвуете в играх"
            )
            return
        
        response = "🎮 *Ваши игры:*\n\n"
        
        for game in user_games[:10]:  # Ограничим 10 играми
            status_emoji = {
                'waiting': '⏳',
                'started': '🎮',
                'finished': '🏁'
            }.get(game['status'], '❓')
            
            response += (
                f"{status_emoji} *{game['code']}* - {game['status']}\n"
                f"   👥 {len(game['participants'])} участников\n"
                f"   👑 Создатель: {game['creator_name']}\n"
                f"   📅 {game['created_at'][:10]}\n\n"
            )
        
        if len(user_games) > 10:
            response += f"... и еще {len(user_games) - 10} игр\n\n"
        
        response += "Перейти к игре: /my_game"
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode='Markdown'
        )
    
    @worker_dp.message_handler(commands=['status'])
    async def handle_status(message: types.Message):
        active_games = sum(1 for g in games_db.values() if g['status'] == 'started')
        waiting_games_count = sum(1 for g in games_db.values() if g['status'] == 'waiting')
        total_users = len(users_db)
        
        response = (
            f"📊 *Статус бота:*\n\n"
            f"🎮 Активных игр: {active_games}\n"
            f"⏳ Ожидающих игр: {waiting_games_count}\n"
            f"👤 Всего пользователей: {total_users}\n"
            f"📝 Игр в базе: {len(games_db)}\n\n"
            f"🔄 Очередь сообщений: {update_queue.qsize()}\n"
            f"⚙️ Воркер: {'✅ работает' if worker_thread.is_alive() else '❌ остановлен'}\n\n"
            f"*Команды:* /help"
        )
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode='Markdown'
        )
    
    @worker_dp.message_handler()
    async def handle_all_messages(message: types.Message):
        if message.text:
            # Если сообщение похоже на код игры (6 символов, буквы+цифры)
            text = message.text.strip().upper()
            if len(text) == 6 and all(c.isalnum() for c in text):
                await worker_bot.send_message(
                    chat_id=message.chat.id,
                    text=(
                        f"🔍 Обнаружен код игры: `{text}`\n\n"
                        f"Присоединиться:\n"
                        f"`/join {text}`\n\n"
                        f"Или используйте /help для других команд"
                    ),
                    parse_mode='Markdown'
                )
            else:
                await worker_bot.send_message(
                    chat_id=message.chat.id,
                    text=(
                        f"👋 Я бот для Тайного Санты!\n\n"
                        f"Вы сказали: *{message.text}*\n\n"
                        f"Используйте /help для списка команд"
                    ),
                    parse_mode='Markdown'
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
    return """
    🎅 Тайный Санта Бот работает!<br>
    <a href='/set_webhook'>Установить вебхук</a><br>
    <a href='/status'>Статус бота</a><br>
    <a href='/stats'>Статистика</a>
    """

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
        'worker': worker_thread.is_alive(),
        'total_games': len(games_db),
        'active_games': sum(1 for g in games_db.values() if g['status'] == 'started'),
        'waiting_games': sum(1 for g in games_db.values() if g['status'] == 'waiting'),
        'total_users': len(users_db)
    })

@app.route('/stats')
def stats():
    """Страница статистики"""
    active_games = sum(1 for g in games_db.values() if g['status'] == 'started')
    waiting_games_count = sum(1 for g in games_db.values() if g['status'] == 'waiting')
    
    return f"""
    <h1>🎅 Статистика Тайного Санты</h1>
    <p>Всего игр: {len(games_db)}</p>
    <p>Активных игр: {active_games}</p>
    <p>Ожидающих игр: {waiting_games_count}</p>
    <p>Зарегистрированных пользователей: {len(users_db)}</p>
    <p>Сообщений в очереди: {update_queue.qsize()}</p>
    <p>Воркер работает: {'✅' if worker_thread.is_alive() else '❌'}</p>
    <p><a href='/'>На главную</a></p>
    """

@app.route('/api/games', methods=['GET'])
def api_games():
    """API для получения списка игр (только для отладки)"""
    return jsonify({
        'games': len(games_db),
        'waiting': waiting_games
    })

# ============== ЗАПУСК ==============
if __name__ == '__main__':
    print("🚀 Бот Тайный Санта запускается...")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
