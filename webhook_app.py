# webhook_app.py - ИСПРАВЛЕННАЯ ВЕРСИЯ С ПРОСТЫМ СОЗДАНИЕМ ИГРЫ
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============== НАСТРОЙКИ ДЛЯ RAILWAY ==============
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен! Добавьте его в Railway Variables.")

RAILWAY_STATIC_URL = os.environ.get('RAILWAY_STATIC_URL')
if RAILWAY_STATIC_URL:
    WEBHOOK_HOST = RAILWAY_STATIC_URL
else:
    WEBHOOK_HOST = "https://web-production-1a5d8.up.railway.app"

if not WEBHOOK_HOST.startswith('http'):
    WEBHOOK_HOST = f"https://{WEBHOOK_HOST}"

WEBHOOK_PATH = f'/webhook/{BOT_TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

logger.info(f"BOT_TOKEN: {'установлен' if BOT_TOKEN else 'НЕ установлен'}")
logger.info(f"WEBHOOK_HOST: {WEBHOOK_HOST}")

# ============== ХРАНИЛИЩЕ ДАННЫХ ==============
games_db = {}        # {game_id: game_data}
players_db = {}      # {user_id: player_data}
game_participants = {}  # {game_id: [user_id1, user_id2]}
user_games = {}      # {user_id: [game_id1, game_id2]}

class GameManager:
    @staticmethod
    def generate_game_id():
        """Генерация 8-символьного кода игры"""
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    
    @staticmethod
    def create_game(creator_id, creator_name, game_name=None):
        """Создание новой игры"""
        game_id = GameManager.generate_game_id()
        
        if not game_name:
            game_name = f"Игра {game_id}"
        
        game_data = {
            'id': game_id,
            'name': game_name,
            'creator_id': creator_id,
            'creator_name': creator_name,
            'budget': "Не ограничен",
            'status': 'waiting',  # waiting, active, finished
            'created_at': datetime.now().isoformat(),
            'started_at': None,
            'participants': [creator_id],
            'wishlists': {},
            'pairs': {}
        }
        
        games_db[game_id] = game_data
        game_participants[game_id] = [creator_id]
        
        if creator_id not in user_games:
            user_games[creator_id] = []
        user_games[creator_id].append(game_id)
        
        if creator_id not in players_db:
            players_db[creator_id] = {
                'username': creator_name,
                'games': [],
                'current_game': game_id
            }
        players_db[creator_id]['current_game'] = game_id
        
        return game_data
    
    @staticmethod
    def join_game(game_id, user_id, username):
        """Присоединение к игре"""
        if game_id not in games_db:
            return False, "Игра не найдена"
        
        game = games_db[game_id]
        
        if game['status'] != 'waiting':
            return False, "Игра уже началась или завершена"
        
        if user_id in game['participants']:
            return False, "Вы уже в этой игре"
        
        # Добавляем участника
        game['participants'].append(user_id)
        game_participants[game_id].append(user_id)
        
        # Добавляем в список игр пользователя
        if user_id not in user_games:
            user_games[user_id] = []
        if game_id not in user_games[user_id]:
            user_games[user_id].append(game_id)
        
        # Сохраняем данные игрока
        if user_id not in players_db:
            players_db[user_id] = {
                'username': username,
                'games': [],
                'current_game': game_id
            }
        players_db[user_id]['current_game'] = game_id
        
        return True, "Вы успешно присоединились к игре"
    
    @staticmethod
    def start_game(game_id, creator_id):
        """Начало игры (жеребьевка)"""
        if game_id not in games_db:
            return False, "Игра не найдена"
        
        game = games_db[game_id]
        
        if game['creator_id'] != creator_id:
            return False, "Только создатель может начать игру"
        
        if game['status'] != 'waiting':
            return False, "Игра уже началась"
        
        if len(game['participants']) < 2:
            return False, "Нужно минимум 2 участника"
        
        # Жеребьевка
        participants = game['participants'].copy()
        random.shuffle(participants)
        
        pairs = {}
        for i in range(len(participants)):
            santa = participants[i]
            receiver = participants[(i + 1) % len(participants)]
            pairs[santa] = receiver
        
        game['pairs'] = pairs
        game['status'] = 'active'
        game['started_at'] = datetime.now().isoformat()
        
        return True, "Игра началась! Пары распределены."
    
    @staticmethod
    def set_wishlist(user_id, wishlist_text):
        """Установка пожеланий"""
        if user_id not in players_db:
            return False, "Вы не участвуете в играх"
        
        current_game = players_db[user_id].get('current_game')
        if not current_game or current_game not in games_db:
            return False, "Вы не в активной игре"
        
        game = games_db[current_game]
        if game['status'] == 'active':
            return False, "Игра уже началась, нельзя изменить пожелания"
        
        game['wishlists'][user_id] = wishlist_text
        return True, "Пожелания сохранены!"
    
    @staticmethod
    def get_my_target(user_id):
        """Получение цели для Санты"""
        if user_id not in players_db:
            return None, "Вы не участвуете в играх"
        
        current_game = players_db[user_id].get('current_game')
        if not current_game or current_game not in games_db:
            return None, "Вы не в активной игре"
        
        game = games_db[current_game]
        if game['status'] != 'active':
            return None, "Игра еще не началась"
        
        if user_id not in game['pairs']:
            return None, "Вы не участвуете в этой игре"
        
        target_id = game['pairs'][user_id]
        target_wishlist = game['wishlists'].get(target_id, "Пожелания не указаны")
        target_name = players_db.get(target_id, {}).get('username', 'Неизвестный игрок')
        
        return {
            'id': target_id,
            'name': target_name,
            'wishlist': target_wishlist
        }, "Найдено"
    
    @staticmethod
    def get_game_info(game_id):
        """Получение информации об игре"""
        if game_id not in games_db:
            return None
        
        game = games_db[game_id].copy()
        # Скрываем пары для общего просмотра
        if 'pairs' in game:
            del game['pairs']
        
        # Добавляем информацию об участниках
        participants_info = []
        for user_id in game['participants']:
            user_info = players_db.get(user_id, {})
            participants_info.append({
                'id': user_id,
                'name': user_info.get('username', 'Неизвестно'),
                'has_wishlist': user_id in game['wishlists']
            })
        
        game['participants_info'] = participants_info
        return game

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
    
    # ============== ОБРАБОТЧИКИ КОМАНД ==============
    @worker_dp.message_handler(commands=['start', 'help'])
    async def handle_start(message: types.Message):
        """Обработчик команд /start и /help"""
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.row(
            types.KeyboardButton("🎮 Создать игру"),
            types.KeyboardButton("🎅 Присоединиться")
        )
        keyboard.row(
            types.KeyboardButton("❓ Помощь"),
            types.KeyboardButton("📋 Мои игры")
        )
        
        if message.text == '/help':
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=(
                    "🎅 *ТАЙНЫЙ САНТА - ПОМОЩЬ*\n\n"
                    "*Основные команды:*\n"
                    "/start - начать работу\n"
                    "/help - помощь\n"
                    "/newgame - создать игру\n"
                    "/join [код] - присоединиться\n"
                    "/startgame - начать игру\n"
                    "/mytarget - мой получатель\n"
                    "/wish [текст] - указать пожелания\n"
                    "/status - статус бота\n\n"
                    "*Пример:*\n"
                    "1. /newgame\n"
                    "2. /join [код]\n"
                    "3. Укажите пожелания\n"
                    "4. /startgame\n"
                    "5. /mytarget"
                ),
                parse_mode="Markdown"
            )
        else:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"🎅 Привет, {message.from_user.first_name}! 👋\n\n"
                     "Я — бот для игры *Тайный Санта*.\n\n"
                     "✨ *Что я умею:*\n"
                     "• Создавать игры\n"
                     "• Распределять пары Сант\n"
                     "• Хранить пожелания\n\n"
                     "🎯 *Начать игру:*\n"
                     "1. Нажми *«Создать игру»*\n"
                     "2. Пригласи друзей кодом\n"
                     "3. Укажите пожелания\n"
                     "4. Нажми /startgame\n\n"
                     "Используй кнопки ниже ⬇️",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
    
    @worker_dp.message_handler(commands=['newgame'])
    async def handle_new_game(message: types.Message):
        """Создание новой игры сразу с названием из команды"""
        user_id = message.from_user.id
        user_name = message.from_user.first_name
        
        # Пытаемся получить название из команды
        text = message.text.strip()
        parts = text.split()
        
        if len(parts) > 1:
            # Если есть название после команды
            game_name = ' '.join(parts[1:])
        else:
            # Имя по умолчанию
            game_name = f"Игра от {user_name}"
        
        # Создаем игру
        game = GameManager.create_game(user_id, user_name, game_name)
        
        response = (
            f"🎉 *Игра создана!*\n\n"
            f"📝 *Название:* {game['name']}\n"
            f"🔑 *Код игры:* `{game['id']}`\n"
            f"👑 *Создатель:* {user_name}\n"
            f"👥 *Участников:* 1\n"
            f"📌 *Статус:* Ожидание игроков\n\n"
            f"*Отправьте друзьям код игры:*\n"
            f"`{game['id']}`\n\n"
            f"Для присоединения:\n"
            f"`/join {game['id']}`\n\n"
            f"Теперь укажите ваши пожелания:\n"
            f"`/wish Мои пожелания`"
        )
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(commands=['startgame'])
    async def handle_start_game_command(message: types.Message):
        """Обработчик запуска игры"""
        user_id = message.from_user.id
        
        # Находим игру пользователя
        if user_id not in players_db:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Вы не участвуете в игре.\n"
                     "Сначала создайте игру (/newgame) или присоединитесь (/join)."
            )
            return
        
        current_game = players_db[user_id].get('current_game')
        if not current_game:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Вы не в активной игре."
            )
            return
        
        success, result = GameManager.start_game(current_game, user_id)
        
        if success:
            # Получаем обновленную игру
            game = games_db[current_game]
            
            # Отправляем уведомления всем участникам
            for participant_id in game['participants']:
                try:
                    target_info, _ = GameManager.get_my_target(participant_id)
                    
                    if target_info:
                        await worker_bot.send_message(
                            chat_id=participant_id,
                            text=(
                                f"🎉 *Игра началась!*\n\n"
                                f"🎮 *Название игры:* {game['name']}\n\n"
                                f"🎅 *Вы — Тайный Санта для:*\n"
                                f"👤 *Имя:* {target_info['name']}\n"
                                f"🆔 *ID:* `{target_info['id']}`\n\n"
                                f"🎁 *Пожелания получателя:*\n"
                                f"{target_info['wishlist']}\n\n"
                                f"Удачи в выборе подарка! 🎄"
                            ),
                            parse_mode="Markdown"
                        )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление {participant_id}: {e}")
            
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=(
                    f"✅ *Игра началась!*\n\n"
                    f"Все участники получили свои цели.\n"
                    f"👥 Участников: {len(game['participants'])}\n\n"
                    f"Проверить своего получателя: /mytarget"
                ),
                parse_mode="Markdown"
            )
        else:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"❌ {result}"
            )
    
    @worker_dp.message_handler(commands=['join'])
    async def handle_join_command(message: types.Message):
        """Обработчик присоединения к игре"""
        text = message.text.strip()
        parts = text.split()
        
        if len(parts) < 2:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Укажите код игры:\n"
                     "`/join ABC123XYZ`\n\n"
                     "Код состоит из 8 символов (буквы и цифры)",
                parse_mode="Markdown"
            )
            return
        
        game_code = parts[1].upper()
        user_id = message.from_user.id
        username = message.from_user.first_name
        
        success, result = GameManager.join_game(game_code, user_id, username)
        
        if success:
            # Получаем информацию об игре
            game = GameManager.get_game_info(game_code)
            
            response = (
                f"✅ *Вы присоединились к игре!*\n\n"
                f"🎮 *Название:* {game['name']}\n"
                f"🔑 *Код игры:* `{game_code}`\n"
                f"👑 *Создатель:* {game['creator_name']}\n"
                f"👥 *Участников:* {len(game['participants_info'])}\n"
                f"📌 *Статус:* {game['status']}\n\n"
                f"Теперь укажите ваши пожелания командой:\n"
                f"`/wish Ваши пожелания здесь`\n\n"
                f"Или просто напишите их в чат."
            )
            
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=response,
                parse_mode="Markdown"
            )
        else:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"❌ {result}"
            )
    
    @worker_dp.message_handler(commands=['wish'])
    async def handle_wish_command(message: types.Message):
        """Обработчик указания пожеланий"""
        text = message.text.strip()
        
        if len(text) < 6:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Укажите ваши пожелания:\n"
                     "`/wish Хочу новую книгу фэнтези`",
                parse_mode="Markdown"
            )
            return
        
        wishlist_text = text[6:]
        user_id = message.from_user.id
        
        success, result = GameManager.set_wishlist(user_id, wishlist_text)
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=f"✅ {result}" if success else f"❌ {result}",
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(commands=['mytarget'])
    async def handle_my_target_command(message: types.Message):
        """Обработчик проверки получателя"""
        user_id = message.from_user.id
        
        target_info, status = GameManager.get_my_target(user_id)
        
        if target_info:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"🎅 *Ваш получатель подарка:*\n\n"
                     f"👤 *Имя:* {target_info['name']}\n"
                     f"🆔 *ID:* `{target_info['id']}`\n\n"
                     f"🎁 *Пожелания получателя:*\n"
                     f"{target_info['wishlist']}\n\n"
                     f"Удачи в выборе подарка! 🎄",
                parse_mode="Markdown"
            )
        else:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"❌ {status}"
            )
    
    @worker_dp.message_handler(commands=['mygames'])
    async def handle_my_games_command(message: types.Message):
        """Обработчик списка игр"""
        user_id = message.from_user.id
        games_list = user_games.get(user_id, [])
        
        if not games_list:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ У вас пока нет игр.\n"
                     "Создайте первую игру через /newgame или присоединитесь к существующей через /join."
            )
            return
        
        response = "🎮 *Ваши игры:*\n\n"
        for i, game_id in enumerate(games_list[:10], 1):
            if game_id in games_db:
                game = games_db[game_id]
                status_emoji = {
                    'waiting': '⏳',
                    'active': '🎁',
                    'finished': '✅'
                }.get(game['status'], '❓')
                
                response += f"{i}. {status_emoji} *{game['name']}*\n"
                response += f"   Код: `{game_id}`\n"
                response += f"   Статус: {game['status']}\n"
                response += f"   Участников: {len(game['participants'])}\n\n"
        
        if len(games_list) > 10:
            response += f"... и еще {len(games_list) - 10} игр\n\n"
        
        response += "Для детальной информации:\n`/gameinfo КОД_ИГРЫ`"
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(commands=['gameinfo'])
    async def handle_game_info_command(message: types.Message):
        """Обработчик информации об игре"""
        text = message.text.strip()
        parts = text.split()
        
        if len(parts) < 2:
            # Показываем текущую игру пользователя
            user_id = message.from_user.id
            
            if user_id not in players_db:
                await worker_bot.send_message(
                    chat_id=message.chat.id,
                    text="❌ Вы не участвуете в игре.\n"
                         "Укажите код игры:\n`/gameinfo ABC123XYZ`"
                )
                return
            
            current_game = players_db[user_id].get('current_game')
            if not current_game:
                await worker_bot.send_message(
                    chat_id=message.chat.id,
                    text="❌ Вы не в активной игре.\n"
                         "Укажите код игры:\n`/gameinfo ABC123XYZ`"
                )
                return
            
            game_code = current_game
        else:
            game_code = parts[1].upper()
        
        game = GameManager.get_game_info(game_code)
        
        if not game:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"❌ Игра с кодом `{game_code}` не найдена",
                parse_mode="Markdown"
            )
            return
        
        status_text = {
            'waiting': '⏳ Ожидание игроков',
            'active': '🎁 Игра началась',
            'finished': '✅ Игра завершена'
        }.get(game['status'], game['status'])
        
        response = (
            f"🎮 *Информация об игре*\n\n"
            f"📝 *Название:* {game['name']}\n"
            f"🔑 *Код:* `{game['id']}`\n"
            f"👑 *Создатель:* {game['creator_name']}\n"
            f"📌 *Статус:* {status_text}\n"
            f"💰 *Бюджет:* {game['budget']}\n"
            f"📅 *Создана:* {game['created_at'][:10]}\n"
            f"👥 *Участников:* {len(game['participants_info'])}\n\n"
        )
        
        if game['status'] == 'waiting':
            # Показываем участников
            response += "*Участники:*\n"
            for i, participant in enumerate(game['participants_info'], 1):
                wish_emoji = "📝" if participant['has_wishlist'] else "❔"
                response += f"{i}. {wish_emoji} {participant['name']}\n"
            
            response += f"\n*Для присоединения:*\n`/join {game['id']}`"
        
        elif game['status'] == 'active':
            response += "🎅 *Игра началась!*\n"
            response += "Узнайте своего получателя: /mytarget"
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(commands=['players'])
    async def handle_players_command(message: types.Message):
        """Обработчик списка участников"""
        user_id = message.from_user.id
        
        if user_id not in players_db:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Вы не участвуете в игре."
            )
            return
        
        current_game = players_db[user_id].get('current_game')
        if not current_game or current_game not in games_db:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Вы не в активной игре."
            )
            return
        
        game = games_db[current_game]
        
        response = f"👥 *Участники игры '{game['name']}':*\n\n"
        
        for i, participant_id in enumerate(game['participants'], 1):
            user_info = players_db.get(participant_id, {})
            username = user_info.get('username', 'Неизвестно')
            is_creator = participant_id == game['creator_id']
            has_wishlist = participant_id in game['wishlists']
            
            creator_mark = " 👑" if is_creator else ""
            wish_mark = " 📝" if has_wishlist else " ❔"
            
            response += f"{i}. {username}{creator_mark}{wish_mark}\n"
        
        response += "\n"
        response += f"👑 - создатель игры\n"
        response += f"📝 - указал пожелания\n"
        response += f"❔ - пожелания не указаны\n\n"
        
        if game['status'] == 'waiting':
            response += f"*Код для присоединения:*\n`{game['id']}`"
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(commands=['status'])
    async def handle_status_command(message: types.Message):
        """Обработчик статуса бота"""
        total_games = len(games_db)
        active_games = sum(1 for g in games_db.values() if g['status'] == 'active')
        waiting_games = sum(1 for g in games_db.values() if g['status'] == 'waiting')
        total_players = len(players_db)
        
        response = (
            f"📊 *Статус бота Тайный Санта:*\n\n"
            f"🎮 Всего игр: {total_games}\n"
            f"🎁 Активных игр: {active_games}\n"
            f"⏳ Ожидающих игр: {waiting_games}\n"
            f"👤 Уникальных игроков: {total_players}\n"
            f"🔄 Очередь сообщений: {update_queue.qsize()}\n"
            f"⚙️ Фоновый воркер: {'✅ работает' if 'worker_thread' in globals() and worker_thread.is_alive() else '❌ остановлен'}\n\n"
            f"*Команды:* /help"
        )
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode="Markdown"
        )
    
    # ============== КНОПКИ ГЛАВНОГО МЕНЮ ==============
    @worker_dp.message_handler(lambda message: message.text == "🎮 Создать игру")
    async def handle_create_game_button(message: types.Message):
        """Обработчик кнопки создания игры"""
        user_id = message.from_user.id
        user_name = message.from_user.first_name
        
        # Создаем игру с именем по умолчанию
        game = GameManager.create_game(user_id, user_name)
        
        response = (
            f"🎉 *Игра создана!*\n\n"
            f"📝 *Название:* {game['name']}\n"
            f"🔑 *Код игры:* `{game['id']}`\n"
            f"👑 *Создатель:* {user_name}\n"
            f"👥 *Участников:* 1\n"
            f"📌 *Статус:* Ожидание игроков\n\n"
            f"*Отправьте друзьям код игры:*\n"
            f"`{game['id']}`\n\n"
            f"Для присоединения:\n"
            f"`/join {game['id']}`\n\n"
            f"Теперь укажите ваши пожелания:\n"
            f"`/wish Мои пожелания`"
        )
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(lambda message: message.text == "🎅 Присоединиться")
    async def handle_join_button(message: types.Message):
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text="Для присоединения к игре:\n\n"
                 "1. Получите *8-значный код* от друга\n"
                 "   (например: ABC123XY)\n\n"
                 "2. Используйте команду:\n"
                 "   `/join КОД_ИГРЫ`\n\n"
                 "Или нажмите на ссылку-приглашение, которую вам отправили.",
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(lambda message: message.text == "📋 Мои игры")
    async def handle_my_games_button(message: types.Message):
        await handle_my_games_command(message)
    
    @worker_dp.message_handler(lambda message: message.text == "❓ Помощь")
    async def handle_help_button(message: types.Message):
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=(
                "🎅 *ТАЙНЫЙ САНТА - ПОМОЩЬ*\n\n"
                "*Основные команды:*\n"
                "/start - начать работу\n"
                "/help - помощь\n"
                "/newgame - создать игру\n"
                "/join [код] - присоединиться\n"
                "/startgame - начать игру\n"
                "/mytarget - мой получатель\n"
                "/wish [текст] - указать пожелания\n"
                "/status - статус бота\n\n"
                "*Пример:*\n"
                "1. /newgame\n"
                "2. /join [код]\n"
                "3. Укажите пожелания\n"
                "4. /startgame\n"
                "5. /mytarget"
            ),
            parse_mode="Markdown"
        )
    
    # ============== ОБРАБОТКА ОСТАЛЬНЫХ СООБЩЕНИЙ ==============
    @worker_dp.message_handler()
    async def handle_all_messages(message: types.Message):
        """Обработчик всех остальных сообщений"""
        user_id = message.from_user.id
        text = message.text.strip()
        
        # Если пользователь в игре и игра еще не началась - это пожелания
        if user_id in players_db and players_db[user_id].get('current_game'):
            current_game = players_db[user_id]['current_game']
            
            if current_game in games_db and games_db[current_game]['status'] == 'waiting':
                success, result = GameManager.set_wishlist(user_id, text)
                
                if success:
                    await worker_bot.send_message(
                        chat_id=message.chat.id,
                        text=f"✅ {result}\n\n"
                             f"*Ваши пожелания:*\n{text}\n\n"
                             f"Изменить пожелания можно командой:\n"
                             f"`/wish Новые пожелания`",
                        parse_mode="Markdown"
                    )
                else:
                    await worker_bot.send_message(
                        chat_id=message.chat.id,
                        text=f"❌ {result}"
                    )
                return
        
        # Если сообщение похоже на код игры (8 символов)
        text_upper = text.upper()
        if len(text_upper) == 8 and all(c.isalnum() for c in text_upper):
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"🔍 *Обнаружен код игры:* `{text_upper}`\n\n"
                     f"Присоединиться к игре:\n"
                     f"`/join {text_upper}`\n\n"
                     f"Или посмотреть информацию об игре:\n"
                     f"`/gameinfo {text_upper}`",
                parse_mode="Markdown"
            )
        else:
            # Если это обычное сообщение и мы не знаем что делать
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"👋 Привет, {message.from_user.first_name}!\n\n"
                     f"Вы написали: *{message.text}*\n\n"
                     f"Я — бот для игры *Тайный Санта* 🎅\n"
                     f"Используйте /help для списка команд\n"
                     f"Или выберите действие в меню ниже:",
                parse_mode="Markdown"
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
                    logger.info(f"✅ Обработано update: {update_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка обработки update {update_id}: {e}")
                
                update_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"❌ Критическая ошибка воркера: {e}")
                time.sleep(5)
                
    except Exception as e:
        logger.error(f"❌ Фоновый воркер остановлен: {e}")
    finally:
        logger.info("✅ Фоновый воркер завершен")
        loop.close()

# Запускаем фоновый воркер
worker_thread = threading.Thread(target=background_worker, daemon=True)
worker_thread.start()
logger.info("✅ Фоновый поток запущен")

# ============== FLASK РОУТЫ ==============
@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook# webhook_app.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============== НАСТРОЙКИ ДЛЯ RAILWAY ==============
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен! Добавьте его в Railway Variables.")

RAILWAY_STATIC_URL = os.environ.get('RAILWAY_STATIC_URL')
if RAILWAY_STATIC_URL:
    WEBHOOK_HOST = RAILWAY_STATIC_URL
else:
    WEBHOOK_HOST = "https://web-production-1a5d8.up.railway.app"

if not WEBHOOK_HOST.startswith('http'):
    WEBHOOK_HOST = f"https://{WEBHOOK_HOST}"

WEBHOOK_PATH = f'/webhook/{BOT_TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

logger.info(f"BOT_TOKEN: {'установлен' if BOT_TOKEN else 'НЕ установлен'}")
logger.info(f"WEBHOOK_HOST: {WEBHOOK_HOST}")

# ============== ХРАНИЛИЩЕ ДАННЫХ ==============
games_db = {}        # {game_id: game_data}
players_db = {}      # {user_id: player_data}
game_participants = {}  # {game_id: [user_id1, user_id2]}
user_games = {}      # {user_id: [game_id1, game_id2]}

class GameManager:
    @staticmethod
    def generate_game_id():
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    
    @staticmethod
    def create_game(creator_id, creator_name, game_name, budget=None):
        game_id = GameManager.generate_game_id()
        
        game_data = {
            'id': game_id,
            'name': game_name,
            'creator_id': creator_id,
            'creator_name': creator_name,
            'budget': budget or "Не ограничен",
            'status': 'waiting',  # waiting, active, finished
            'created_at': datetime.now().isoformat(),
            'started_at': None,
            'participants': [creator_id],
            'wishlists': {},
            'pairs': {},
            'invite_link': f"t.me/share/url?url=join_game_{game_id}"
        }
        
        games_db[game_id] = game_data
        game_participants[game_id] = [creator_id]
        
        if creator_id not in user_games:
            user_games[creator_id] = []
        user_games[creator_id].append(game_id)
        
        if creator_id not in players_db:
            players_db[creator_id] = {
                'username': creator_name,
                'games': [],
                'current_game': game_id
            }
        
        return game_data
    
    @staticmethod
    def join_game(game_id, user_id, username):
        if game_id not in games_db:
            return False, "Игра не найдена"
        
        game = games_db[game_id]
        
        if game['status'] != 'waiting':
            return False, "Игра уже началась или завершена"
        
        if user_id in game['participants']:
            return False, "Вы уже в этой игре"
        
        # Добавляем участника
        game['participants'].append(user_id)
        game_participants[game_id].append(user_id)
        
        # Добавляем в список игр пользователя
        if user_id not in user_games:
            user_games[user_id] = []
        if game_id not in user_games[user_id]:
            user_games[user_id].append(game_id)
        
        # Сохраняем данные игрока
        if user_id not in players_db:
            players_db[user_id] = {
                'username': username,
                'games': [],
                'current_game': game_id
            }
        players_db[user_id]['current_game'] = game_id
        
        return True, "Вы успешно присоединились к игре"
    
    @staticmethod
    def start_game(game_id, creator_id):
        if game_id not in games_db:
            return False, "Игра не найдена"
        
        game = games_db[game_id]
        
        if game['creator_id'] != creator_id:
            return False, "Только создатель может начать игру"
        
        if game['status'] != 'waiting':
            return False, "Игра уже началась"
        
        if len(game['participants']) < 2:
            return False, "Нужно минимум 2 участника"
        
        # Жеребьевка
        participants = game['participants'].copy()
        random.shuffle(participants)
        
        pairs = {}
        for i in range(len(participants)):
            santa = participants[i]
            receiver = participants[(i + 1) % len(participants)]
            pairs[santa] = receiver
        
        game['pairs'] = pairs
        game['status'] = 'active'
        game['started_at'] = datetime.now().isoformat()
        
        return True, "Игра началась! Пары распределены."
    
    @staticmethod
    def set_wishlist(user_id, wishlist_text):
        if user_id not in players_db:
            return False, "Вы не участвуете в играх"
        
        current_game = players_db[user_id].get('current_game')
        if not current_game or current_game not in games_db:
            return False, "Вы не в активной игре"
        
        game = games_db[current_game]
        if game['status'] == 'active':
            return False, "Игра уже началась, нельзя изменить пожелания"
        
        game['wishlists'][user_id] = wishlist_text
        return True, "Пожелания сохранены!"
    
    @staticmethod
    def get_my_target(user_id):
        if user_id not in players_db:
            return None, "Вы не участвуете в играх"
        
        current_game = players_db[user_id].get('current_game')
        if not current_game or current_game not in games_db:
            return None, "Вы не в активной игре"
        
        game = games_db[current_game]
        if game['status'] != 'active':
            return None, "Игра еще не началась"
        
        if user_id not in game['pairs']:
            return None, "Вы не участвуете в этой игре"
        
        target_id = game['pairs'][user_id]
        target_wishlist = game['wishlists'].get(target_id, "Пожелания не указаны")
        target_name = players_db.get(target_id, {}).get('username', 'Неизвестный игрок')
        
        return {
            'id': target_id,
            'name': target_name,
            'wishlist': target_wishlist
        }, "Найдено"
    
    @staticmethod
    def get_game_info(game_id):
        if game_id not in games_db:
            return None
        
        game = games_db[game_id].copy()
        # Скрываем пары для общего просмотра
        if 'pairs' in game:
            del game['pairs']
        
        # Добавляем информацию об участниках
        participants_info = []
        for user_id in game['participants']:
            user_info = players_db.get(user_id, {})
            participants_info.append({
                'id': user_id,
                'name': user_info.get('username', 'Неизвестно'),
                'has_wishlist': user_id in game['wishlists']
            })
        
        game['participants_info'] = participants_info
        return game

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
    
    # ============== ОБРАБОТЧИКИ КОМАНД ==============
    @worker_dp.message_handler(commands=['start', 'help'])
    async def handle_start(message: types.Message):
        """Обработчик команд /start и /help"""
        if message.text == '/help':
            help_text = """
🎅 *ТАЙНЫЙ САНТА - ПОЛНАЯ СПРАВКА*

*Основные команды:*
/start - Начать работу с ботом
/help - Показать эту справку

*🎮 Управление игрой:*
/newgame - Создать новую игру
/mygames - Список ваших игр
/gameinfo [код] - Информация об игре
/startgame - Запустить игру (только создатель)

*🤝 Участие в игре:*
/join [код] - Присоединиться к игре
/players - Список участников текущей игры

*🎁 Подарки:*
/wish [текст] - Указать пожелания
/mywishlist - Посмотреть мои пожелания
/mytarget - Кому я дарю подарок?

*📊 Информация:*
/status - Статус бота и статистика

*💡 Примеры:*
/join ABC123XYZ - присоединиться к игре
/wish Хочу книгу - указать пожелания
/startgame - начать игру
            """
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=help_text,
                parse_mode="Markdown"
            )
        else:
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
                     "• Создавать игры с кодами-приглашениями\n"
                     "• Автоматически распределять пары Сант\n"
                     "• Хранить пожелания участников\n\n"
                     "🎯 *Быстрый старт:*\n"
                     "1. Нажми *«Создать игру»*\n"
                     "2. Укажи название игры\n"
                     "3. Отправь друзьям код игры\n"
                     "4. Запусти игру командой /startgame\n\n"
                     "Или используй кнопки ниже ⬇️",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
    
    # ============== КОМАНДЫ ИГРЫ ==============
    @worker_dp.message_handler(commands=['newgame', 'new_game'])
    async def handle_new_game(message: types.Message):
        """Обработчик создания новой игры"""
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text="🎄 *Давайте создадим новую игру Тайного Санты!*\n\n"
                 "Введите *название* для вашей игры:\n"
                 "(например: 'Семейный Новый Год' или 'Корпоратив 2024')",
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(commands=['startgame', 'start_game'])
    async def handle_start_game_command(message: types.Message):
        """Обработчик запуска игры"""
        user_id = message.from_user.id
        
        # Находим игру пользователя
        current_game = players_db.get(user_id, {}).get('current_game')
        if not current_game:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Вы не участвуете в игре.\n"
                     "Сначала создайте игру (/newgame) или присоединитесь (/join)."
            )
            return
        
        success, result = GameManager.start_game(current_game, user_id)
        
        if success:
            # Получаем обновленную игру
            game = games_db[current_game]
            
            # Отправляем уведомления всем участникам
            for participant_id in game['participants']:
                try:
                    target_info, _ = GameManager.get_my_target(participant_id)
                    
                    if target_info:
                        await worker_bot.send_message(
                            chat_id=participant_id,
                            text=(
                                f"🎉 *Игра началась!*\n\n"
                                f"🎮 *Название игры:* {game['name']}\n\n"
                                f"🎅 *Вы — Тайный Санта для:*\n"
                                f"👤 *Имя:* {target_info['name']}\n"
                                f"🆔 *ID:* `{target_info['id']}`\n\n"
                                f"🎁 *Пожелания получателя:*\n"
                                f"{target_info['wishlist']}\n\n"
                                f"Удачи в выборе подарка! 🎄"
                            ),
                            parse_mode="Markdown"
                        )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление {participant_id}: {e}")
            
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=(
                    f"✅ *Игра началась!*\n\n"
                    f"Все участники получили свои цели.\n"
                    f"👥 Участников: {len(game['participants'])}\n\n"
                    f"Проверить своего получателя: /mytarget"
                ),
                parse_mode="Markdown"
            )
        else:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"❌ {result}"
            )
    
    @worker_dp.message_handler(commands=['join'])
    async def handle_join_command(message: types.Message):
        """Обработчик присоединения к игре"""
        text = message.text.strip()
        parts = text.split()
        
        if len(parts) < 2:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Укажите код игры:\n"
                     "`/join ABC123XYZ`\n\n"
                     "Код состоит из 8 символов (буквы и цифры)",
                parse_mode="Markdown"
            )
            return
        
        game_code = parts[1].upper()
        user_id = message.from_user.id
        username = message.from_user.first_name
        
        success, result = GameManager.join_game(game_code, user_id, username)
        
        if success:
            # Получаем информацию об игре
            game = GameManager.get_game_info(game_code)
            
            response = (
                f"✅ *Вы присоединились к игре!*\n\n"
                f"🎮 *Название:* {game['name']}\n"
                f"🔑 *Код игры:* `{game_code}`\n"
                f"👑 *Создатель:* {game['creator_name']}\n"
                f"👥 *Участников:* {len(game['participants_info'])}\n"
                f"📌 *Статус:* {game['status']}\n\n"
                f"Теперь укажите ваши пожелания командой:\n"
                f"`/wish Ваши пожелания здесь`\n\n"
                f"Или просто напишите их в чат."
            )
            
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=response,
                parse_mode="Markdown"
            )
        else:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"❌ {result}"
            )
    
    @worker_dp.message_handler(commands=['wish'])
    async def handle_wish_command(message: types.Message):
        """Обработчик указания пожеланий"""
        text = message.text.strip()
        
        if len(text) < 6:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Укажите ваши пожелания:\n"
                     "`/wish Хочу новую книгу фэнтези`",
                parse_mode="Markdown"
            )
            return
        
        wishlist_text = text[6:]
        user_id = message.from_user.id
        
        success, result = GameManager.set_wishlist(user_id, wishlist_text)
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=f"✅ {result}" if success else f"❌ {result}",
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(commands=['mytarget', 'my_target'])
    async def handle_my_target_command(message: types.Message):
        """Обработчик проверки получателя"""
        user_id = message.from_user.id
        
        target_info, status = GameManager.get_my_target(user_id)
        
        if target_info:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"🎅 *Ваш получатель подарка:*\n\n"
                     f"👤 *Имя:* {target_info['name']}\n"
                     f"🆔 *ID:* `{target_info['id']}`\n\n"
                     f"🎁 *Пожелания получателя:*\n"
                     f"{target_info['wishlist']}\n\n"
                     f"Удачи в выборе подарка! 🎄",
                parse_mode="Markdown"
            )
        else:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"❌ {status}"
            )
    
    @worker_dp.message_handler(commands=['mygames', 'my_games'])
    async def handle_my_games_command(message: types.Message):
        """Обработчик списка игр"""
        user_id = message.from_user.id
        games_list = user_games.get(user_id, [])
        
        if not games_list:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ У вас пока нет игр.\n"
                     "Создайте первую игру через /newgame или присоединитесь к существующей через /join."
            )
            return
        
        response = "🎮 *Ваши игры:*\n\n"
        for i, game_id in enumerate(games_list[:10], 1):
            if game_id in games_db:
                game = games_db[game_id]
                status_emoji = {
                    'waiting': '⏳',
                    'active': '🎁',
                    'finished': '✅'
                }.get(game['status'], '❓')
                
                response += f"{i}. {status_emoji} *{game['name']}*\n"
                response += f"   Код: `{game_id}`\n"
                response += f"   Статус: {game['status']}\n"
                response += f"   Участников: {len(game['participants'])}\n\n"
        
        if len(games_list) > 10:
            response += f"... и еще {len(games_list) - 10} игр\n\n"
        
        response += "Для детальной информации:\n`/gameinfo КОД_ИГРЫ`"
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(commands=['gameinfo', 'game_info'])
    async def handle_game_info_command(message: types.Message):
        """Обработчик информации об игре"""
        text = message.text.strip()
        parts = text.split()
        
        if len(parts) < 2:
            # Показываем текущую игру пользователя
            user_id = message.from_user.id
            current_game = players_db.get(user_id, {}).get('current_game')
            
            if not current_game:
                await worker_bot.send_message(
                    chat_id=message.chat.id,
                    text="❌ Вы не участвуете в игре.\n"
                         "Укажите код игры:\n`/gameinfo ABC123XYZ`"
                )
                return
            
            game_code = current_game
        else:
            game_code = parts[1].upper()
        
        game = GameManager.get_game_info(game_code)
        
        if not game:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"❌ Игра с кодом `{game_code}` не найдена",
                parse_mode="Markdown"
            )
            return
        
        status_text = {
            'waiting': '⏳ Ожидание игроков',
            'active': '🎁 Игра началась',
            'finished': '✅ Игра завершена'
        }.get(game['status'], game['status'])
        
        response = (
            f"🎮 *Информация об игре*\n\n"
            f"📝 *Название:* {game['name']}\n"
            f"🔑 *Код:* `{game['id']}`\n"
            f"👑 *Создатель:* {game['creator_name']}\n"
            f"📌 *Статус:* {status_text}\n"
            f"💰 *Бюджет:* {game['budget']}\n"
            f"📅 *Создана:* {game['created_at'][:10]}\n"
            f"👥 *Участников:* {len(game['participants_info'])}\n\n"
        )
        
        if game['status'] == 'waiting':
            # Показываем участников
            response += "*Участники:*\n"
            for i, participant in enumerate(game['participants_info'], 1):
                wish_emoji = "📝" if participant['has_wishlist'] else "❔"
                response += f"{i}. {wish_emoji} {participant['name']}\n"
            
            response += f"\n*Для присоединения:*\n`/join {game['id']}`"
        
        elif game['status'] == 'active':
            response += "🎅 *Игра началась!*\n"
            response += "Узнайте своего получателя: /mytarget"
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(commands=['players'])
    async def handle_players_command(message: types.Message):
        """Обработчик списка участников"""
        user_id = message.from_user.id
        current_game = players_db.get(user_id, {}).get('current_game')
        
        if not current_game or current_game not in games_db:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Вы не участвуете в игре."
            )
            return
        
        game = games_db[current_game]
        
        response = f"👥 *Участники игры '{game['name']}':*\n\n"
        
        for i, participant_id in enumerate(game['participants'], 1):
            user_info = players_db.get(participant_id, {})
            username = user_info.get('username', 'Неизвестно')
            is_creator = participant_id == game['creator_id']
            has_wishlist = participant_id in game['wishlists']
            
            creator_mark = " 👑" if is_creator else ""
            wish_mark = " 📝" if has_wishlist else " ❔"
            
            response += f"{i}. {username}{creator_mark}{wish_mark}\n"
        
        response += "\n"
        response += f"👑 - создатель игры\n"
        response += f"📝 - указал пожелания\n"
        response += f"❔ - пожелания не указаны\n\n"
        
        if game['status'] == 'waiting':
            response += f"*Код для присоединения:*\n`{game['id']}`"
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(commands=['status'])
    async def handle_status_command(message: types.Message):
        """Обработчик статуса бота"""
        total_games = len(games_db)
        active_games = sum(1 for g in games_db.values() if g['status'] == 'active')
        waiting_games = sum(1 for g in games_db.values() if g['status'] == 'waiting')
        total_players = len(players_db)
        
        response = (
            f"📊 *Статус бота Тайный Санта:*\n\n"
            f"🎮 Всего игр: {total_games}\n"
            f"🎁 Активных игр: {active_games}\n"
            f"⏳ Ожидающих игр: {waiting_games}\n"
            f"👤 Уникальных игроков: {total_players}\n"
            f"🔄 Очередь сообщений: {update_queue.qsize()}\n"
            f"⚙️ Фоновый воркер: {'✅ работает' if 'worker_thread' in globals() and worker_thread.is_alive() else '❌ остановлен'}\n\n"
            f"*Команды:* /help"
        )
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode="Markdown"
        )
    
    # ============== КНОПКИ ГЛАВНОГО МЕНЮ ==============
    @worker_dp.message_handler(lambda message: message.text == "🎮 Создать игру")
    async def handle_create_game_button(message: types.Message):
        await handle_new_game(message)
    
    @worker_dp.message_handler(lambda message: message.text == "🎅 Присоединиться")
    async def handle_join_button(message: types.Message):
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text="Для присоединения к игре:\n\n"
                 "1. Получите *8-значный код* от друга\n"
                 "   (например: ABC123XY)\n\n"
                 "2. Используйте команду:\n"
                 "   `/join КОД_ИГРЫ`\n\n"
                 "Или нажмите на ссылку-приглашение, которую вам отправили.",
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(lambda message: message.text == "📋 Мои игры")
    async def handle_my_games_button(message: types.Message):
        await handle_my_games_command(message)
    
    @worker_dp.message_handler(lambda message: message.text == "❓ Помощь")
    async def handle_help_button(message: types.Message):
        await handle_start(message)  # /help обрабатывается в handle_start
    
    # ============== ОБРАБОТКА ОСТАЛЬНЫХ СООБЩЕНИЙ ==============
    @worker_dp.message_handler()
    async def handle_all_messages(message: types.Message):
        """Обработчик всех остальных сообщений"""
        user_id = message.from_user.id
        text = message.text.strip()
        
        # Если пользователь только что создал игру - это название игры
        if user_id in players_db and user_id not in user_games:
            # Создаем игру с введенным названием
            game = GameManager.create_game(user_id, message.from_user.first_name, text)
            
            response = (
                f"🎉 *Игра создана!*\n\n"
                f"📝 *Название:* {game['name']}\n"
                f"🔑 *Код игры:* `{game['id']}`\n"
                f"👑 *Создатель:* {game['creator_name']}\n"
                f"👥 *Участников:* 1\n"
                f"📌 *Статус:* Ожидание игроков\n"
                f"💰 *Бюджет:* {game['budget']}\n\n"
                f"*Отправьте друзьям код игры:*\n"
                f"`{game['id']}`\n\n"
                f"Для присоединения нужно отправить:\n"
                f"`/join {game['id']}`\n\n"
                f"Когда все присоединятся, нажмите /startgame"
            )
            
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=response,
                parse_mode="Markdown"
            )
            return
        
        # Если пользователь в игре и игра еще не началась - это пожелания
        if user_id in players_db and players_db[user_id].get('current_game'):
            current_game = players_db[user_id]['current_game']
            
            if current_game in games_db and games_db[current_game]['status'] == 'waiting':
                success, result = GameManager.set_wishlist(user_id, text)
                
                if success:
                    await worker_bot.send_message(
                        chat_id=message.chat.id,
                        text=f"✅ {result}\n\n"
                             f"*Ваши пожелания:*\n{text}\n\n"
                             f"Изменить пожелания можно командой:\n"
                             f"`/wish Новые пожелания`",
                        parse_mode="Markdown"
                    )
                else:
                    await worker_bot.send_message(
                        chat_id=message.chat.id,
                        text=f"❌ {result}"
                    )
                return
        
        # Если сообщение похоже на код игры (8 символов)
        if len(text) == 8 and all(c.isalnum() for c in text.upper()):
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"🔍 *Обнаружен код игры:* `{text.upper()}`\n\n"
                     f"Присоединиться к игре:\n"
                     f"`/join {text.upper()}`\n\n"
                     f"Или посмотреть информацию об игре:\n"
                     f"`/gameinfo {text.upper()}`",
                parse_mode="Markdown"
            )
        else:
            # Если это обычное сообщение и мы не знаем что делать
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"👋 Привет, {message.from_user.first_name}!\n\n"
                     f"Вы написали: *{message.text}*\n\n"
                     f"Я — бот для игры *Тайный Санта* 🎅\n"
                     f"Используйте /help для списка команд\n"
                     f"Или выберите действие в меню ниже:",
                parse_mode="Markdown"
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
                    logger.info(f"✅ Обработано update: {update_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка обработки update {update_id}: {e}")
                
                update_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"❌ Критическая ошибка воркера: {e}")
                time.sleep(5)
                
    except Exception as e:
        logger.error(f"❌ Фоновый воркер остановлен: {e}")
    finally:
        logger.info("✅ Фоновый воркер завершен")
        loop.close()

# Запускаем фоновый воркер
worker_thread = threading.Thread(target=background_worker, daemon=True)
worker_thread.start()
logger.info("✅ Фоновый поток запущен")

# ============== FLASK РОУТЫ ==============
@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    """Основной обработчик вебхуков"""
    try:
        update_data = request.get_json()
        update_id = update_data.get('update_id', 'unknown')
        
        update_queue.put(update_data)
        
        logger.info(f"📥 Update {update_id} добавлен в очередь")
        return jsonify({'status': 'queued', 'update_id': update_id})
            
    except Exception as e:
        logger.error(f"❌ Ошибка в webhook: {e}")
        return jsonify({'status': 'error'}), 500

@app.route('/')
def index():
    return """
    🎅 Бот 'Тайный Санта' работает на Railway!<br>
    Статус: ONLINE<br><br>
    <a href='/set_webhook'>Установить вебхук</a><br>
    <a href='/status'>Статус API</a><br>
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
        'service': 'Secret Santa Bot',
        'timestamp': datetime.datetime.now().isoformat(),
        'webhook_url': WEBHOOK_URL,
        'queue_size': update_queue.qsize(),
        'background_worker': worker_thread.is_alive() if 'worker_thread' in locals() else False,
        'total_games': len(games_db),
        'active_games': sum(1 for g in games_db.values() if g['status'] == 'active'),
        'total_players': len(players_db)
    })

@app.route('/stats')
def stats():
    """Страница статистики"""
    active_games = sum(1 for g in games_db.values() if g['status'] == 'active')
    waiting_games = sum(1 for g in games_db.values() if g['status'] == 'waiting')
    
    return f"""
    <h1>🎅 Статистика Тайного Санты</h1>
    <p>Всего игр: {len(games_db)}</p>
    <p>Активных игр: {active_games}</p>
    <p>Ожидающих игр: {waiting_games}</p>
    <p>Зарегистрированных игроков: {len(players_db)}</p>
    <p>Очередь сообщений: {update_queue.qsize()}</p>
    <p>Фоновый воркер: {'✅ работает' if worker_thread.is_alive() else '❌ остановлен'}</p>
    <p><a href='/'>На главную</a></p>
    """

# ============== ЗАПУСК ПРИЛОЖЕНИЯ ==============
if __name__ == '__main__':
    print("🚀 Запуск Flask приложения...")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
