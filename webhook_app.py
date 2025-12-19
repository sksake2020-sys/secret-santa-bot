# webhook_app.py - ПОЛНАЯ РАБОЧАЯ ВЕРСИЯ С DEEP-LINK И БЕЗОПАСНЫМ ВЫВОДОМ
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

# ============== НАСТРОЙКИ ==============
BOT_TOKEN = os.environ.get('BOT_TOKEN')
BOT_USERNAME = os.environ.get('BOT_USERNAME')  # имя бота без @, например TainiSantaBot
if not BOT_TOKEN or not BOT_USERNAME:
    raise ValueError("BOT_TOKEN и BOT_USERNAME должны быть установлены!")

RAILWAY_STATIC_URL = os.environ.get('RAILWAY_STATIC_URL')
WEBHOOK_HOST = RAILWAY_STATIC_URL or "https://web-production-1a5d8.up.railway.app"
if not WEBHOOK_HOST.startswith('http'):
    WEBHOOK_HOST = f"https://{WEBHOOK_HOST}"

WEBHOOK_PATH = f'/webhook/{BOT_TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

# ============== БАЗА ДАННЫХ В ПАМЯТИ ==============
games_db = {}           # {game_id: game_data}
players_db = {}         # {user_id: {username, games[], current_game}}
game_participants = {}  # {game_id: [user_id1, ...]}
user_games = {}         # {user_id: [game_id1, ...]}

# ============== ЛОГИКА ИГРЫ ==============
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
            'status': 'waiting',  # waiting | active | finished
            'created_at': datetime.now().isoformat(),
            'started_at': None,
            'participants': [creator_id],
            'wishlists': {},  # {user_id: text}
            'pairs': {},      # {santa_id: receiver_id}
            'invite_link': invite_link
        }
        games_db[game_id] = game_data
        game_participants[game_id] = [creator_id]
        user_games.setdefault(creator_id, []).append(game_id)
        players_db[creator_id] = {
            'username': creator_name,
            'games': user_games[creator_id],
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
        game['participants'].append(user_id)
        game_participants[game_id].append(user_id)
        user_games.setdefault(user_id, []).append(game_id)
        players_db[user_id] = {
            'username': username,
            'games': user_games[user_id],
            'current_game': game_id
        }
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
        pairs = {participants[i]: participants[(i + 1) % len(participants)] for i in range(len(participants))}
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
            return False, "Игра уже началась, пожелания закрыты"
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
        target_id = game['pairs'].get(user_id)
        if not target_id:
            return None, "Пара не найдена"
        target_name = players_db.get(target_id, {}).get('username', 'Неизвестный игрок')
        wishlist = game['wishlists'].get(target_id, "Пожелания не указаны")
        return {'id': target_id, 'name': target_name, 'wishlist': wishlist}, "Найдено"

    @staticmethod
    def get_game_info(game_id):
        if game_id not in games_db:
            return None
        game = games_db[game_id].copy()
        if 'pairs' in game:
            del game['pairs']
        participants_info = []
        for uid in game['participants']:
            uname = players_db.get(uid, {}).get('username', 'Неизвестно')
            participants_info.append({
                'id': uid,
                'name': uname,
                'has_wishlist': uid in game['wishlists']
            })
        game['participants_info'] = participants_info
        return game

# ============== ОЧЕРЕДЬ ОБНОВЛЕНИЙ ==============
update_queue = queue.Queue()

# ============== ФОНОВЫЙ ВОРКЕР ==============
def background_worker():
    """Фоновая обработка апдейтов из очереди"""
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.fsm_storage.memory import MemoryStorage

    bot = Bot(token=BOT_TOKEN)
    types.Bot.set_current(bot)
    dp = Dispatcher(bot, MemoryStorage())

    pending_new_game = {}  # {user_id: True}

    # ---------- START / HELP ----------
    @dp.message_handler(commands=['start'])
    async def handle_start(message: types.Message):
        args = message.get_args()
        if args and args.startswith("join_"):
            game_code = args.replace("join_", "").upper()
            success, result = GameManager.join_game(game_code, message.from_user.id, message.from_user.first_name)
            if success:
                game = games_db[game_code]
                await bot.send_message(message.chat.id, f"Вы присоединились к игре: {game['name']}\nКод: {game_code}")
                await bot.send_message(message.chat.id, "Укажите ваши пожелания командой:\n/wish Ваши пожелания")
            else:
                await bot.send_message(message.chat.id, f"Ошибка: {result}")
            return

        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.row(types.KeyboardButton("🎮 Создать игру"), types.KeyboardButton("🎅 Присоединиться"))
        keyboard.row(types.KeyboardButton("❓ Помощь"), types.KeyboardButton("📋 Мои игры"))
        await bot.send_message(
            message.chat.id,
            "Привет! Это бот Тайный Санта.\n\n"
            "Создавай игру, приглашай друзей ссылкой и запускай жеребьевку.\n"
            "Используй кнопки ниже или команду /help.",
            reply_markup=keyboard
        )

    @dp.message_handler(commands=['help'])
    async def handle_help(message: types.Message):
        await bot.send_message(
            message.chat.id,
            "Команды:\n"
            "/newgame — создать игру\n"
            "/join CODE — присоединиться по коду (или нажать ссылку)\n"
            "/startgame — начать игру (создатель)\n"
            "/finishgame — завершить игру (создатель)\n"
            "/wish TEXT — указать пожелания\n"
            "/mytarget — узнать получателя\n"
            "/mygames — список ваших игр\n"
            "/gameinfo CODE — информация об игре\n"
            "/players — участники текущей игры\n"
            "/status — статус бота\n\n"
            f"Приглашение формата:\nhttps://t.me/{BOT_USERNAME}?start=join_<КОД>"
        )

    # ---------- СОЗДАНИЕ ИГРЫ ----------
    @dp.message_handler(commands=['newgame'])
    async def handle_newgame(message: types.Message):
        pending_new_game[message.from_user.id] = True
        await bot.send_message(message.chat.id, "Введите название игры:")

    # ---------- УПРАВЛЕНИЕ ИГРОЙ ----------
    @dp.message_handler(commands=['startgame'])
    async def handle_startgame(message: types.Message):
        uid = message.from_user.id
        current_game = players_db.get(uid, {}).get('current_game')
        if not current_game:
            await bot.send_message(message.chat.id, "Вы не участвуете ни в одной игре.")
            return
        success, result = GameManager.start_game(current_game, uid)
        if success:
            game = games_db[current_game]
            # оповещения участникам
            for pid in game['participants']:
                target, _ = GameManager.get_my_target(pid)
                if target:
                    await bot.send_message(pid, f"Игра '{game['name']}' началась!\nВы — Тайный Санта для: {target['name']}\nПожелания: {target['wishlist']}")
            await bot.send_message(message.chat.id, "Игра началась! Пары распределены.")
        else:
            await bot.send_message(message.chat.id, f"Ошибка: {result}")

    @dp.message_handler(commands=['finishgame'])
    async def handle_finishgame(message: types.Message):
        uid = message.from_user.id
        current_game = players_db.get(uid, {}).get('current_game')
        if not current_game:
            await bot.send_message(message.chat.id, "Вы не участвуете ни в одной игре.")
            return
        success, result = GameManager.finish_game(current_game, uid)
        if success:
            game = games_db[current_game]
            for pid in game['participants']:
                await bot.send_message(pid, f"Игра '{game['name']}' завершена. Спасибо за участие!")
        await bot.send_message(message.chat.id, f"{'Готово: ' if success else 'Ошибка: '}{result}")

    # ---------- УЧАСТИЕ ----------
    @dp.message_handler(commands=['join'])
    async def handle_join(message: types.Message):
        parts = message.text.split()
        if len(parts) < 2:
            await bot.send_message(message.chat.id, "Укажите код: /join ABC123XY")
            return
        code = parts[1].upper()
        success, result = GameManager.join_game(code, message.from_user.id, message.from_user.first_name)
        if success:
            game = games_db[code]
            await bot.send_message(message.chat.id, f"Вы присоединились к игре: {game['name']}\nСсылка для друзей:\n{game['invite_link']}")
        else:
            await bot.send_message(message.chat.id, f"Ошибка: {result}")

    @dp.message_handler(commands=['players'])
    async def handle_players(message: types.Message):
        uid = message.from_user.id
        current_game = players_db.get(uid, {}).get('current_game')
        if not current_game or current_game not in games_db:
            await bot.send_message(message.chat.id, "Вы не участвуете в игре.")
            return
        game = games_db[current_game]
        lines = [f"Участники игры '{game['name']}':"]
        for i, pid in enumerate(game['participants'], 1):
            uname = players_db.get(pid, {}).get('username', 'Неизвестно')
            creator_mark = " 👑" if pid == game['creator_id'] else ""
            wishlist_mark = " 📝" if pid in game['wishlists'] else " ❔"
            lines.append(f"{i}. {uname}{creator_mark}{wishlist_mark}")
        await bot.send_message(message.chat.id, "\n".join(lines))

    # ---------- ПОДАРКИ ----------
    @dp.message_handler(commands=['wish'])
    async def handle_wish(message: types.Message):
        text = message.text.strip()
        wishlist = text[6:].strip() if len(text) > 6 else ""
        if not wishlist:
            await bot.send_message(message.chat.id, "Укажите пожелания: /wish Хочу книгу")
            return
        success, result = GameManager.set_wishlist(message.from_user.id, wishlist)
        await bot.send_message(message.chat.id, f"{'Готово: ' if success else 'Ошибка: '}{result}")

    @dp.message_handler(commands=['mytarget'])
    async def handle_mytarget(message: types.Message):
        target, status = GameManager.get_my_target(message.from_user.id)
        if target:
            await bot.send_message(message.chat.id, f"Ваш получатель: {target['name']}\nПожелания: {target['wishlist']}")
        else:
            await bot.send_message(message.chat.id, f"Ошибка: {status}")

    # ---------- ИНФО ----------
    @dp.message_handler(commands=['mygames'])
    async def handle_mygames(message: types.Message):
        games_list = user_games.get(message.from_user.id, [])
        if not games_list:
            await bot.send_message(message.chat.id, "У вас пока нет игр.")
            return
        lines = ["Ваши игры:"]
        for gid in games_list:
            g = games_db.get(gid)
            if not g:
                continue
            lines.append(f"- {g['name']} (код: {gid}, статус: {g['status']})\n  Ссылка: {g['invite_link']}")
        await bot.send_message(message.chat.id, "\n".join(lines))

    @dp.message_handler(commands=['gameinfo'])
    async def handle_gameinfo(message: types.Message):
        parts = message.text.split()
        if len(parts) < 2:
            uid = message.from_user.id
            current_game = players_db.get(uid, {}).get('current_game')
            if not current_game:
                await bot.send_message(message.chat.id, "Укажите код: /gameinfo ABC123XY")
                return
            code = current_game
        else:
            code = parts[1].upper()
        game = GameManager.get_game_info(code)
        if not game:
            await bot.send_message(message.chat.id, f"Игра {code} не найдена")
            return
        status_map = {'waiting': 'Ожидание игроков', 'active': 'Игра началась', 'finished': 'Игра завершена'}
        lines = [
            f"Игра: {game['name']}",
            f"Код: {game['id']}",
            f"Создатель: {game['creator_name']}",
            f"Статус: {status_map.get(game['status'], game['status'])}",
            f"Бюджет: {game['budget']}",
            f"Создана: {game['created_at'][:10]}",
            f"Участников: {len(game['participants_info'])}",
        ]
        if game['status'] == 'waiting':
            lines.append("Участники:")
            for p in game['participants_info']:
                lines.append(f"- {p['name']} {'📝' if p['has_wishlist'] else '❔'}")
            lines.append(f"Ссылка для присоединения:\nhttps://t.me/{BOT_USERNAME}?start=join_{game['id']}")
        elif game['status'] == 'active':
            lines.append("Игра началась! Узнайте своего получателя: /mytarget")
        await bot.send_message(message.chat.id, "\n".join(lines))

    @dp.message_handler(commands=['status'])
    async def handle_status(message: types.Message):
        total_games = len(games_db)
        active_games = sum(1 for g in games_db.values() if g['status'] == 'active')
        waiting_games = sum(1 for g in games_db.values() if g['status'] == 'waiting')
        finished_games = sum(1 for g in games_db.values() if g['status'] == 'finished')
        total_players = len(players_db)
        await bot.send_message(
            message.chat.id,
            "Статус бота:\n"
            f"- Всего игр: {total_games}\n"
            f"- Активных: {active_games}\n"
            f"- Ожидающих: {waiting_games}\n"
            f"- Завершенных: {finished_games}\n"
            f"- Уникальных игроков: {total_players}\n"
            f"- Очередь сообщений: {update_queue.qsize()}"
        )

    # ---------- КНОПКИ ----------
    @dp.message_handler(lambda m: m.text == "🎮 Создать игру")
    async def handle_create_game_button(message: types.Message):
        await handle_newgame(message)

    @dp.message_handler(lambda m: m.text == "🎅 Присоединиться")
    async def handle_join_button(message: types.Message):
        await bot.send_message(
            message.chat.id,
            "Для присоединения просто нажмите на ссылку от создателя.\n"
            "Либо используйте команду: /join КОД_ИГРЫ"
        )

    @dp.message_handler(lambda m: m.text == "📋 Мои игры")
    async def handle_my_games_button(message: types.Message):
        await handle_mygames(message)

    @dp.message_handler(lambda m: m.text == "❓ Помощь")
    async def handle_help_button(message: types.Message):
        await handle_help(message)

    # ---------- ПРОЧИЕ СООБЩЕНИЯ ----------
    @dp.message_handler()
    async def handle_all_messages(message: types.Message):
        uid = message.from_user.id
        text = (message.text or "").strip()

        # Пользователь вводит название новой игры
        if pending_new_game.get(uid):
            game = GameManager.create_game(uid, message.from_user.first_name, text)
            del pending_new_game[uid]
            await bot.send_message(
                message.chat.id,
                "Игра создана!\n"
                f"Название: {game['name']}\n"
                f"Код: {game['id']}\n"
                f"Ссылка для друзей:\n{game['invite_link']}\n\n"
                "Когда все присоединятся, нажмите /startgame"
            )
            return

        # Если сообщение похоже на код (8 алфанумерических символов)
        if len(text) == 8 and text.isalnum():
            await bot.send_message(
                message.chat.id,
                "Похоже на код игры.\n"
                f"Присоединиться:\nhttps://t.me/{BOT_USERNAME}?start=join_{text.upper()}\n"
                f"Информация:\n/gameinfo {text.upper()}"
            )
            return

        # Если пользователь в ожидании — считаем текст пожеланиями
        current_game = players_db.get(uid, {}).get('current_game')
        if current_game and games_db.get(current_game, {}).get('status') == 'waiting':
            success, result = GameManager.set_wishlist(uid, text)
            if success:
                await bot.send_message(message.chat.id, "Пожелания сохранены!")
            else:
                await bot.send_message(message.chat.id, f"Ошибка: {result}")
            return

        await bot.send_message(
            message.chat.id,
            "Я бот Тайный Санта. Используйте /help для списка команд."
        )

    # ---------- ЦИКЛ ОБРАБОТКИ ОЧЕРЕДИ ----------
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    logger.info("Фоновый воркер запущен")

    try:
        while True:
            try:
                update_data = update_queue.get(timeout=1)
                update_id = update_data.get('update_id', 'unknown')
                try:
                    from aiogram import types as aio_types
                    update = aio_types.Update(**update_data)
                    loop.run_until_complete(dp.process_update(update))
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
        logger.info("Фоновый воркер завершен")
        loop.close()

# Запускаем фоновый воркер
worker_thread = threading.Thread(target=background_worker, daemon=True)
worker_thread.start()
logger.info("✅ Фоновый поток запущен")

# ============== FLASK РОУТЫ ==============
@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
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
    🎅 Бот 'Тайный Санта' работает!<br>
    Вебхук: {WEBHOOK_URL}<br><br>
    <a href='/set_webhook'>Установить вебхук</a><br>
    <a href='/delete_webhook'>Удалить вебхук</a><br>
    <a href='/status'>Статус API</a><br>
    <a href='/stats'>Статистика</a><br>
    """

@app.route('/set_webhook')
def set_webhook():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        from aiogram import Bot
        temp_bot = Bot(token=BOT_TOKEN)
        loop.run_until_complete(temp_bot.set_webhook(WEBHOOK_URL))
        loop.close()
        logger.info(f"✅ Вебхук установлен: {WEBHOOK_URL}")
        return f"✅ Вебхук установлен! URL: {WEBHOOK_URL}"
    except Exception as e:
        logger.error(f"❌ Ошибка установки вебхука: {e}")
        return f"❌ Ошибка: {str(e)}"

@app.route('/delete_webhook')
def delete_webhook():
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
    return jsonify({
        'status': 'online',
        'service': 'Secret Santa Bot',
        'timestamp': datetime.now().isoformat(),
        'webhook_url': WEBHOOK_URL,
        'queue_size': update_queue.qsize(),
        'background_worker': worker_thread.is_alive(),
        'total_games': len(games_db),
        'active_games': sum(1 for g in games_db.values() if g['status'] == 'active'),
        'waiting_games': sum(1 for g in games_db.values() if g['status'] == 'waiting'),
        'finished_games': sum(1 for g in games_db.values() if g['status'] == 'finished'),
        'total_players': len(players_db)
    })

@app.route('/stats')
def stats():
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
