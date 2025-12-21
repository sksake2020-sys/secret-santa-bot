# app/worker.py
# Aiogram background worker: обрабатывает команды Telegram-бота

import asyncio
import logging
import queue
import threading
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage

from app.manager import GameManager
from app.messages import MESSAGES
from app.utils import username_is_valid_for_link
from app.database import SessionLocal
from app.models import Game, Participant

logger = logging.getLogger(__name__)

# Очередь апдейтов, куда webhook кладёт данные
update_queue = queue.Queue()

# Пользователи, ожидающие ввода названия игры
pending_new_game = set()


def start_worker(bot_token: str, bot_username: str):
    """Запускает aiogram worker в отдельном потоке."""

    def worker():
        bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
        dp = Dispatcher(bot, storage=MemoryStorage())

        # -------------------- Команды --------------------

        @dp.message_handler(commands=['start'])
        async def cmd_start(message: types.Message):
            args = message.get_args()
            if args and args.startswith("join_"):
                code = args.replace("join_", "").upper()
                ok, res = GameManager.join_game(
                    code,
                    message.from_user.id,
                    message.from_user.first_name or message.from_user.username or str(message.from_user.id)
                )
                if ok:
                    g = GameManager.get_game_info(code)
                    await bot.send_message(
                        message.chat.id,
                        MESSAGES["joined_game"].format(name=g['name'], code=code),
                        parse_mode="Markdown"
                    )
                else:
                    await bot.send_message(message.chat.id, res)
                return

            await bot.send_message(message.chat.id, MESSAGES["start_welcome"])

        @dp.message_handler(commands=['help'])
        async def cmd_help(message: types.Message):
            await bot.send_message(
                message.chat.id,
                MESSAGES["help"].format(bot=bot_username),
                parse_mode="Markdown"
            )

        @dp.message_handler(commands=['newgame'])
        async def cmd_newgame(message: types.Message):
            uid = message.from_user.id
            pending_new_game.add(uid)
            await bot.send_message(message.chat.id, MESSAGES["newgame_prompt"])

        @dp.message_handler(commands=['join'])
        async def cmd_join(message: types.Message):
            parts = message.text.strip().split()
            if len(parts) < 2:
                await bot.send_message(message.chat.id, "❌ Укажите код: /join ABC123XY")
                return

            code = parts[1].upper()
            ok, res = GameManager.join_game(
                code,
                message.from_user.id,
                message.from_user.first_name or message.from_user.username or str(message.from_user.id)
            )
            await bot.send_message(message.chat.id, res)

        @dp.message_handler(commands=['startgame'])
        async def cmd_startgame(message: types.Message):
            db = SessionLocal()
            try:
                game = db.query(Game).filter(
                    Game.admin_id == message.from_user.id,
                    Game.is_started == False,
                    Game.is_active == True
                ).order_by(Game.created_at.desc()).first()

                if not game:
                    await bot.send_message(message.chat.id, "❌ У вас нет игр, которые можно запустить.")
                    return

                ok, res = GameManager.start_game(game.id, message.from_user.id)
                await bot.send_message(message.chat.id, res)

                if ok:
                    participants = db.query(Participant).filter(
                        Participant.game_id == game.id
                    ).all()

                    for p in participants:
                        if not p.target_id:
                            continue

                        target = db.query(Participant).filter(
                            Participant.game_id == game.id,
                            Participant.user_id == p.target_id
                        ).first()

                        if not target:
                            continue

                        wishlist = target.wishlist or "Пожелания не указаны"
                        display = target.username or target.full_name or str(target.user_id)

                        logger.info("pair_sent: game=%s santa=%s receiver=%s", game.id, p.user_id, target.user_id)

                        try:
                            await bot.send_message(
                                p.user_id,
                                MESSAGES["startgame_notify"].format(
                                    name=display,
                                    wishlist=wishlist
                                ),
                                parse_mode="Markdown"
                            )
                        except Exception as e:
                            logger.exception("Failed to send DM: %s", e)

            finally:
                db.close()

        @dp.message_handler(commands=['finishgame'])
        async def cmd_finishgame(message: types.Message):
            db = SessionLocal()
            try:
                game = db.query(Game).filter(
                    Game.admin_id == message.from_user.id,
                    Game.is_active == True
                ).order_by(Game.created_at.desc()).first()

                if not game:
                    await bot.send_message(message.chat.id, "❌ У вас нет активных игр.")
                    return

                ok, res = GameManager.finish_game(game.id, message.from_user.id)
                await bot.send_message(message.chat.id, res)

                if ok:
                    participants = db.query(Participant).filter(
                        Participant.game_id == game.id
                    ).all()

                    for p in participants:
                        try:
                            await bot.send_message(
                                p.user_id,
                                MESSAGES["finishgame"].format(name=game.name)
                            )
                        except:
                            pass

            finally:
                db.close()

        @dp.message_handler(commands=['wish'])
        async def cmd_wish(message: types.Message):
            text = message.text.strip()
            wishlist = text[6:].strip() if len(text) > 6 else ""

            if not wishlist:
                await bot.send_message(message.chat.id, "📝 Укажите пожелания: /wish Хочу книгу")
                return

            ok, res = GameManager.set_wishlist(message.from_user.id, wishlist)
            await bot.send_message(message.chat.id, res)

        @dp.message_handler(commands=['mytargets', 'mytarget'])
        async def cmd_mytargets(message: types.Message):
            results = GameManager.get_my_targets(message.from_user.id)

            if not results:
                await bot.send_message(message.chat.id, "📭 У вас пока нет активных назначений.")
                return

            lines = []
            for r in results:
                if not r.get("target_id"):
                    lines.append(
                        f"Игра: *{r['game_name']}* (код `{r['game_id']}`) — получатель: ❌ не назначен"
                    )
                    continue

                display = r.get("target_username") or r.get("target_full_name") or str(r["target_id"])

                if username_is_valid_for_link(r.get("target_username")):
                    lines.append(
                        f"Игра: *{r['game_name']}*\n"
                        f"Получатель: [{display}](https://t.me/{r['target_username']})\n"
                        f"Пожелания: {r['target_wishlist']}"
                    )
                else:
                    lines.append(
                        f"Игра: *{r['game_name']}*\n"
                        f"Получатель: {display}\n"
                        f"Пожелания: {r['target_wishlist']}"
                    )

            await bot.send_message(message.chat.id, "\n\n".join(lines), parse_mode="Markdown")

        @dp.message_handler(commands=['mygames'])
        async def cmd_mygames(message: types.Message):
            db = SessionLocal()
            try:
                parts = db.query(Participant).filter(
                    Participant.user_id == message.from_user.id
                ).all()

                game_ids = {p.game_id for p in parts}

                if not game_ids:
                    await bot.send_message(message.chat.id, "📭 У вас пока нет игр.")
                    return

                lines = []
                for gid in game_ids:
                    g = db.query(Game).filter(Game.id == gid).first()
                    if not g:
                        continue

                    count = db.query(Participant).filter(
                        Participant.game_id == gid
                    ).count()

                    status = (
                        "Игра началась" if g.is_started else
                        ("Ожидание" if g.is_active else "Завершена")
                    )

                    lines.append(f"- {g.name} (код: {g.id}, статус: {status}) — {count} участников")

                await bot.send_message(message.chat.id, "📋 Ваши игры:\n" + "\n".join(lines))

            finally:
                db.close()

        @dp.message_handler(commands=['gameinfo'])
        async def cmd_gameinfo(message: types.Message):
            parts = message.text.strip().split()
            if len(parts) < 2:
                await bot.send_message(message.chat.id, "❌ Укажите код: /gameinfo ABC123XY")
                return

            code = parts[1].upper()
            info = GameManager.get_game_info(code)

            if not info:
                await bot.send_message(message.chat.id, f"❌ Игра с кодом {code} не найдена")
                return

            status_map = {
                "waiting": "Ожидание игроков",
                "active": "Игра началась",
                "finished": "Игра завершена"
            }

            extra = ""
            if info["participants"]:
                extra_lines = []
                for p in info["participants"]:
                    uname = p.get("username") or p.get("full_name") or str(p.get("user_id"))
                    mark = "📝" if p.get("has_wishlist") else "❔"

                    if username_is_valid_for_link(p.get("username")):
                        extra_lines.append(f"- [{uname}](https://t.me/{p.get('username')}) {mark}")
                    else:
                        extra_lines.append(f"- {uname} {mark}")

                extra = "Участники:\n" + "\n".join(extra_lines)

            await bot.send_message(
                message.chat.id,
                MESSAGES["gameinfo"].format(
                    name=info["name"],
                    code=info["id"],
                    creator=info["creator_name"],
                    status=status_map.get(info["status"], info["status"]),
                    budget=info["budget"],
                    created=info["created_at"][:10] if info["created_at"] else "",
                    count=len(info["participants"]),
                    extra=extra
                ),
                parse_mode="Markdown"
            )

        @dp.message_handler(commands=['players'])
        async def cmd_players(message: types.Message):
            db = SessionLocal()
            try:
                p = db.query(Participant).filter(
                    Participant.user_id == message.from_user.id
                ).order_by(Participant.id.desc()).first()

                if not p:
                    await bot.send_message(message.chat.id, "❌ Вы не участвуете в игре.")
                    return

                g = db.query(Game).filter(Game.id == p.game_id).first()
                if not g:
                    await bot.send_message(message.chat.id, "❌ Игра не найдена.")
                    return

                participants = db.query(Participant).filter(
                    Participant.game_id == g.id
                ).all()

                lines = []
                for i, part in enumerate(participants, 1):
                    uname = part.username or part.full_name or str(part.user_id)
                    link = (
                        f"[{uname}](https://t.me/{part.username})"
                        if username_is_valid_for_link(part.username)
                        else uname
                    )
                    creator_mark = " 👑" if part.user_id == g.admin_id else ""
                    wishlist_mark = " 📝" if part.wishlist else " ❔"

                    lines.append(f"{i}. {link}{creator_mark}{wishlist_mark}")

                await bot.send_message(
                    message.chat.id,
                    MESSAGES["players_list_header"].format(name=g.name) + "\n" + "\n".join(lines),
                    parse_mode="Markdown"
                )

            finally:
                db.close()

        @dp.message_handler(commands=['status'])
        async def cmd_status(message: types.Message):
            db = SessionLocal()
            try:
                total_games = db.query(Game).count()
                active_games = db.query(Game).filter(Game.is_started == True).count()
                waiting_games = db.query(Game).filter(Game.is_started == False, Game.is_active == True).count()
                finished_games = db.query(Game).filter(Game.is_active == False).count()
                total_players = db.query(Participant).distinct(Participant.user_id).count()

                await bot.send_message(
                    message.chat.id,
                    MESSAGES["status"].format(
                        total=total_games,
                        active=active_games,
                        waiting=waiting_games,
                        finished=finished_games,
                        players=total_players,
                        queue=update_queue.qsize()
                    ),
                    parse_mode="Markdown"
                )
            finally:
                db.close()

        # -------------------- Обработка текста --------------------

        @dp.message_handler()
        async def handle_text(message: types.Message):
            uid = message.from_user.id
            text = (message.text or "").strip()

            # Пользователь вводит название игры
            if uid in pending_new_game:
                pending_new_game.remove(uid)

                game_name = text[:200].strip()
                if not game_name:
                    await bot.send_message(message.chat.id, "❌ Название не может быть пустым.")
                    return

                creator_name = message.from_user.first_name or message.from_user.username or str(uid)

                try:
                    g = GameManager.create_game(uid, creator_name, game_name)
                    await bot.send_message(
                        message.chat.id,
                        MESSAGES["game_created"].format(
                            name=g["name"],
                            code=g["id"],
                            link=g["invite_link"]
                        ),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.exception("Error creating game: %s", e)
                    await bot.send_message(message.chat.id, "❌ Не удалось создать игру.")
                return

            # Если текст похож на код игры
            if len(text) == 8 and text.isalnum():
                await bot.send_message(
                    message.chat.id,
                    f"🔍 Похоже на код игры.\nПрисоединиться: https://t.me/{bot_username}?start=join_{text.upper()}"
                )
                return

            await bot.send_message(message.chat.id, MESSAGES["unknown_command"])

        # -------------------- Очередь апдейтов --------------------

        async def process_queue():
            logger.info("Aiogram worker started")
            while True:
                try:
                    update_data = update_queue.get(timeout=1)
                except queue.Empty:
                    await asyncio.sleep(0.1)
                    continue

                try:
                    update = types.Update(**update_data)
                    await dp.process_update(update)
                except Exception as e:
                    logger.exception("Error processing update: %s", e)
                finally:
                    update_queue.task_done()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.create_task(process_queue())

        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(bot.session.close())

    # Запускаем воркер в отдельном потоке
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    logger.info("Background worker thread started")
    return update_queue
