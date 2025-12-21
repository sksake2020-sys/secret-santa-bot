# webhook_app.py
# Полный рабочий вебхук для Telegram-бота "Тайный Санта"
# - использует PostgreSQL (через SQLAlchemy)
# - сохраняет игры, участников и пары в БД
# - поддерживает /mytargets для всех игр пользователя
# - логирует рассылку пар (pair_sent)
# - имеет админ-эндпойнт /dump_games для экспорта текущих игр (только для ADMIN_ID)
#
# Требуемые переменные окружения:
# BOT_TOKEN, BOT_USERNAME, DATABASE_URL, ADMIN_ID (опционально, для /dump_games)
#
# Установка зависимостей:
# pip install aiogram flask sqlalchemy psycopg2-binary

import os
import logging
import asyncio
import threading
import queue
import random
import string
from datetime import datetime
from typing import Optional, Dict, Any

from flask import Flask, request, jsonify
from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage

from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, DateTime, Text, ForeignKey, select
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, scoped_session

# ----------------- Logging -----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("santa")

# ----------------- Config -----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BOT_USERNAME = os.environ.get("BOT_USERNAME")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_ID = os.environ.get("ADMIN_ID")  # optional, Telegram user id allowed to use /dump_games

if not BOT_TOKEN or not BOT_USERNAME:
    raise RuntimeError("BOT_TOKEN and BOT_USERNAME must be set in environment variables")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be set in environment variables")

# SQLAlchemy expects postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ----------------- Database models -----------------
Base = declarative_base()

class Game(Base):
    __tablename__ = "games"
    id = Column(String(50), primary_key=True)  # codes like ABC123XY
    name = Column(String(200), nullable=False)
    admin_id = Column(Integer, nullable=False)
    admin_username = Column(String(200), nullable=True)
    chat_id = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True)
    is_started = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    gift_price = Column(String(100), nullable=True)
    wishlist = Column(Text, nullable=True)

    participants = relationship("Participant", back_populates="game", cascade="all, delete-orphan")

class Participant(Base):
    __tablename__ = "participants"
    id = Column(Integer, primary_key=True)
    game_id = Column(String(50), ForeignKey("games.id"), nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    username = Column(String(100), nullable=True)
    full_name = Column(String(200), nullable=True)
    wishlist = Column(Text, nullable=True)
    target_id = Column(Integer, nullable=True, index=True)

    game = relationship("Game", back_populates="participants")

# ----------------- Engine and Session -----------------
engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=False
)
SessionLocal = scoped_session(sessionmaker(bind=engine, autocommit=False, autoflush=False))
Base.metadata.create_all(bind=engine)
logger.info("Database tables created/checked")

# ----------------- Flask app -----------------
app = Flask(__name__)

# ----------------- In-memory queue and worker -----------------
update_queue = queue.Queue()

# ----------------- Messages (localized / themed) -----------------
MESSAGES = {
    "start_welcome": (
        "❄️✨ Добро пожаловать в волшебный мир Тайного Санты! ✨❄️\n\n"
        "🎁 Здесь рождаются сюрпризы и тёплые истории под ёлкой.\n"
        "🎄 Создайте игру, пригласите друзей и пусть начнётся праздник!\n\n"
        "📜 Для списка команд отправьте /help — и волшебство начнётся 🎅"
    ),
    "help": (
        "🎄 *Команды Тайного Санты* 🎄\n\n"
        "/newgame — создать игру\n"
        "/join CODE — присоединиться к игре\n"
        "/startgame — запустить жеребьёвку (только создатель)\n"
        "/finishgame — завершить игру\n"
        "/wish TEXT — оставить пожелания\n"
        "/mytargets — узнать, кому вы дарите (во всех играх)\n"
        "/mygames — список ваших игр\n"
        "/gameinfo CODE — подробности об игре\n"
        "/players — кто уже у ёлки\n"
        "/status — статус бота\n\n"
        "🔔 Приглашение: https://t.me/{bot}?start=join_<КОД>"
    ),
    "newgame_prompt": "🎄 Как назовём вашу праздничную игру?",
    "game_created": "🎉 Игра создана: {name} (код {code}). Ссылка: {link}",
    "joined_game": "🎉 Вы присоединились к игре {name}! Код: {code}",
    "wish_saved": "📝 Пожелания сохранены!",
    "mytarget": "🎅 Ваш получатель: {name}\n\n🎁 Пожелания:\n{wishlist}",
    "startgame_ok": "🎄 Жеребьёвка проведена — игра началась!",
    "startgame_notify": "🎅 Хо-хо! Вы Тайный Санта для: {name}\n\n🎁 Пожелания:\n{wishlist}",
    "finishgame": "✅ Игра '{name}' завершена!",
    "players_list_header": "👥 Участники игры '{name}':",
    "gameinfo": "🎮 Информация об игре\n\nНазвание: {name}\nКод: {code}\nСоздатель: {creator}\nСтатус: {status}\nБюджет: {budget}\nСоздана: {created}\nУчастников: {count}\n\n{extra}",
    "status": "📊 Статус бота:\nВсего игр: {total}\nАктивных: {active}\nОжидающих: {waiting}\nЗавершенных: {finished}\nИгроков: {players}\nОчередь: {queue}",
    "unknown_command": "Я — бот Тайный Санта 🎅. Используйте /help для списка команд."
}

# ----------------- Utility helpers -----------------
def generate_game_id(length: int = 8) -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def format_display_name(username: Optional[str], full_name: Optional[str], user_id: int) -> str:
    if username:
        return username
    if full_name:
        return full_name
    return str(user_id)

def username_is_valid_for_link(username: Optional[str]) -> bool:
    if not username:
        return False
    # Telegram usernames: 5-32 chars, letters, numbers, underscores
    import re
    return bool(re.match(r'^[A-Za-z0-9_]{5,32}$', username))

# ----------------- GameManager (DB-backed) -----------------
class GameManager:
    @staticmethod
    def create_game(creator_id: int, creator_name: str, game_name: str, budget: Optional[str] = None) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            game_id = generate_game_id()
            invite_link = f"https://t.me/{BOT_USERNAME}?start=join_{game_id}"
            g = Game(
                id=game_id,
                name=game_name,
                admin_id=creator_id,
                admin_username=creator_name,
                chat_id=str(creator_id),
                is_active=True,
                is_started=False,
                created_at=datetime.utcnow(),
                gift_price=budget or "Без ограничений"
            )
            db.add(g)
            # add creator as participant
            p = Participant(
                game_id=game_id,
                user_id=creator_id,
                username=creator_name,
                full_name=creator_name
            )
            db.add(p)
            db.commit()
            logger.info("game_created: %s by %s", game_id, creator_id)
            return {
                'id': game_id,
                'name': game_name,
                'creator_id': creator_id,
                'creator_name': creator_name,
                'budget': budget or "Без ограничений",
                'invite_link': invite_link
            }
        except Exception as e:
            db.rollback()
            logger.exception("Error create_game: %s", e)
            raise
        finally:
            db.close()

    @staticmethod
    def join_game(game_id: str, user_id: int, username: str) -> (bool, str):
        db = SessionLocal()
        try:
            game = db.query(Game).filter(Game.id == game_id).first()
            if not game:
                return False, "❌ Игра не найдена"
            if game.is_started:
                return False, "⏳ Игра уже началась"
            exists = db.query(Participant).filter(Participant.game_id == game_id, Participant.user_id == user_id).first()
            if exists:
                return False, "🎅 Вы уже участвуете в этой игре"
            p = Participant(
                game_id=game_id,
                user_id=user_id,
                username=username,
                full_name=username
            )
            db.add(p)
            db.commit()
            logger.info("player_joined: game=%s user=%s", game_id, user_id)
            return True, "🎉 Вы присоединились к праздничной игре!"
        except Exception as e:
            db.rollback()
            logger.exception("Error join_game: %s", e)
            return False, "❌ Ошибка при присоединении"
        finally:
            db.close()

    @staticmethod
    def start_game(game_id: str, creator_id: int) -> (bool, str):
        db = SessionLocal()
        try:
            game = db.query(Game).filter(Game.id == game_id).first()
            if not game:
                return False, "❌ Игра не найдена"
            if game.admin_id != creator_id:
                return False, "👑 Только создатель может начать игру"
            if game.is_started:
                return False, "⏳ Игра уже началась"
            participants = db.query(Participant).filter(Participant.game_id == game_id).all()
            if len(participants) < 2:
                return False, "🎁 Нужно минимум 2 участника"
            user_ids = [p.user_id for p in participants]
            random.shuffle(user_ids)
            # assign circular pairs
            pairs = {}
            for i, giver in enumerate(user_ids):
                receiver = user_ids[(i + 1) % len(user_ids)]
                # update participant record for giver
                giver_rec = db.query(Participant).filter(Participant.game_id == game_id, Participant.user_id == giver).first()
                if giver_rec:
                    giver_rec.target_id = receiver
                    pairs[str(giver)] = receiver
            game.is_started = True
            game.started_at = datetime.utcnow()
            db.commit()
            logger.info("game_started: %s pairs=%s", game_id, pairs)
            return True, "🎄 Игра началась! Тайные Санты распределены 🎅"
        except Exception as e:
            db.rollback()
            logger.exception("Error start_game: %s", e)
            return False, "❌ Ошибка при старте игры"
        finally:
            db.close()

    @staticmethod
    def finish_game(game_id: str, user_id: int) -> (bool, str):
        db = SessionLocal()
        try:
            game = db.query(Game).filter(Game.id == game_id).first()
            if not game:
                return False, "❌ Игра не найдена"
            if game.admin_id != user_id:
                return False, "👑 Только создатель может завершить игру"
            if not game.is_started:
                return False, "⏳ Игра еще не началась"
            game.is_active = False
            game.is_started = False
            db.commit()
            logger.info("game_finished: %s by %s", game_id, user_id)
            return True, "✅ Игра завершена! Спасибо за участие 🎁"
        except Exception as e:
            db.rollback()
            logger.exception("Error finish_game: %s", e)
            return False, "❌ Ошибка при завершении игры"
        finally:
            db.close()

    @staticmethod
    def set_wishlist(user_id: int, wishlist_text: str) -> (bool, str):
        db = SessionLocal()
        try:
            # find participant and game
            p = db.query(Participant).filter(Participant.user_id == user_id).order_by(Participant.id.desc()).first()
            if not p:
                return False, "❌ Вы не участвуете в играах"
            game = db.query(Game).filter(Game.id == p.game_id).first()
            if not game or game.is_started:
                return False, "⏳ Нельзя менять пожелания после старта игры"
            p.wishlist = wishlist_text
            db.commit()
            logger.info("wishlist_saved: user=%s game=%s", user_id, p.game_id)
            return True, MESSAGES["wish_saved"]
        except Exception as e:
            db.rollback()
            logger.exception("Error set_wishlist: %s", e)
            return False, "❌ Ошибка при сохранении пожеланий"
        finally:
            db.close()

    @staticmethod
    def get_my_targets(user_id: int):
        db = SessionLocal()
        try:
            # find all participants rows for this user (they may be in multiple games)
            rows = db.query(Participant).filter(Participant.user_id == user_id).all()
            results = []
            for p in rows:
                game = db.query(Game).filter(Game.id == p.game_id).first()
                if not game or not game.is_started:
                    continue
                if not p.target_id:
                    results.append({'game_id': p.game_id, 'game_name': game.name, 'target_id': None})
                    continue
                target = db.query(Participant).filter(Participant.game_id == p.game_id, Participant.user_id == p.target_id).first()
                if target:
                    results.append({
                        'game_id': p.game_id,
                        'game_name': game.name,
                        'target_id': target.user_id,
                        'target_username': target.username,
                        'target_full_name': target.full_name,
                        'target_wishlist': target.wishlist or "Пожелания не указаны"
                    })
                else:
                    results.append({'game_id': p.game_id, 'game_name': game.name, 'target_id': p.target_id})
            return results
        except Exception as e:
            logger.exception("Error get_my_targets: %s", e)
            return []
        finally:
            db.close()

    @staticmethod
    def get_game_info(game_id: str):
        db = SessionLocal()
        try:
            game = db.query(Game).filter(Game.id == game_id).first()
            if not game:
                return None
            participants = db.query(Participant).filter(Participant.game_id == game_id).all()
            participants_info = []
            for p in participants:
                participants_info.append({
                    'user_id': p.user_id,
                    'username': p.username,
                    'full_name': p.full_name,
                    'has_wishlist': bool(p.wishlist)
                })
            return {
                'id': game.id,
                'name': game.name,
                'creator_id': game.admin_id,
                'creator_name': game.admin_username,
                'status': 'active' if game.is_started else ('waiting' if game.is_active else 'finished'),
                'budget': game.gift_price,
                'created_at': game.created_at.isoformat() if game.created_at else None,
                'participants': participants_info
            }
        except Exception as e:
            logger.exception("Error get_game_info: %s", e)
            return None
        finally:
            db.close()

# ----------------- Aiogram background worker -----------------
def background_worker():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(bot, storage=MemoryStorage())

    @dp.message_handler(commands=['start'])
    async def cmd_start(message: types.Message):
        args = message.get_args()
        if args and args.startswith("join_"):
            code = args.replace("join_", "").upper()
            ok, res = GameManager.join_game(code, message.from_user.id, message.from_user.first_name or message.from_user.username or str(message.from_user.id))
            if ok:
                g = GameManager.get_game_info(code)
                await bot.send_message(message.chat.id, MESSAGES["joined_game"].format(name=g['name'], code=code))
            else:
                await bot.send_message(message.chat.id, res)
            return
        await bot.send_message(message.chat.id, MESSAGES["start_welcome"])

    @dp.message_handler(commands=['help'])
    async def cmd_help(message: types.Message):
        await bot.send_message(message.chat.id, MESSAGES["help"].format(bot=BOT_USERNAME))

    @dp.message_handler(commands=['newgame'])
    async def cmd_newgame(message: types.Message):
        await bot.send_message(message.chat.id, MESSAGES["newgame_prompt"])
        # next message will be treated as game name by simple approach:
        # For simplicity, user sends /newgame then the next text message becomes the name.
        # In production use FSM to handle multi-step flows.

    @dp.message_handler(commands=['join'])
    async def cmd_join(message: types.Message):
        parts = message.text.strip().split()
        if len(parts) < 2:
            await bot.send_message(message.chat.id, "❌ Укажите код: /join ABC123XY")
            return
        code = parts[1].upper()
        ok, res = GameManager.join_game(code, message.from_user.id, message.from_user.first_name or message.from_user.username or str(message.from_user.id))
        await bot.send_message(message.chat.id, res)

    @dp.message_handler(commands=['startgame'])
    async def cmd_startgame(message: types.Message):
        # find a game where user is admin and current_game is waiting
        db = SessionLocal()
        try:
            # find a game where this user is admin and not started
            game = db.query(Game).filter(Game.admin_id == message.from_user.id, Game.is_started == False, Game.is_active == True).order_by(Game.created_at.desc()).first()
            if not game:
                await bot.send_message(message.chat.id, "❌ У вас нет игр, которые можно запустить.")
                return
            ok, res = GameManager.start_game(game.id, message.from_user.id)
            await bot.send_message(message.chat.id, res)
            if ok:
                # notify participants individually and log pair_sent
                targets = GameManager.get_my_targets  # helper
                # fetch participants
                participants = db.query(Participant).filter(Participant.game_id == game.id).all()
                for p in participants:
                    # get target for this participant
                    if not p.target_id:
                        continue
                    target = db.query(Participant).filter(Participant.game_id == game.id, Participant.user_id == p.target_id).first()
                    if not target:
                        continue
                    display_name = target.username or target.full_name or str(target.user_id)
                    wishlist = target.wishlist or "Пожелания не указаны"
                    logger.info("pair_sent: game=%s santa=%s receiver=%s", game.id, p.user_id, target.user_id)
                    try:
                        await bot.send_message(p.user_id, MESSAGES["startgame_notify"].format(name=display_name, wishlist=wishlist))
                    except Exception as e:
                        logger.exception("Failed to send DM to %s: %s", p.user_id, e)
        finally:
            db.close()

    @dp.message_handler(commands=['finishgame'])
    async def cmd_finishgame(message: types.Message):
        db = SessionLocal()
        try:
            game = db.query(Game).filter(Game.admin_id == message.from_user.id, Game.is_active == True).order_by(Game.created_at.desc()).first()
            if not game:
                await bot.send_message(message.chat.id, "❌ У вас нет активных игр.")
                return
            ok, res = GameManager.finish_game(game.id, message.from_user.id)
            await bot.send_message(message.chat.id, res)
            if ok:
                participants = db.query(Participant).filter(Participant.game_id == game.id).all()
                for p in participants:
                    try:
                        await bot.send_message(p.user_id, MESSAGES["finishgame"].format(name=game.name))
                    except Exception:
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
            if not r.get('target_id'):
                lines.append(f"Игра: *{r['game_name']}* (код `{r['game_id']}`) — получатель: ❌ не назначен")
                continue
            display = r.get('target_username') or r.get('target_full_name') or str(r['target_id'])
            if username_is_valid_for_link(r.get('target_username')):
                lines.append(f"Игра: *{r['game_name']}* (код `{r['game_id']}`)\nПолучатель: [{display}](https://t.me/{r['target_username']}) (id `{r['target_id']}`)\nПожелания: {r.get('target_wishlist')}")
            else:
                lines.append(f"Игра: *{r['game_name']}* (код `{r['game_id']}`)\nПолучатель: {display} (id `{r['target_id']}`)\nПожелания: {r.get('target_wishlist')}")
        await bot.send_message(message.chat.id, "\n\n".join(lines), parse_mode="Markdown")

    @dp.message_handler(commands=['mygames'])
    async def cmd_mygames(message: types.Message):
        db = SessionLocal()
        try:
            rows = db.query(Game).filter(Game.admin_id == message.from_user.id).all()
            # also include games where user is participant
            parts = db.query(Participant).filter(Participant.user_id == message.from_user.id).all()
            game_ids = set([g.id for g in rows] + [p.game_id for p in parts])
            if not game_ids:
                await bot.send_message(message.chat.id, "📭 У вас пока нет игр.")
                return
            lines = []
            for gid in game_ids:
                g = db.query(Game).filter(Game.id == gid).first()
                if not g:
                    continue
                count = db.query(Participant).filter(Participant.game_id == gid).count()
                lines.append(f"- {g.name} (код: {g.id}, статус: {'Игра началась' if g.is_started else ('Ожидание' if g.is_active else 'Завершена')}) — {count} участников")
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
        status_map = {'waiting': 'Ожидание игроков', 'active': 'Игра началась', 'finished': 'Игра завершена'}
        extra = ""
        if info['participants']:
            extra_lines = []
            for p in info['participants']:
                uname = p.get('username') or p.get('full_name') or str(p.get('user_id'))
                if username_is_valid_for_link(p.get('username')):
                    extra_lines.append(f"- [{uname}](https://t.me/{p.get('username')}) {'📝' if p.get('has_wishlist') else '❔'}")
                else:
                    extra_lines.append(f"- {uname} {'📝' if p.get('has_wishlist') else '❔'}")
            extra = "Участники:\n" + "\n".join(extra_lines)
        await bot.send_message(message.chat.id, MESSAGES["gameinfo"].format(
            name=info['name'],
            code=info['id'],
            creator=info['creator_name'],
            status=status_map.get(info['status'], info['status']),
            budget=info['budget'],
            created=info['created_at'][:10] if info['created_at'] else "",
            count=len(info['participants']),
            extra=extra
        ), parse_mode="Markdown")

    @dp.message_handler(commands=['players'])
    async def cmd_players(message: types.Message):
        # show participants for the most recent game where user is participant
        db = SessionLocal()
        try:
            p = db.query(Participant).filter(Participant.user_id == message.from_user.id).order_by(Participant.id.desc()).first()
            if not p:
                await bot.send_message(message.chat.id, "❌ Вы не участвуете в игре.")
                return
            g = db.query(Game).filter(Game.id == p.game_id).first()
            if not g:
                await bot.send_message(message.chat.id, "❌ Игра не найдена.")
                return
            participants = db.query(Participant).filter(Participant.game_id == g.id).all()
            lines = []
            for i, part in enumerate(participants, 1):
                uname = part.username or part.full_name or str(part.user_id)
                if username_is_valid_for_link(part.username):
                    link = f"[{uname}](https://t.me/{part.username})"
                else:
                    link = uname
                creator_mark = " 👑" if part.user_id == g.admin_id else ""
                wishlist_mark = " 📝" if part.wishlist else " ❔"
                lines.append(f"{i}. {link}{creator_mark}{wishlist_mark}")
            text = MESSAGES["players_list_header"].format(name=g.name) + "\n" + "\n".join(lines)
            await bot.send_message(message.chat.id, text, parse_mode="Markdown")
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
            await bot.send_message(message.chat.id, MESSAGES["status"].format(
                total=total_games, active=active_games, waiting=waiting_games,
                finished=finished_games, players=total_players, queue=update_queue.qsize()
            ))
        finally:
            db.close()

    @dp.message_handler()
    async def handle_all(message: types.Message):
        # Simple flow: if user recently sent /newgame, treat next text as game name.
        # For simplicity, we detect messages of length > 2 and if user has no current games, create one.
        text = (message.text or "").strip()
        if not text:
            await bot.send_message(message.chat.id, MESSAGES["unknown_command"])
            return
        # If text looks like a code (8 alnum), show code hint
        if len(text) == 8 and text.isalnum():
            await bot.send_message(message.chat.id, f"🔍 Похоже на код игры. Присоединиться: https://t.me/{BOT_USERNAME}?start=join_{text.upper()}")
            return
        # Otherwise unknown
        await bot.send_message(message.chat.id, MESSAGES["unknown_command"])

    async def process_queue():
        logger.info("Background aiogram worker started")
        while True:
            try:
                update_data = update_queue.get(timeout=1)
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue
            update_id = update_data.get("update_id", "unknown")
            try:
                update = types.Update(**update_data)
                await dp.process_update(update)
                logger.info("✅ Обработано update: %s", update_id)
            except Exception as e:
                logger.exception("Ошибка обработки update %s: %s", update_id, e)
            finally:
                update_queue.task_done()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(process_queue())
    try:
        loop.run_forever()
    except Exception as e:
        logger.exception("Aiogram worker stopped: %s", e)
    finally:
        loop.run_until_complete(bot.session.close())

# Start worker thread
worker_thread = threading.Thread(target=background_worker, daemon=True)
worker_thread.start()
logger.info("Background worker thread started")

# ----------------- Flask routes -----------------
WEBHOOK_HOST = os.environ.get("RAILWAY_STATIC_URL") or os.environ.get("WEBHOOK_HOST") or "https://example.com"
if not WEBHOOK_HOST.startswith("http"):
    WEBHOOK_HOST = f"https://{WEBHOOK_HOST}"
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    try:
        update_data = request.get_json()
        update_id = update_data.get("update_id", "unknown")
        update_queue.put(update_data)
        logger.info("📥 Update %s queued", update_id)
        return jsonify({"status": "queued", "update_id": update_id})
    except Exception as e:
        logger.exception("Webhook error: %s", e)
        return jsonify({"status": "error"}), 500

@app.route("/")
def index():
    return (
        f"🎅 Тайный Санта бот работает<br>"
        f"Webhook: {WEBHOOK_URL}<br>"
        f"<a href='/set_webhook'>Установить вебхук</a><br>"
        f"<a href='/delete_webhook'>Удалить вебхук</a><br>"
        f"<a href='/status'>Статус API</a><br>"
    )

@app.route("/set_webhook")
def set_webhook():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        bot = Bot(token=BOT_TOKEN)
        loop.run_until_complete(bot.set_webhook(WEBHOOK_URL))
        loop.run_until_complete(bot.session.close())
        return f"✅ Вебхук установлен: {WEBHOOK_URL}"
    except Exception as e:
        logger.exception("Error set_webhook: %s", e)
        return f"❌ Ошибка: {e}"

@app.route("/delete_webhook")
def delete_webhook():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        bot = Bot(token=BOT_TOKEN)
        loop.run_until_complete(bot.delete_webhook())
        loop.run_until_complete(bot.session.close())
        return "✅ Вебхук удален!"
    except Exception as e:
        logger.exception("Error delete_webhook: %s", e)
        return f"❌ Ошибка: {e}"

@app.route("/status")
def status():
    # lightweight status of the Flask app and worker
    db = SessionLocal()
    try:
        total_games = db.query(Game).count()
        active_games = db.query(Game).filter(Game.is_started == True).count()
        waiting_games = db.query(Game).filter(Game.is_started == False, Game.is_active == True).count()
        finished_games = db.query(Game).filter(Game.is_active == False).count()
        total_players = db.query(Participant).distinct(Participant.user_id).count()
    except Exception as e:
        logger.exception("Status DB error: %s", e)
        total_games = active_games = waiting_games = finished_games = total_players = 0
    finally:
        db.close()
    return jsonify({
        "status": "online",
        "webhook_url": WEBHOOK_URL,
        "queue_size": update_queue.qsize(),
        "background_worker": worker_thread.is_alive(),
        "total_games": total_games,
        "active_games": active_games,
        "waiting_games": waiting_games,
        "finished_games": finished_games,
        "total_players": total_players
    })

@app.route("/dump_games")
def dump_games():
    # Admin-only endpoint to export current DB state (JSON)
    caller = request.args.get("admin_id")
    if ADMIN_ID and str(caller) != str(ADMIN_ID):
        return jsonify({"error": "forbidden"}), 403
    db = SessionLocal()
    try:
        games = []
        for g in db.query(Game).all():
            participants = []
            for p in db.query(Participant).filter(Participant.game_id == g.id).all():
                participants.append({
                    "user_id": p.user_id,
                    "username": p.username,
                    "full_name": p.full_name,
                    "wishlist": p.wishlist,
                    "target_id": p.target_id
                })
            games.append({
                "id": g.id,
                "name": g.name,
                "admin_id": g.admin_id,
                "admin_username": g.admin_username,
                "is_active": g.is_active,
                "is_started": g.is_started,
                "created_at": g.created_at.isoformat() if g.created_at else None,
                "started_at": g.started_at.isoformat() if g.started_at else None,
                "participants": participants
            })
        return jsonify({"games": games})
    except Exception as e:
        logger.exception("dump_games error: %s", e)
        return jsonify({"error": "internal"}), 500
    finally:
        db.close()

# ----------------- Run Flask -----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info("Starting Flask app on port %s", port)
    app.run(host="0.0.0.0", port=port)
# webhook_app.py - Полный рабочий файл с новогодним оформлением (все тексты вынесены в MESSAGES)
from flask import Flask, request, jsonify
import asyncio
import logging
import os
import queue
import threading
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
WEBHOOK_HOST = RAILWAY_STATIC_URL or "https://example.com"
if not WEBHOOK_HOST.startswith('http'):
    WEBHOOK_HOST = f"https://{WEBHOOK_HOST}"
WEBHOOK_PATH = f'/webhook/{BOT_TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

# ---------- Новогодние тексты ----------
MESSAGES = {
    "start_welcome": (
        "❄️✨ Добро пожаловать в волшебный мир Тайного Санты! ✨❄️\n\n"
        "🎁 Здесь рождаются сюрпризы и тёплые истории под ёлкой.\n"
        "🎄 Создайте игру, пригласите друзей и пусть начнётся праздник!\n\n"
        "📜 Для списка команд отправьте /help — и волшебство начнётся 🎅"
    ),
    "help": (
        "🎄 *Команды Тайного Санты* 🎄\n\n"
        "/newgame — создать игру и зажечь ёлку\n"
        "/join CODE — присоединиться к игре\n"
        "/startgame — запустить жеребьёвку (только создатель)\n"
        "/finishgame — завершить игру и поблагодарить всех\n"
        "/wish TEXT — оставить свои праздничные пожелания\n"
        "/mytarget — узнать, кому дарить подарок\n"
        "/mygames — список ваших игр\n"
        "/gameinfo CODE — подробности об игре\n"
        "/players — кто уже у ёлки\n"
        "/status — статус бота\n\n"
        "🔔 Приглашение: https://t.me/{bot}?start=join_<КОД>"
    ),
    "newgame_prompt": "🎄 Отлично! Как назовём вашу праздничную игру? (например: «Ёлка друзей 2025»)",
    "game_created": (
        "🎉 Игра создана! 🎉\n\n"
        "📝 Название: {name}\n"
        "🔑 Код: {code}\n"
        "👑 Создатель: {creator}\n"
        "👥 Участников: {count}\n"
        "📌 Ссылка для приглашения:\n{link}\n\n"
        "Когда все соберутся у ёлки, запустите жеребьёвку: /startgame 🎅"
    ),
    "joined_game": "🎉 Вы присоединились к игре {name}! 🔔\nКод: {code}\nНапишите /wish чтобы оставить пожелания.",
    "wish_saved": "📝 Пожелания сохранены! Спасибо — пусть Санта услышит ваши мечты 🎁",
    "mytarget": "🎅 Ваш получатель: {name}\n\n🎁 Пожелания:\n{wishlist}\n\n✨ Сделайте подарок с теплом!",
    "startgame_ok": "🎄 Жеребьёвка проведена — игра началась! Всем удачи и праздничного настроения 🎁",
    "startgame_notify": "🎅 Хо-хо! Вы Тайный Санта для: {name}\n\n🎁 Пожелания:\n{wishlist}\n\nПусть ваш подарок будет волшебным ✨",
    "finishgame": "✅ Игра '{name}' завершена! Спасибо всем за участие — праздник удался 🎉🎄",
    "players_list_header": "👥 Участники игры '{name}':",
    "gameinfo": (
        "🎮 Информация об игре\n\n"
        "📝 Название: {name}\n"
        "🔑 Код: {code}\n"
        "👑 Создатель: {creator}\n"
        "📌 Статус: {status}\n"
        "💰 Бюджет: {budget}\n"
        "📅 Создана: {created}\n"
        "👥 Участников: {count}\n\n"
        "{extra}"
    ),
    "status": (
        "📊 Статус бота:\n"
        "🎮 Всего игр: {total}\n"
        "🎁 Активных: {active}\n"
        "⏳ Ожидающих: {waiting}\n"
        "✅ Завершенных: {finished}\n"
        "👤 Игроков: {players}\n"
        "🔔 Очередь: {queue}"
    ),
    "unknown_command": "Я — бот Тайный Санта 🎅. Используйте /help для списка команд и подсказок.",
    "code_hint": "🔍 Похоже на код игры.\nПрисоединиться: https://t.me/{bot}?start=join_{code}\nИнформация: /gameinfo {code}"
}

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
            'status': 'waiting',
            'created_at': datetime.now().isoformat(),
            'started_at': None,
            'participants': [creator_id],
            'wishlists': {},
            'pairs': {},
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
        return True, MESSAGES["wish_saved"]

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

# ---------- Фоновый воркер ----------
def background_worker():
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.fsm_storage.memory import MemoryStorage

    async def run():
        bot = Bot(token=BOT_TOKEN)
        dp = Dispatcher(bot, storage=MemoryStorage())
        pending_new_game = {}

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
                        MESSAGES["joined_game"].format(name=g['name'], code=code)
                    )
                else:
                    await bot.send_message(message.chat.id, res)
                return
            await bot.send_message(message.chat.id, MESSAGES["start_welcome"])

        @dp.message_handler(commands=['help'])
        async def cmd_help(message: types.Message):
            await bot.send_message(message.chat.id, MESSAGES["help"].format(bot=BOT_USERNAME))

        @dp.message_handler(commands=['newgame'])
        async def cmd_newgame(message: types.Message):
            pending_new_game[message.from_user.id] = True
            await bot.send_message(message.chat.id, MESSAGES["newgame_prompt"])

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
                            MESSAGES["startgame_notify"].format(name=target_info['name'], wishlist=target_info['wishlist'])
                        )
                await bot.send_message(message.chat.id, MESSAGES["startgame_ok"])
            else:
                await bot.send_message(message.chat.id, res)

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
                    await bot.send_message(pid, MESSAGES["finishgame"].format(name=g['name']))
            await bot.send_message(message.chat.id, res)

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
                await bot.send_message(message.chat.id, MESSAGES["joined_game"].format(name=g['name'], code=code))
            else:
                await bot.send_message(message.chat.id, res)

        @dp.message_handler(commands=['players'])
        async def cmd_players(message: types.Message):
            uid = message.from_user.id
            current_game = players_db.get(uid, {}).get('current_game')
            if not current_game or current_game not in games_db:
                await bot.send_message(message.chat.id, "❌ Вы не участвуете в игре.")
                return
            g = games_db[current_game]
            lines = []
            for i, pid in enumerate(g['participants'], 1):
                uname = players_db.get(pid, {}).get('username', 'Неизвестно')
                creator_mark = " 👑" if pid == g['creator_id'] else ""
                wishlist_mark = " 📝" if pid in g['wishlists'] else " ❔"
                lines.append(f"{i}. {uname}{creator_mark}{wishlist_mark}")
            await bot.send_message(message.chat.id, MESSAGES["players_list_header"].format(name=g['name']) + "\n" + "\n".join(lines))

        @dp.message_handler(commands=['wish'])
        async def cmd_wish(message: types.Message):
            text = message.text.strip()
            wishlist = text[6:].strip() if len(text) > 6 else ""
            if not wishlist:
                await bot.send_message(message.chat.id, "📝 Укажите пожелания: /wish Хочу книгу")
                return
            ok, res = GameManager.set_wishlist(message.from_user.id, wishlist)
            await bot.send_message(message.chat.id, res)

        @dp.message_handler(commands=['mytarget'])
        async def cmd_mytarget(message: types.Message):
            target, status = GameManager.get_my_target(message.from_user.id)
            if target:
                await bot.send_message(message.chat.id, MESSAGES["mytarget"].format(name=target['name'], wishlist=target['wishlist']))
            else:
                await bot.send_message(message.chat.id, status)

        @dp.message_handler(commands=['mygames'])
        async def cmd_mygames(message: types.Message):
            games_list = user_games.get(message.from_user.id, [])
            if not games_list:
                await bot.send_message(message.chat.id, "📭 У вас пока нет игр.")
                return
            lines = []
            for gid in games_list:
                g = games_db.get(gid)
                if not g:
                    continue
                lines.append(f"- {g['name']} (код: {gid}, статус: {g['status']})\n  Ссылка: {g['invite_link']}")
            await bot.send_message(message.chat.id, "📋 Ваши игры:\n" + "\n".join(lines))

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
            extra = ""
            if game['status'] == 'waiting':
                extra_lines = []
                for p in game['participants_info']:
                    extra_lines.append(f"- {p['name']} {'📝' if p['has_wishlist'] else '❔'}")
                extra = "Участники:\n" + "\n".join(extra_lines) + f"\n\nСсылка для присоединения:\nhttps://t.me/{BOT_USERNAME}?start=join_{game['id']}"
            elif game['status'] == 'active':
                extra = "🎅 Игра началась! Узнайте своего получателя: /mytarget"
            await bot.send_message(message.chat.id, MESSAGES["gameinfo"].format(
                name=game['name'],
                code=game['id'],
                creator=game['creator_name'],
                status=status_map.get(game['status'], game['status']),
                budget=game['budget'],
                created=game['created_at'][:10],
                count=len(game['participants_info']),
                extra=extra
            ))

        @dp.message_handler(commands=['status'])
        async def cmd_status(message: types.Message):
            total_games = len(games_db)
            active_games = sum(1 for g in games_db.values() if g['status'] == 'active')
            waiting_games = sum(1 for g in games_db.values() if g['status'] == 'waiting')
            finished_games = sum(1 for g in games_db.values() if g['status'] == 'finished')
            total_players = len(players_db)
            await bot.send_message(message.chat.id, MESSAGES["status"].format(
                total=total_games, active=active_games, waiting=waiting_games,
                finished=finished_games, players=total_players, queue=update_queue.qsize()
            ))

        @dp.message_handler()
        async def handle_all(message: types.Message):
            uid = message.from_user.id
            text = (message.text or "").strip()

            if uid in pending_new_game:
                game = GameManager.create_game(uid, message.from_user.first_name, text)
                del pending_new_game[uid]
                await bot.send_message(message.chat.id, MESSAGES["game_created"].format(
                    name=game['name'], code=game['id'], creator=game['creator_name'],
                    count=len(game['participants']), link=game['invite_link']
                ))
                return

            if len(text) == 8 and text.isalnum():
                await bot.send_message(message.chat.id, MESSAGES["code_hint"].format(bot=BOT_USERNAME, code=text.upper()))
                return

            current_game = players_db.get(uid, {}).get('current_game')
            if current_game and games_db.get(current_game, {}).get('status') == 'waiting':
                ok, res = GameManager.set_wishlist(uid, text)
                await bot.send_message(message.chat.id, res)
                return

            await bot.send_message(message.chat.id, MESSAGES["unknown_command"])

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
                        logger.exception("Ошибка обработки update %s: %s", update_id, e)
                    update_queue.task_done()
                except queue.Empty:
                    await asyncio.sleep(0.1)
        finally:
            try:
                await bot.session.close()
            except Exception:
                pass

    try:
        asyncio.run(run())
    except Exception as e:
        logger.exception("Фоновый воркер упал: %s", e)

# Запускаем фоновый воркер в отдельном потоке
worker_thread = threading.Thread(target=background_worker, daemon=True)
worker_thread.start()
logger.info("✅ Фоновый поток запущен")

# ---------- Flask маршруты ----------
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
