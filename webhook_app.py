# webhook_app.py - Полный рабочий файл с новогодним оформлением
from flask import Flask, request, jsonify
import asyncio
import logging
import os
import queue
import threading
import time
import random
import string
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Настройки (установи в окружении) ----------
BOT_TOKEN = os.environ.get('BOT_TOKEN')
BOT_USERNAME = os.environ.get('BOT_USERNAME')  # имя бота без @
if not BOT_TOKEN or not BOT_USERNAME:
    raise ValueError("BOT_TOKEN и BOT_USERNAME должны быть установлены в переменных окружения")

RAILWAY_STATIC_URL = os.environ.get('RAILWAY_STATIC_URL')
WEBHOOK_HOST = RAILWAY_STATIC_URL or "https://example.com"  # замени на свой хост при необходимости
if not WEBHOOK_HOST.startswith('http'):
    WEBHOOK_HOST = f"https://{WEBHOOK_HOST}"
WEBHOOK_PATH = f'/webhook/{BOT_TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

# ---------- Хранилище в памяти ----------
games_db = {}           # {game_id: game_data}
players_db = {}         # {user_id: player_data}
game_participants = {}  # {game_id: [user_id, ...]}
user_games = {}         # {user_id: [game_id, ...]}

# ---------- Менеджер игры ----------
class GameManager:
    @staticmethod
    def generate_game_id():
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

    @staticmethod
    def create_game(creator_id, creator_name, game_name, budget=None):
        game_id = GameManager.generate_game_id()
        invite_link = f"https://t.me/{BOT_USERNAME}?start=join_{game_id}"
        game = {
            'id': game_id,
            'name': game_name,
            'creator_id': creator_id,
            'creator_name': creator_name,
            'budget': budget or "🎁 Без ограничений",
            'status': 'waiting',  # waiting | active | finished
            'created_at': datetime.now().isoformat(),
            'started_at': None,
            'participants': [creator_id],
            'wishlists': {},  # {user_id: text}
            'pairs': {},      # {santa_id: receiver_id}
            'invite_link': invite_link
        }
        games_db[game_id] = game
        game_participants[game_id] = [creator_id]
        user_games.setdefault(creator_id, []).append(game_id)
        players_db[creator_id] = {
            'username': creator_name,
            'games': user_games[creator_id],
            'current_game': game_id
        }
        return game

    @staticmethod
    def join_game(game_id, user_id, username):
        if game_id not in games_db:
            return False, "❌ Игра не найдена"
        game = games_db[game_id]
        if game['status'] != 'waiting':
            return False, "⏳ Игра уже началась или завершена"
        if user_id in game['participants']:
            return False, "🎅 Вы уже участвуете в этой игре"
        game['participants'].append(user_id)
        game_participants[game_id].append(user_id)
        user_games.setdefault(user_id, []).append(game_id)
        players_db[user_id] = {
            'username': username,
            'games': user_games[user_id],
            'current_game': game_id
        }
        return True, "🎉 Вы присоединились к праздничной игре!"

    @staticmethod
    def start_game(game_id, creator_id):
        if game_id not in games_db:
            return False, "❌ Игра не найдена"
        game = games_db[game_id]
        if game['creator_id'] != creator_id:
            return False, "👑 Только создатель может начать игру"
        if game['status'] != 'waiting':
            return False, "⏳ Игра уже началась"
        if len(game['participants']) < 2:
            return False, "🎁 Нужно минимум 2 участника"
        participants = game['participants'].copy()
        random.shuffle(participants)
        pairs = {participants[i]: participants[(i + 1) % len(participants)] for i in range(len(participants))}
        game['pairs'] = pairs
        game['status'] = 'active'
        game['started_at'] = datetime.now().isoformat()
        return True, "🎄 Игра началась! Тайные Санты распределены 🎅"

    @staticmethod
    def finish_game(game_id, user_id):
        if game_id not in games_db:
            return False, "❌ Игра не найдена"
        game = games_db[game_id]
        if game['creator_id'] != user_id:
            return False, "👑 Только создатель может завершить игру"
        if game['status'] != 'active':
            return False, "⏳ Игра еще не началась или уже завершена"
        game['status'] = 'finished'
        return True, "✅ Игра завершена! Спасибо за участие 🎁✨"

    @staticmethod
    def set_wishlist(user_id, wishlist_text):
        if user_id not in players_db:
            return False, "❌ Вы не участвуете в играх"
        current_game = players_db[user_id].get('current_game')
        if not current_game or current_game not in games_db:
            return False, "❌ Вы не в активной игре"
        game = games_db[current_game]
        if game['status'] == 'active':
            return False, "⏳ Игра уже началась, пожелания закрыты"
        game['wishlists'][user_id] = wishlist_text
        return True, "📝 Ваши пожелания сохранены 🎄"

    @staticmethod
    def get_my_target(user_id):
        if user_id not in players_db:
            return None, "❌ Вы не участвуете в играх"
        current_game = players_db[user_id].get('current_game')
        if not current_game or current_game not in games_db:
            return None, "❌ Вы не в активной игре"
        game = games_db[current_game]
        if game['status'] != 'active':
            return None, "⏳ Игра еще не началась"
        target_id = game['pairs'].get(user_id)
        if not target_id:
            return None, "❌ Пара не найдена"
        target_name = players_db.get(target_id, {}).get('username', 'Неизвестный игрок')
        wishlist = game['wishlists'].get(target_id, "🎁 Пожелания не указаны")
        return {'id': target_id, 'name': target_name, 'wishlist': wishlist}, "🎅 Найдено"

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

# ---------- Очередь апдейтов ----------
update_queue = queue.Queue()

# ---------- Фоновый воркер (обрабатывает апдейты из очереди) ----------
def background_worker():
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.fsm_storage.memory import MemoryStorage

    async def run():
        bot = Bot(token=BOT_TOKEN)
        dp = Dispatcher(bot, storage=MemoryStorage())
        pending_new_game = {}

        # --- /start (поддерживает deep-link join_<code>) ---
        @dp.message_handler(commands=['start'])
        async def cmd_start(message: types.Message):
            args = message.get_args()
            if args and args.startswith("join_"):
                code = args.replace("join_", "").upper()
                ok, res = GameManager.join_game(code, message.from_user.id, message.from_user.first_name)
                if ok:
                    g = games_db[code]
                    await bot.send_message(
                        message.chat.id,
                        f"🎉 Вы присоединились к игре: {g['name']} 🎄\n🔑 Код: {code}\n✨ Укажите пожелания: /wish Текст"
                    )
                else:
                    await bot.send_message(message.chat.id, res)
                return
            await bot.send_message(
                message.chat.id,
                "❄️✨ Добро пожаловать в игру Тайный Санта! ✨❄️\n\n"
                "🎁 Дарите радость и сюрпризы!\n"
                "📜 Используйте /help для списка команд 🎅"
            )

        # --- /help ---
        @dp.message_handler(commands=['help'])
        async def cmd_help(message: types.Message):
            await bot.send_message(
                message.chat.id,
                "🎄 Команды Тайного Санты:\n"
                "/newgame — создать игру\n"
                "/join CODE — присоединиться\n"
                "/startgame — начать игру (только создатель)\n"
                "/finishgame — завершить игру (только создатель)\n"
                "/wish TEXT — указать пожелания\n"
                "/mytarget — узнать получателя\n"
                "/mygames — список ваших игр\n"
                "/gameinfo CODE — информация об игре\n"
                "/players — участники текущей игры\n"
                "/status — статус бота\n\n"
                f"Приглашение: https://t.me/{BOT_USERNAME}?start=join_<КОД>"
            )

        # --- /newgame ---
        @dp.message_handler(commands=['newgame'])
        async def cmd_newgame(message: types.Message):
            pending_new_game[message.from_user.id] = True
            await bot.send_message(message.chat.id, "🎄 Введите название вашей праздничной игры:")

        # --- /startgame ---
        @dp.message_handler(commands=['startgame'])
        async def cmd_startgame(message: types.Message):
            uid = message.from_user.id
            current_game = players_db.get(uid, {}).get('current_game')
            if not current_game:
                await bot.send_message(message.chat.id, "❌ Вы не участвуете в игре.")
                return
            ok, res = GameManager.start_game(current_game, uid)
            if ok:
                g = games_db[current_game]
                for pid in g['participants']:
                    target_info, _ = GameManager.get_my_target(pid)
                    if target_info:
                        await bot.send_message(
                            pid,
                            f"🎅 Игра '{g['name']}' началась!\nВы — Тайный Санта для: {target_info['name']}\n"
                            f"🎁 Пожелания: {target_info['wishlist']}"
                        )
                await bot.send_message(message.chat.id, "🎄 Игра началась! Пары распределены 🎁")
            else:
                await bot.send_message(message.chat.id, res)

        # --- /finishgame ---
        @dp.message_handler(commands=['finishgame'])
        async def cmd_finishgame(message: types.Message):
            uid = message.from_user.id
            current_game = players_db.get(uid, {}).get('current_game')
            if not current_game:
                await bot.send_message(message.chat.id, "❌ Вы не участвуете в игре.")
                return
            ok, res = GameManager.finish_game(current_game, uid)
            if ok:
                g = games_db[current_game]
                for pid in g['participants']:
                    await bot.send_message(pid, f"✅ Игра '{g['name']}' завершена! Спасибо за участие 🎄✨")
            await bot.send_message(message.chat.id, res)

        # --- /join CODE ---
        @dp.message_handler(commands=['join'])
        async def cmd_join(message: types.Message):
            parts = message.text.strip().split()
            if len(parts) < 2:
                await bot.send_message(message.chat.id, "❌ Укажите код: /join ABC123XY")
                return
            code = parts[1].upper()
            ok, res = GameManager.join_game(code, message.from_user.id, message.from_user.first_name)
            if ok:
                g = games_db[code]
                await bot.send_message(
                    message.chat.id,
                    f"🎉 Вы присоединились к игре: {g['name']}\nСсылка для друзей:\n{g['invite_link']}"
                )
            else:
                await bot.send_message(message.chat.id, res)

        # --- /players ---
        @dp.message_handler(commands=['players'])
        async def cmd_players(message: types.Message):
            uid = message.from_user.id
            current_game = players_db.get(uid, {}).get('current_game')
            if not current_game or current_game not in games_db:
                await bot.send_message(message.chat.id, "❌ Вы не участвуете в игре.")
                return
            g = games_db[current_game]
            lines = [f"👥 Участники игры '{g['name']}':"]
            for i, pid in enumerate(g['participants'], 1):
                uname = players_db.get(pid, {}).get('username', 'Неизвестно')
                creator_mark = " 👑" if pid == g['creator_id'] else ""
                wishlist_mark = " 📝" if pid in g['wishlists'] else " ❔"
                lines.append(f"{i}. {uname}{creator_mark}{wishlist_mark}")
            await bot.send_message(message.chat.id, "\n".join(lines))

        # --- /wish TEXT ---
        @dp.message_handler(commands=['wish'])
        async def cmd_wish(message: types.Message):
            text = message.text.strip()
            wishlist = text[6:].strip() if len(text) > 6 else ""
            if not wishlist:
                await bot.send_message(message.chat.id, "📝 Укажите пожелания: /wish Хочу книгу")
                return
            ok, res = GameManager.set_wishlist(message.from_user.id, wishlist)
            await bot.send_message(message.chat.id, res)

        # --- /mytarget ---
        @dp.message_handler(commands=['mytarget'])
        async def cmd_mytarget(message: types.Message):
            target, status = GameManager.get_my_target(message.from_user.id)
            if target:
                await bot.send_message(
                    message.chat.id,
                    f"🎅 Ваш получатель: {target['name']}\n🎁 Пожелания:\n{target['wishlist']}"
                )
            else:
                await bot.send_message(message.chat.id, status)

        # --- /mygames ---
        @dp.message_handler(commands=['mygames'])
        async def cmd_mygames(message: types.Message):
            games_list = user_games.get(message.from_user.id, [])
            if not games_list:
                await bot.send_message(message.chat.id, "📭 У вас пока нет игр.")
                return
            lines = ["📋 Ваши игры:"]
            for gid in games_list:
                g = games_db.get(gid)
                if not g:
                    continue
                lines.append(f"- {g['name']} (код: {gid}, статус: {g['status']})\n  Ссылка: {g['invite_link']}")
            await bot.send_message(message.chat.id, "\n".join(lines))

        # --- /gameinfo CODE ---
        @dp.message_handler(commands=['gameinfo'])
        async def cmd_gameinfo(message: types.Message):
            parts = message.text.strip().split()
            if len(parts) < 2:
                uid = message.from_user.id
                current_game = players_db.get(uid, {}).get('current_game')
                if not current_game:
                    await bot.send_message(message.chat.id, "❌ Укажите код: /gameinfo ABC123XY")
                    return
                code = current_game
            else:
                code = parts[1].upper()
            game = GameManager.get_game_info(code)
            if not game:
                await bot.send_message(message.chat.id, f"❌ Игра с кодом {code} не найдена")
                return
            status_map = {'waiting': 'Ожидание игроков', 'active': 'Игра началась', 'finished': 'Игра завершена'}
            lines = [
                f"🎮 Игра: {game['name']}",
                f"🔑 Код: {game['id']}",
                f"👑 Создатель: {game['creator_name']}",
                f"📌 Статус: {status_map.get(game['status'], game['status'])}",
                f"💰 Бюджет: {game['budget']}",
                f"📅 Создана: {game['created_at'][:10]}",
                f"👥 Участников: {len(game['participants_info'])}",
            ]
            if game['status'] == 'waiting':
                lines.append("Участники:")
                for p in game['participants_info']:
                    lines.append(f"- {p['name']} {'📝' if p['has_wishlist'] else '❔'}")
                lines.append(f"Ссылка для присоединения:\nhttps://t.me/{BOT_USERNAME}?start=join_{game['id']}")
            elif game['status'] == 'active':
                lines.append("🎅 Игра началась! Узнайте своего получателя: /mytarget")
            await bot.send_message(message.chat.id, "\n".join(lines))

        # --- /status ---
        @dp.message_handler(commands=['status'])
        async def cmd_status(message: types.Message):
            total_games = len(games_db)
            active_games = sum(1 for g in games_db.values() if g['status'] == 'active')
            waiting_games = sum(1 for g in games_db.values() if g['status'] == 'waiting')
            finished_games = sum(1 for g in games_db.values() if g['status'] == 'finished')
            total_players = len(players_db)
            await bot.send_message(
                message.chat.id,
                "📊 Статус бота:\n"
                f"- Всего игр: {total_games}\n"
                f"- Активных: {active_games}\n"
                f"- Ожидающих: {waiting_games}\n"
                f"- Завершенных: {finished_games}\n"
                f"- Уникальных игроков: {total_players}\n"
                f"- Очередь сообщений: {update_queue.qsize()}"
            )

        # --- Обработка обычных сообщений (название игры / пожелания / код) ---
        @dp.message_handler()
        async def handle_all(message: types.Message):
            uid = message.from_user.id
            text = (message.text or "").strip()

            # Если пользователь вводит название новой игры
            if uid in pending_new_game:
                game = GameManager.create_game(uid, message.from_user.first_name, text)
                del pending_new_game[uid]
                await bot.send_message(
                    message.chat.id,
                    "🎉 Игра создана!\n"
                    f"📝 Название: {game['name']}\n"
                    f"🔑 Код: {game['id']}\n"
                    f"📌 Ссылка для друзей:\n{game['invite_link']}\n\n"
                    "Когда все присоединятся, запустите жеребьёвку: /startgame"
                )
                return

            # Если сообщение похоже на код игры (8 символов)
            if len(text) == 8 and text.isalnum():
                await bot.send_message(
                    message.chat.id,
                    "🔍 Похоже на код игры.\n"
                    f"Присоединиться: https://t.me/{BOT_USERNAME}?start=join_{text.upper()}\n"
                    f"Информация: /gameinfo {text.upper()}"
                )
                return

            # Если пользователь в игре и игра в статусе waiting — считаем это пожеланиями
            current_game = players_db.get(uid, {}).get('current_game')
            if current_game and games_db.get(current_game, {}).get('status') == 'waiting':
                ok, res = GameManager.set_wishlist(uid, text)
                await bot.send_message(message.chat.id, res)
                return

            # Иначе — подсказка
            await bot.send_message(
                message.chat.id,
                "Я — бот Тайный Санта 🎅. Используйте /help для списка команд и подсказок."
            )

        # --- Цикл обработки апдейтов из очереди ---
        logger.info("Фоновый воркер запущен")
        try:
            while True:
                try:
                    update_data = update_queue.get(timeout=1)
                    update_id = update_data.get('update_id', 'unknown')
                    try:
                        update = types.Update(**update_data)
                        await dp.process_update(update)
                        logger.info(f"✅ Обработано update: {update_id}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка обработки update {update_id}: {e}")
                    update_queue.task_done()
                except queue.Empty:
                    await asyncio.sleep(0.1)
        finally:
            try:
                await bot.session.close()
            except Exception:
                pass

    # Запускаем асинхронный run() в отдельном event loop
    try:
        asyncio.run(run())
    except Exception as e:
        logger.exception("Фоновый воркер упал: %s", e)

# Запускаем фоновый воркер в отдельном потоке
worker_thread = threading.Thread(target=background_worker, daemon=True)
worker_thread.start()
logger.info("✅ Фоновый поток запущен")

# ---------- Flask маршруты для вебхука и статуса ----------
@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    try:
        update_data = request.get_json()
        update_id = update_data.get('update_id', 'unknown')
        update_queue.put(update_data)
        logger.info(f"📥 Update {update_id} добавлен в очередь")
        return jsonify({'status': 'queued', 'update_id': update_id})
    except Exception as e:
        logger.exception("Ошибка в webhook: %s", e)
        return jsonify({'status': 'error'}), 500

@app.route('/')
def index():
    return (
        f"🎅 Тайный Санта бот работает<br>"
        f"Webhook: {WEBHOOK_URL}<br><br>"
        f"<a href='/set_webhook'>Установить вебхук</a><br>"
        f"<a href='/delete_webhook'>Удалить вебхук</a><br>"
        f"<a href='/status'>Статус API</a><br>"
    )

@app.route('/set_webhook')
def set_webhook():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        from aiogram import Bot
        temp_bot = Bot(token=BOT_TOKEN)
        loop.run_until_complete(temp_bot.set_webhook(WEBHOOK_URL))
        loop.run_until_complete(temp_bot.session.close())
        loop.close()
        logger.info(f"✅ Вебхук установлен: {WEBHOOK_URL}")
        return f"✅ Вебхук установлен! URL: {WEBHOOK_URL}"
    except Exception as e:
        logger.exception("Ошибка установки вебхука: %s", e)
        return f"❌ Ошибка: {e}"

@app.route('/delete_webhook')
def delete_webhook():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        from aiogram import Bot
        temp_bot = Bot(token=BOT_TOKEN)
        loop.run_until_complete(temp_bot.delete_webhook())
        loop.run_until_complete(temp_bot.session.close())
        loop.close()
        return "✅ Вебхук удален!"
    except Exception as e:
        logger.exception("Ошибка удаления вебхука: %s", e)
        return f"❌ Ошибка: {e}"

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

# ---------- Статистика (HTML) ----------
@app.route('/stats')
def stats():
    active_games = sum(1 for g in games_db.values() if g['status'] == 'active')
    waiting_games = sum(1 for g in games_db.values() if g['status'] == 'waiting')
    finished_games = sum(1 for g in games_db.values() if g['status'] == 'finished')
    return (
        f"<h1>🎅 Статистика Тайного Санты</h1>"
        f"<p>Всего игр: {len(games_db)}</p>"
        f"<p>Активных игр: {active_games}</p>"
        f"<p>Ожидающих игр: {waiting_games}</p>"
        f"<p>Завершенных игр: {finished_games}</p>"
        f"<p>Зарегистрированных игроков: {len(players_db)}</p>"
        f"<p>Очередь сообщений: {update_queue.qsize()}</p>"
        f"<p>Фоновый воркер: {'✅ работает' if worker_thread.is_alive() else '❌ остановлен'}</p>"
        f"<p><a href='/'>На главную</a></p>"
    )

# ---------- Запуск приложения ----------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info("🚀 Запуск Flask приложения...")
    app.run(host='0.0.0.0', port=port)
