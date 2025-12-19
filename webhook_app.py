# webhook_app.py - ПОЛНАЯ ВЕРСИЯ С ДИПЛИНКОМ И ЗАВЕРШЕНИЕМ ИГРЫ
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
BOT_USERNAME = os.environ.get('BOT_USERNAME')  # например: TainiSantaBot
if not BOT_TOKEN or not BOT_USERNAME:
    raise ValueError("BOT_TOKEN и BOT_USERNAME должны быть установлены!")

RAILWAY_STATIC_URL = os.environ.get('RAILWAY_STATIC_URL')
WEBHOOK_HOST = RAILWAY_STATIC_URL or "https://web-production-1a5d8.up.railway.app"
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
        invite_link = f"https://t.me/{BOT_USERNAME}?start=join_{game_id}"
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
            'invite_link': invite_link
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
        else:
            players_db[creator_id]['current_game'] = game_id
        
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
        
        game['participants'].append(user_id)
        game_participants[game_id].append(user_id)
        
        if user_id not in user_games:
            user_games[user_id] = []
        if game_id not in user_games[user_id]:
            user_games[user_id].append(game_id)
        
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
    def finish_game(game_id, user_id):
        if game_id not in games_db:
            return False, "Игра не найдена"
        game = games_db[game_id]
        if game['creator_id'] != user_id:
            return False, "Только создатель может завершить игру"
        if game['status'] != 'active':
            return False, "Игра еще не началась или уже завершена"
        game['status'] = 'finished'
        return True, "Игра завершена!"
    
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
        if 'pairs' in game:
            del game['pairs']
        
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
    
    worker_bot = Bot(token=BOT_TOKEN)
    Bot.set_current(worker_bot)
    worker_storage = MemoryStorage()
    worker_dp = Dispatcher(worker_bot, worker_storage)

    # Состояние «ждет название игры»
    pending_new_game = {}  # {user_id: True}
    
    # ---------- START / HELP ----------
    @worker_dp.message_handler(commands=['start'])
    async def handle_start(message: types.Message):
        """Обработка /start с диплинком join_<game_id>"""
        args = message.get_args()
        if args and args.startswith("join_"):
            game_code = args.replace("join_", "").upper()
            success, result = GameManager.join_game(game_code, message.from_user.id, message.from_user.first_name)
            if success:
                game = GameManager.get_game_info(game_code)
                await worker_bot.send_message(
                    message.chat.id,
                    f"✅ Вы присоединились к игре *{game['name']}*\n"
                    f"🔑 Код: `{game_code}`\n"
                    f"Теперь укажите ваши пожелания командой:\n`/wish Ваши пожелания`",
                    parse_mode="Markdown"
                )
            else:
                await worker_bot.send_message(message.chat.id, f"❌ {result}")
            return

        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.row(types.KeyboardButton("🎮 Создать игру"), types.KeyboardButton("🎅 Присоединиться"))
        keyboard.row(types.KeyboardButton("❓ Помощь"), types.KeyboardButton("📋 Мои игры"))
        await worker_bot.send_message(
            message.chat.id,
            f"🎅 Привет, {message.from_user.first_name}! 👋\n\n"
            "Я — бот для организации *Тайного Санты*.\n\n"
            "✨ *Что я умею:*\n"
            "• Создавать игры с кодами-приглашениями\n"
            "• Автоматически распределять пары Сант\n"
            "• Хранить пожелания участников\n\n"
            "🎯 *Быстрый старт:*\n"
            "1. Нажми *«Создать игру»*\n"
            "2. Укажи название игры\n"
            "3. Отправь друзьям ссылку-приглашение\n"
            "4. Запусти игру командой /startgame\n\n"
            "Или используй кнопки ниже ⬇️",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    @worker_dp.message_handler(commands=['help'])
    async def handle_help(message: types.Message):
        help_text = """
🎅 *ТАЙНЫЙ САНТА - ПОЛНАЯ СПРАВКА*

*Основные команды:*
/start - Начать работу с ботом (поддерживает deep-link)
/help - Показать эту справку

*🎮 Управление игрой:*
/newgame - Создать новую игру
/mygames - Список ваших игр
/gameinfo [код] - Информация об игре
/startgame - Запустить игру (только создатель)
/finishgame - Завершить игру (только создатель)

*🤝 Участие в игре:*
/join [код] - Присоединиться к игре (альтернатива ссылке)
/players - Список участников текущей игры

*🎁 Подарки:*
/wish [текст] - Указать пожелания
/mytarget - Кому я дарю подарок?

*📊 Информация:*
/status - Статус бота и статистика

*💡 Приглашение:*
Отправляйте ссылку вида:
https://t.me/{BOT_USERNAME}?start=join_КОД_ИГРЫ
        """.replace("{BOT_USERNAME}", BOT_USERNAME)
        await worker_bot.send_message(message.chat.id, help_text, parse_mode="Markdown")

    # ---------- СОЗДАНИЕ ИГРЫ ----------
    @worker_dp.message_handler(commands=['newgame', 'new_game'])
    async def handle_new_game(message: types.Message):
        pending_new_game[message.from_user.id] = True
        await worker_bot.send_message(
            chat_id=message.chat.id,
            text="🎄 *Создаём новую игру Тайного Санты!*\n\n"
                 "Введите *название* для вашей игры:\n"
                 "(например: 'Семейный Новый Год' или 'Корпоратив 2025')",
            parse_mode="Markdown"
        )

    # ---------- ЗАПУСК И ЗАВЕРШЕНИЕ ИГРЫ ----------
    @worker_dp.message_handler(commands=['startgame', 'start_game'])
    async def handle_start_game_command(message: types.Message):
        user_id = message.from_user.id
        current_game = players_db.get(user_id, {}).get('current_game')
        if not current_game:
            await worker_bot.send_message(message.chat.id, "❌ Вы не участвуете в игре.\nСоздайте игру (/newgame) или присоединитесь (/join).")
            return
        
        success, result = GameManager.start_game(current_game, user_id)
        if success:
            game = games_db[current_game]
            # Уведомляем всех участников о целях
            for participant_id in game['participants']:
                target_info, _ = GameManager.get_my_target(participant_id)
                if target_info:
                    await worker_bot.send_message(
                        participant_id,
                        f"🎉 *Игра началась!*\n\n"
                        f"🎮 Игра: {game['name']}\n"
                        f"🎅 Вы — Тайный Санта для: {target_info['name']}\n\n"
                        f"🎁 Пожелания получателя:\n{target_info['wishlist']}",
                        parse_mode="Markdown"
                    )
            await worker_bot.send_message(message.chat.id, "✅ Игра началась! Пары распределены.", parse_mode="Markdown")
        else:
            await worker_bot.send_message(message.chat.id, f"❌ {result}")

    @worker_dp.message_handler(commands=['finishgame', 'finish_game'])
    async def handle_finish_game(message: types.Message):
        user_id = message.from_user.id
        current_game = players_db.get(user_id, {}).get('current_game')
        if not current_game:
            await worker_bot.send_message(message.chat.id, "❌ Вы не участвуете в игре.")
            return
        success, result = GameManager.finish_game(current_game, user_id)
        if success:
            game = games_db[current_game]
            for participant_id in game['participants']:
                await worker_bot.send_message(
                    participant_id,
                    f"✅ Игра *{game['name']}* завершена!\nСпасибо за участие 🎄",
                    parse_mode="Markdown"
                )
        await worker_bot.send_message(message.chat.id, f"{'✅' if success else '❌'} {result}")

    # ---------- УЧАСТИЕ ----------
    @worker_dp.message_handler(commands=['join'])
    async def handle_join_command(message: types.Message):
        text = message.text.strip()
        parts = text.split()
        if len(parts) < 2:
            await worker_bot.send_message(message.chat.id, "❌ Укажите код игры: `/join ABC123XY`", parse_mode="Markdown")
            return
        game_code = parts[1].upper()
        success, result = GameManager.join_game(game_code, message.from_user.id, message.from_user.first_name)
        if success:
            game = GameManager.get_game_info(game_code)
            await worker_bot.send_message(
                message.chat.id,
                f"✅ Вы присоединились к игре *{game['name']}*\n"
                f"🔑 Код: `{game_code}`\n"
                f"Ссылка-приглашение для друзей:\n{games_db[game_code]['invite_link']}",
                parse_mode="Markdown"
            )
        else:
            await worker_bot.send_message(message.chat.id, f"❌ {result}")

    @worker_dp.message_handler(commands=['players'])
    async def handle_players_command(message: types.Message):
        user_id = message.from_user.id
        current_game = players_db.get(user_id, {}).get('current_game')
        if not current_game or current_game not in games_db:
            await worker_bot.send_message(message.chat.id, "❌ Вы не участвуете в игре.")
            return
        game = games_db[current_game]
        response = f"👥 *Участники игры '{game['name']}':*\n\n"
        for i, participant_id in enumerate(game['participants'], 1):
            username = players_db.get(participant_id, {}).get('username', 'Неизвестно')
            is_creator = participant_id == game['creator_id']
            has_wishlist = participant_id in game['wishlists']
            response += f"{i}. {username}{' 👑' if is_creator else ''}{' 📝' if has_wishlist else ' ❔'}\n"
        await worker_bot.send_message(message.chat.id, response, parse_mode="Markdown")

    # ---------- ПОДАРКИ И ЦЕЛИ ----------
    @worker_dp.message_handler(commands=['wish'])
    async def handle_wish_command(message: types.Message):
        text = message.text.strip()
        if len(text) < 6:
            await worker_bot.send_message(message.chat.id, "❌ Укажите ваши пожелания:\n`/wish Хочу новую книгу фэнтези`", parse_mode="Markdown")
            return
        wishlist_text = text[6:]
        success, result = GameManager.set_wishlist(message.from_user.id, wishlist_text)
        await worker_bot.send_message(message.chat.id, f"{'✅' if success else '❌'} {result}", parse_mode="Markdown")

    @worker_dp.message_handler(commands=['mytarget', 'my_target'])
    async def handle_my_target_command(message: types.Message):
        target_info, status = GameManager.get_my_target(message.from_user.id)
        if target_info:
            await worker_bot.send_message(
                message.chat.id,
                f"🎅 *Ваш получатель:*\n\n"
                f"👤 Имя: {target_info['name']}\n"
                f"🎁 Пожелания:\n{target_info['wishlist']}",
                parse_mode="Markdown"
            )
        else:
            await worker_bot.send_message(message.chat.id, f"❌ {status}")

    # ---------- ИНФО ----------
    @worker_dp.message_handler(commands=['mygames', 'my_games'])
    async def handle_my_games_command(message: types.Message):
        games_list = user_games.get(message.from_user.id, [])
        if not games_list:
            await worker_bot.send_message(message.chat.id, "❌ У вас пока нет игр.\nСоздайте первую игру через /newgame или присоединитесь по ссылке/коду.")
            return
        response = "🎮 *Ваши игры:*\n\n"
        for i, game_id in enumerate(games_list[:10], 1):
            game = games_db.get(game_id)
            if not game: 
                continue
            status_emoji = {'waiting': '⏳', 'active': '🎁', 'finished': '✅'}.get(game['status'], '❓')
            response += (
                f"{i}. {status_emoji} *{game['name']}*\n"
                f"   Код: `{game_id}`\n"
                f"   Статус: {game['status']}\n"
                f"   Участников: {len(game['participants'])}\n"
                f"   Ссылка: {game['invite_link']}\n\n"
            )
        await worker_bot.send_message(message.chat.id, response, parse_mode="Markdown")

    @worker_dp.message_handler(commands=['gameinfo', 'game_info'])
    async def handle_game_info_command(message: types.Message):
        parts = message.text.strip().split()
        if len(parts) < 2:
            user_id = message.from_user.id
            current_game = players_db.get(user_id, {}).get('current_game')
            if not current_game:
                await worker_bot.send_message(message.chat.id, "❌ Вы не участвуете в игре.\nУкажите код: `/gameinfo ABC123XY`", parse_mode="Markdown")
                return
            game_code = current_game
        else:
            game_code = parts[1].upper()
        
        game = GameManager.get_game_info(game_code)
        if not game:
            await worker_bot.send_message(message.chat.id, f"❌ Игра с кодом `{game_code}` не найдена", parse_mode="Markdown")
            return
        
        status_text = {'waiting': '⏳ Ожидание игроков', 'active': '🎁 Игра началась', 'finished': '✅ Игра завершена'}.get(game['status'], game['status'])
        response = (
            f"🎮 *Информация об игре*\n\n"
            f"📝 Название: {game['name']}\n"
            f"🔑 Код: `{game['id']}`\n"
            f"👑 Создатель: {game['creator_name']}\n"
            f"📌 Статус: {status_text}\n"
            f"💰 Бюджет: {game['budget']}\n"
            f"📅 Создана: {game['created_at'][:10]}\n"
            f"👥 Участников: {len(game['participants_info'])}\n"
        )
        if game['status'] == 'waiting':
            response += "\n*Участники:*\n"
            for i, p in enumerate(game['participants_info'], 1):
                response += f"{i}. {p['name']} {'📝' if p['has_wishlist'] else '❔'}\n"
            response += f"\n*Ссылка для присоединения:*\nhttps://t.me/{BOT_USERNAME}?start=join_{game['id']}"
        elif game['status'] == 'active':
            response += "\n🎅 Игра началась! Узнайте своего получателя: /mytarget"
        await worker_bot.send_message(message.chat.id, response, parse_mode="Markdown")

    @worker_dp.message_handler(commands=['status'])
    async def handle_status_command(message: types.Message):
        total_games = len(games_db)
        active_games = sum(1 for g in games_db.values() if g['status'] == 'active')
        waiting_games = sum(1 for g in games_db.values() if g['status'] == 'waiting')
        total_players = len(players_db)
        response = (
            f"📊 *Статус бота:*\n\n"
            f"🎮 Всего игр: {total_games}\n"
            f"🎁 Активных игр: {active_games}\n"
            f"⏳ Ожидающих игр: {waiting_games}\n"
            f"👤 Уникальных игроков: {total_players}\n"
            f"🔄 Очередь сообщений: {update_queue.qsize()}\n"
            f"⚙️ Фоновый воркер: {'✅ работает' if 'worker_thread' in globals() and worker_thread.is_alive() else '❌ остановлен'}\n"
        )
        await worker_bot.send_message(message.chat.id, response, parse_mode="Markdown")

    # ---------- КНОПКИ ----------
    @worker_dp.message_handler(lambda m: m.text == "🎮 Создать игру")
    async def handle_create_game_button(message: types.Message):
        await handle_new_game(message)
    
    @worker_dp.message_handler(lambda m: m.text == "🎅 Присоединиться")
    async def handle_join_button(message: types.Message):
        await worker_bot.send_message(
            message.chat.id,
            "Для присоединения к игре просто нажмите на ссылку, которую прислал создатель.\n"
            "Также можно использовать команду:\n`/join КОД_ИГРЫ`",
            parse_mode="Markdown"
        )
    
    @worker_dp.message_handler(lambda m: m.text == "📋 Мои игры")
    async def handle_my_games_button(message: types.Message):
        await handle_my_games_command(message)
    
    @worker_dp.message_handler(lambda m: m.text == "❓ Помощь")
    async def handle_help_button(message: types.Message):
        await handle_help(message)

    # ---------- ОБРАБОТКА ПРОЧИХ СООБЩЕНИЙ ----------
    @worker_dp.message_handler()
    async def handle_all_messages(message: types.Message):
        user_id = message.from_user.id
        text = message.text.strip()
        
        # Пользователь вводит название новой игры
        if pending_new_game.get(user_id):
            game = GameManager.create_game(user_id, message.from_user.first_name, text)
            del pending_new_game[user_id]

            response = (
                f"🎉 *Игра создана!*\n\n"
                f"📝 Название: {game['name']}\n"
                f"🔑 Код игры: `{game['id']}`\n"
                f"👑 Создатель: {game['creator_name']}\n"
                f"👥 Участников: 1\n"
                f"📌 Статус: Ожидание игроков\n"
                f"💰 Бюджет: {game['budget']}\n\n"
                f"Отправьте друзьям ссылку:\n{game['invite_link']}\n\n"
                f"Когда все присоединятся, нажмите /startgame"
            )
            await worker_bot.send_message(message.chat.id, response, parse_mode="Markdown")
            return
        
        # Если сообщение похоже на код игры (8 символов)
        if len(text) == 8 and all(c.isalnum() for c in text.upper()):
            await worker_bot.send_message(
                message.chat.id,
                f"🔍 Обнаружен код: `{text.upper()}`\n\n"
                f"Присоединиться:\nhttps://t.me/{BOT_USERNAME}?start=join_{text.upper()}\n\n"
                f"Информация об игре:\n`/gameinfo {text.upper()}`",
                parse_mode="Markdown"
            )
            return

        # Если пользователь в игре и игра еще не началась — считаем текст пожеланиями
        if user_id in players_db and players_db[user_id].get('current_game'):
            current_game = players_db[user_id]['current_game']
            if current_game in games_db and games_db[current_game]['status'] == 'waiting':
                success, result = GameManager.set_wishlist(user_id, text)
                if success:
                    await worker_bot.send_message(
                        message.chat.id,
                        f"✅ {result}\n\n"
                        f"*Ваши пожелания:*\n{text}\n\n"
                        f"Изменить пожелания: `/wish Новые пожелания`",
                        parse_mode="Markdown"
                    )
                else:
                    await worker_bot.send_message(message.chat.id, f"❌ {result}")
                return

        # Обычный ответ
        await worker_bot.send_message(
            message.chat.id,
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            f"Вы написали: *{message.text}*\n\n"
            f"Я — бот для игры *Тайный Санта* 🎅\n"
            f"Используйте /help для списка команд\n"
            f"Или выберите действие в меню ниже:",
            parse_mode="Markdown"
        )
    
    # ---------- ЦИКЛ ОБРАБОТКИ ОЧЕРЕДИ ----------
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    logger.info("✅ Фоновый воркер запущен")
    
    try:
        while True:
            try:
                update_data = update_queue.get(timeout=1)
                update_id = update_data.get('update_id', 'unknown')
                try:
                    from aiogram import types as aio_types
                    update = aio_types.Update(**update_data)
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
    """Основной обработчик вебхуков Telegram"""
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
    return f"""
    🎅 Бот 'Тайный Санта' работает на Railway!<br>
    Статус: ONLINE<br><br>
    <a href='/set_webhook'>Установить вебхук</a><br>
    <a href='/delete_webhook'>Удалить вебхук</a><br>
    <a href='/status'>Статус API</a><br>
    <a href='/stats'>Статистика</a><br><br>
    Текущий вебхук: {WEBHOOK_URL}
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
    return jsonify({
        'status': 'online',
        'service': 'Secret Santa Bot',
        'timestamp': datetime.now().isoformat(),
        'webhook_url': WEBHOOK_URL,
        'queue_size': update_queue.qsize(),
        'background_worker': worker_thread.is_alive() if 'worker_thread' in globals() else False,
        'total_games': len(games_db),
        'active_games': sum(1 for g in games_db.values() if g['status'] == 'active'),
        'waiting_games': sum(1 for g in games_db.values() if g['status'] == 'waiting'),
        'finished_games': sum(1 for g in games_db.values() if g['status'] == 'finished'),
        'total_players': len(players_db)
    })

@app.route('/stats')
def stats():
    """Страница статистики"""
    active_games = sum(1 for g in games_db.values() if g['status'] == 'active')
    waiting_games = sum(1 for g in games_db.values() if g['status'] == 'waiting')
    finished_games = sum(1 for g in games_db.values() if g['status'] == 'finished')
    return f"""
    <h1>🎅 Статистика Тайного Санты</h1>
    <p>Всего игр: {len(games_db)}</p>
    <p>Активных игр: {active_games}</p>
    <p>Ожидающих игр: {waiting_games}</p>
    <p>Завершенных игр: {finished_games}</p>
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
