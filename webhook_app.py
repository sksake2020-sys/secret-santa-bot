# webhook_app.py - ПОЛНЫЙ ТАЙНЫЙ САНТА (совместимая версия)
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
    
    @staticmethod
    def cleanup_old_games():
        """Очистка старых завершенных игр (раз в день)"""
        current_time = datetime.now()
        games_to_remove = []
        
        for game_id, game in games_db.items():
            if game['status'] == 'finished':
                created_at = datetime.fromisoformat(game['created_at'])
                if (current_time - created_at).days > 7:  # 7 дней
                    games_to_remove.append(game_id)
        
        for game_id in games_to_remove:
            # Удаляем из всех связанных структур
            for user_id in game_participants.get(game_id, []):
                if user_id in user_games and game_id in user_games[user_id]:
                    user_games[user_id].remove(game_id)
            
            del games_db[game_id]
            if game_id in game_participants:
                del game_participants[game_id]
            
            logger.info(f"Очищена старая игра: {game_id}")

# ============== ОЧЕРЕДЬ ДЛЯ ОБНОВЛЕНИЙ ==============
update_queue = queue.Queue()

# ============== ФОНОВЫЙ ОБРАБОТЧИК ==============
def background_worker():
    """Фоновый воркер, который обрабатывает обновления из очереди"""
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.fsm_storage.memory import MemoryStorage
    
    # Создаем бота для этого потока (старая версия aiogram)
    worker_bot = Bot(token=BOT_TOKEN)
    Bot.set_current(worker_bot)
    worker_storage = MemoryStorage()
    worker_dp = Dispatcher(worker_bot, worker_storage)
    
    # ============== ОБРАБОТЧИКИ КОМАНД ==============
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
        keyboard.row(
            types.KeyboardButton("🎁 Мой получатель"),
            types.KeyboardButton("📝 Мои пожелания")
        )
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=f"🎅 Привет, {message.from_user.first_name}! 👋\n\n"
                 "Я — бот для организации *Тайного Санты*.\n\n"
                 "✨ *Что я умею:*\n"
                 "• Создавать игры с кодами-приглашениями\n"
                 "• Автоматически распределять пары Сант\n"
                 "• Хранить пожелания участников\n"
                 "• Отправлять напоминания о подарках\n\n"
                 "🎯 *Быстрый старт:*\n"
                 "1. Нажми *«Создать игру»*\n"
                 "2. Укажи бюджет и название\n"
                 "3. Отправь друзьям код игры\n"
                 "4. Запусти игру командой /start_game\n\n"
                 "Или используй кнопки ниже ⬇️",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(commands=['help'])
    async def handle_help(message: types.Message):
        """Обработчик команды /help"""
        help_text = """
🎅 *ТАЙНЫЙ САНТА - ПОЛНАЯ СПРАВКА*

*Основные команды:*
/start - Начать работу с ботом
/help - Показать эту справку

*🎮 Управление игрой:*
/new_game - Создать новую игру
/my_games - Список ваших игр
/game_info [код] - Информация об игре
/start_game - Запустить игру (только создатель)
/end_game - Завершить игру (только создатель)

*🤝 Участие в игре:*
/join [код] - Присоединиться к игре
/leave_game - Покинуть текущую игру
/players - Список участников текущей игры

*🎁 Подарки:*
/wish [текст] - Указать пожелания
/my_wishlist - Посмотреть мои пожелания
/my_target - Кому я дарю подарок?
/set_budget [сумма] - Установить бюджет (для создателя)

*📊 Информация:*
/status - Статус бота и статистика
/clear_data - Очистить мои данные

*💡 Примеры:*
`/join ABC123XYZ` - присоединиться к игре
`/wish Хочу новую книгу по программированию` - указать пожелания
`/start_game` - начать игру (после присоединения всех)
        """
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=help_text,
            parse_mode="Markdown"
        )
    
    # ============== КНОПКИ ГЛАВНОГО МЕНЮ ==============
    @worker_dp.message_handler(lambda message: message.text == "🎮 Создать игру")
    async def handle_create_game_button(message: types.Message):
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text="🎄 *Давайте создадим новую игру Тайного Санты!*\n\n"
                 "Введите *название* для вашей игры:\n"
                 "(например: 'Семейный Новый Год' или 'Корпоратив 2024')",
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
        user_id = message.from_user.id
        games_list = user_games.get(user_id, [])
        
        if not games_list:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ У вас пока нет игр.\n"
                     "Создайте первую игру через меню или присоединитесь к существующей."
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
        
        response += "Для детальной информации:\n`/game_info КОД_ИГРЫ`"
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(lambda message: message.text == "🎁 Мой получатель")
    async def handle_my_target_button(message: types.Message):
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
    
    @worker_dp.message_handler(lambda message: message.text == "📝 Мои пожелания")
    async def handle_my_wishlist_button(message: types.Message):
        user_id = message.from_user.id
        current_game = players_db.get(user_id, {}).get('current_game')
        
        if not current_game or current_game not in games_db:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Вы не участвуете в активной игре.\n"
                     "Присоединитесь к игре или создайте новую."
            )
            return
        
        game = games_db[current_game]
        wishlist = game['wishlists'].get(user_id, "❌ Пожелания не указаны")
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=f"📝 *Ваши текущие пожелания:*\n\n{wishlist}\n\n"
                 f"*Игра:* {game['name']}\n"
                 f"*Код игры:* `{game['id']}`\n\n"
                 f"Изменить пожелания:\n"
                 f"`/wish Ваши новые пожелания`",
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(lambda message: message.text == "❓ Помощь")
    async def handle_help_button(message: types.Message):
        await handle_help(message)
    
    # ============== КОМАНДЫ БОТА ==============
    @worker_dp.message_handler(commands=['new_game'])
    async def handle_new_game(message: types.Message):
        text = message.text.strip()
        
        if len(text) > 9:  # "/new_game" + пробел + название
            game_name = text[10:]
            
            # Очищаем старые игры
            GameManager.cleanup_old_games()
            
            # Создаем игру
            game = GameManager.create_game(
                message.from_user.id,
                message.from_user.first_name,
                game_name
            )
            
            keyboard = types.InlineKeyboardMarkup()
            invite_button = types.InlineKeyboardButton(
                "🎅 Пригласить друзей",
                url=f"https://t.me/share/url?url=Присоединяйся%20к%20моей%20игре%20Тайного%20Санты!%20Код:%20{game['id']}"
            )
            keyboard.add(invite_button)
            
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
                f"Когда все присоединятся, нажмите /start_game"
            )
            
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=response,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Укажите название игры:\n"
                     "`/new_game Семейный Новый Год`\n\n"
                     "Или используйте кнопку '🎮 Создать игру' в меню",
                parse_mode="Markdown"
            )
    
    @worker_dp.message_handler(commands=['join'])
    async def handle_join_command(message: types.Message):
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
            
            keyboard = types.InlineKeyboardMarkup()
            set_wishlist_button = types.InlineKeyboardButton(
                "📝 Указать пожелания",
                callback_data=f"set_wish_{game_code}"
            )
            keyboard.add(set_wishlist_button)
            
            response = (
                f"✅ *Вы присоединились к игре!*\n\n"
                f"🎮 *Название:* {game['name']}\n"
                f"🔑 *Код игры:* `{game_code}`\n"
                f"👑 *Создатель:* {game['creator_name']}\n"
                f"👥 *Участников:* {len(game['participants_info'])}\n"
                f"📌 *Статус:* {game['status']}\n"
                f"💰 *Бюджет:* {game['budget']}\n\n"
                f"Нажмите кнопку ниже, чтобы указать ваши пожелания:"
            )
            
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=response,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"❌ {result}"
            )
    
    @worker_dp.message_handler(commands=['game_info'])
    async def handle_game_info(message: types.Message):
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
                         "Укажите код игры:\n`/game_info ABC123XYZ`"
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
            response += "Узнайте своего получателя: /my_target"
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=response,
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(commands=['start_game'])
    async def handle_start_game_command(message: types.Message):
        user_id = message.from_user.id
        
        # Находим игру пользователя
        current_game = players_db.get(user_id, {}).get('current_game')
        if not current_game:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Вы не участвуете в игре."
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
                    f"Проверить своего получателя: /my_target"
                ),
                parse_mode="Markdown"
            )
        else:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"❌ {result}"
            )
    
    @worker_dp.message_handler(commands=['wish'])
    async def handle_wish_command(message: types.Message):
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
    
    @worker_dp.message_handler(commands=['players'])
    async def handle_players_command(message: types.Message):
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
    
    @worker_dp.message_handler(commands=['clear_data'])
    async def handle_clear_data(message: types.Message):
        keyboard = types.InlineKeyboardMarkup()
        confirm_button = types.InlineKeyboardButton(
            "✅ Да, очистить мои данные",
            callback_data="clear_data_confirm"
        )
        cancel_button = types.InlineKeyboardButton(
            "❌ Нет, отменить",
            callback_data="clear_data_cancel"
        )
        keyboard.add(confirm_button, cancel_button)
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text="⚠️ *Внимание!*\n\n"
                 "Вы собираетесь удалить ВСЕ ваши данные:\n"
                 "• Информацию о вас как игроке\n"
                 "• Ваши пожелания во всех играх\n"
                 "• Список ваших игр\n\n"
                 "Это действие *нельзя отменить*!\n"
                 "Вы уверены?",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(commands=['my_games'])
    async def handle_my_games_command(message: types.Message):
        await handle_my_games_button(message)
    
    @worker_dp.message_handler(commands=['my_target'])
    async def handle_my_target_command(message: types.Message):
        await handle_my_target_button(message)
    
    @worker_dp.message_handler(commands=['set_budget'])
    async def handle_set_budget(message: types.Message):
        text = message.text.strip()
        parts = text.split()
        
        if len(parts) < 2:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Укажите бюджет:\n"
                     "`/set_budget 1000 руб`\n"
                     "`/set_budget Не ограничен`"
            )
            return
        
        user_id = message.from_user.id
        current_game = players_db.get(user_id, {}).get('current_game')
        
        if not current_game or current_game not in games_db:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Вы не создатель игры."
            )
            return
        
        game = games_db[current_game]
        if game['creator_id'] != user_id:
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text="❌ Только создатель игры может менять бюджет."
            )
            return
        
        new_budget = ' '.join(parts[1:])
        game['budget'] = new_budget
        
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text=f"✅ Бюджет обновлен:\n{new_budget}"
        )
    
    # ============== ОБРАБОТКА CALLBACK-QUERY ==============
    @worker_dp.callback_query_handler(lambda c: c.data.startswith('set_wish_'))
    async def process_set_wish(callback_query: types.CallbackQuery):
        game_code = callback_query.data.split('_')[2]
        await worker_bot.answer_callback_query(callback_query.id)
        
        await worker_bot.send_message(
            callback_query.from_user.id,
            f"📝 *Укажите ваши пожелания для подарка:*\n\n"
            f"Напишите сообщение с вашими пожеланиями.\n"
            f"Что вам нравится? Что бы вы хотели получить?\n\n"
            f"*Пример:* Хочу книгу по программированию на Python\n\n"
            f"Или используйте команду:\n"
            f"`/wish Ваши пожелания здесь`",
            parse_mode="Markdown"
        )
    
    @worker_dp.callback_query_handler(lambda c: c.data == 'clear_data_confirm')
    async def process_clear_data_confirm(callback_query: types.CallbackQuery):
        user_id = callback_query.from_user.id
        
        # Удаляем пользователя из всех игр
        if user_id in user_games:
            for game_id in user_games[user_id]:
                if game_id in games_db:
                    game = games_db[game_id]
                    if user_id in game['participants']:
                        game['participants'].remove(user_id)
                    if user_id in game['wishlists']:
                        del game['wishlists'][user_id]
                    if user_id in game['pairs']:
                        del game['pairs'][user_id]
            
            del user_games[user_id]
        
        if user_id in players_db:
            del players_db[user_id]
        
        await worker_bot.answer_callback_query(
            callback_query.id,
            "✅ Все ваши данные удалены!",
            show_alert=True
        )
        
        await worker_bot.send_message(
            callback_query.from_user.id,
            "🧹 *Все ваши данные удалены.*\n\n"
            "Вы можете начать заново с команды /start",
            parse_mode="Markdown"
        )
    
    @worker_dp.callback_query_handler(lambda c: c.data == 'clear_data_cancel')
    async def process_clear_data_cancel(callback_query: types.CallbackQuery):
        await worker_bot.answer_callback_query(
            callback_query.id,
            "❌ Удаление данных отменено.",
            show_alert=True
        )
    
    # ============== ОБРАБОТКА ВСЕХ ОСТАЛЬНЫХ СООБЩЕНИЙ ==============
    @worker_dp.message_handler()
    async def handle_all_messages(message: types.Message):
        user_id = message.from_user.id
        
        # Если пользователь в игре и пишет обычное сообщение - считаем это пожеланиями
        if user_id in players_db and players_db[user_id].get('current_game'):
            current_game = players_db[user_id]['current_game']
            
            # Если игра еще не началась
            if current_game in games_db and games_db[current_game]['status'] == 'waiting':
                success, result = GameManager.set_wishlist(user_id, message.text)
                
                if success:
                    await worker_bot.send_message(
                        chat_id=message.chat.id,
                        text=f"✅ {result}\n\n"
                             f"*Ваши пожелания:*\n{message.text}\n\n"
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
        text = message.text.strip().upper()
        if len(text) == 8 and all(c.isalnum() for c in text):
            await worker_bot.send_message(
                chat_id=message.chat.id,
                text=f"🔍 *Обнаружен код игры:* `{text}`\n\n"
                     f"Присоединиться к игре:\n"
                     f"`/join {text}`\n\n"
                     f"Или посмотреть информацию об игре:\n"
                     f"`/game_info {text}`",
                parse_mode="Markdown"
            )
        else:
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
        
        # Простая версия для старого aiogram
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
