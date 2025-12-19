# bot.py - ПОЛНЫЙ КОД БОТА "ТАЙНЫЙ САНТА"
import os
import random
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime
from database import SessionLocal, Game, Participant

# ===================== НАСТРОЙКИ =====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ВАЖНО! ЗАМЕНИТЕ ЭТОТ ТОКЕН НА СВОЙ, ПОЛУЧЕННЫЙ ОТ @BOTFATHER
API_TOKEN = os.environ.get('BOT_TOKEN', '8572653274:AAHDvbfPcGSRzJl-RQ11m4akOW1Wq0NmXYw')

# ID администратора бота (можно узнать у @userinfobot). Замените на свой.
ADMIN_ID = 1417297585

PROXY_URL = "http://proxy.server:3128"
bot = Bot(token=API_TOKEN, proxy=PROXY_URL)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ===================== СОСТОЯНИЯ (FSM) =====================
class GameCreation(StatesGroup):
    waiting_for_name = State()
    waiting_for_price = State()
    waiting_for_wishlist = State()

class JoinGame(StatesGroup):
    waiting_for_code = State()

class EditWishlist(StatesGroup):
    waiting_for_new_wish = State()

# ===================== КОМАНДА /start =====================
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    """Главное меню бота."""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(KeyboardButton("🎮 Создать игру"), KeyboardButton("🎅 Присоединиться"))
    keyboard.row(KeyboardButton("❓ Помощь"), KeyboardButton("📋 Мои игры"))

    welcome_text = f"""
Привет, {message.from_user.first_name}! 👋

Я — бот для организации *Тайного Санты*.

✨ *Что я умею:*
• Создавать игру с настройками
• Приглашать друзей по ссылке
• Автоматически распределять пары
• Хранить пожелания участников

🎯 *Быстрый старт:*
1. Нажми *«Создать игру»*
2. Укажи бюджет и пожелания
3. Отправь друзьям ссылку-приглашение
4. Запусти игру, когда все соберутся

Или используй кнопки ниже ⬇️
    """
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="Markdown")

# ===================== КОМАНДА /help =====================
@dp.message_handler(commands=['help'])
async def cmd_help(message: types.Message):
    """Подробная справка по всем командам."""
    help_text = """
🎅 *Помощь по командам Тайного Санты*

*Основные команды:*
/start - Начать работу с ботом (главное меню)
/help - Показать эту справку

*Создание и управление игрой:*
/new_game - Создать новую игру (шаг за шагом)
/game_info - Посмотреть информацию о ваших играх
/start_game - Запустить распределение (только создатель)
/end_game - Завершить игру (только создатель)

*Участие в игре:*
/join [код] - Присоединиться к игре по коду
/my_wishlist - Изменить свои пожелания к подарку

*После запуска игры:*
/my_target - Узнать, кому вы дарите подарок

*Для администратора:*
/stats - Статистика бота

*Пример использования:*
1. Создатель: /new_game → "Корпоратив 2024"
2. Участники: /join 12345 → пишут пожелания
3. Создатель: /start_game - запускает распределение
4. Все участники: /my_target - видят своего получателя

*Примечание:* Игра начинается только когда создатель использует /start_game
    """
    await message.answer(help_text, parse_mode="Markdown")

# ===================== ОБРАБОТКА ГЛАВНЫХ КНОПОК =====================
@dp.message_handler(lambda message: message.text in ["🎮 Создать игру", "🎅 Присоединиться", "❓ Помощь", "📋 Мои игры"])
async def process_main_buttons(message: types.Message):
    """Обработчик кнопок главного меню."""
    if message.text == "🎮 Создать игру":
        await cmd_new_game(message)
    elif message.text == "🎅 Присоединиться":
        # Просим ввести код игры
        await JoinGame.waiting_for_code.set()
        await message.answer("✍️ Введите *код игры*, чтобы присоединиться.\n\nКод — это число, которое создатель игры может вам отправить.\n\nИли нажмите на кнопку-приглашение, которую вам отправили.", parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())
    elif message.text == "❓ Помощь":
        await cmd_help(message)
    elif message.text == "📋 Мои игры":
        await cmd_game_info(message)

# ===================== СОЗДАНИЕ ИГРЫ (/new_game) =====================
@dp.message_handler(commands=['new_game'])
async def cmd_new_game(message: types.Message):
    """Начинает процесс создания новой игры."""
    await GameCreation.waiting_for_name.set()
    await message.answer("🎄 *Давайте создадим новую игру Тайного Санты!*\n\nВведите *название* для вашей игры (например, 'Корпоратив 2024' или 'Семейный Новый Год'):", parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(state=GameCreation.waiting_for_name)
async def process_game_name(message: types.Message, state: FSMContext):
    """Сохраняет название игры и запрашивает бюджет."""
    async with state.proxy() as data:
        data['name'] = message.text
    await GameCreation.next()
    await message.answer("💰 Теперь укажите *ограничение по цене* подарка.\n\nНапример: 'до 1500 рублей', 'в районе 2000₽' или просто 'без ограничений'.", parse_mode="Markdown")

@dp.message_handler(state=GameCreation.waiting_for_price)
async def process_game_price(message: types.Message, state: FSMContext):
    """Сохраняет бюджет и запрашивает пожелания создателя."""
    async with state.proxy() as data:
        data['price'] = message.text
    await GameCreation.next()
    await message.answer("📝 Отлично! Теперь напишите *ваши пожелания* к подарку.\n\nЧто вам нравится? (хобби, размер одежды, любимые сладости, цвета и т.д.)\n\nЭту информацию увидят все участники.", parse_mode="Markdown")

@dp.message_handler(state=GameCreation.waiting_for_wishlist)
async def process_game_wishlist(message: types.Message, state: FSMContext):
    """Финальный шаг создания игры. Сохраняет всё в БД."""
    db = SessionLocal()
    try:
        async with state.proxy() as data:
            # 1. Создаем игру
            new_game = Game(
                name=data['name'],
                admin_id=message.from_user.id,
                admin_username=message.from_user.username,
                chat_id=str(message.chat.id),
                gift_price=data['price'],
                wishlist=message.text
            )
            db.add(new_game)
            db.commit()
            db.refresh(new_game)

            # 2. Добавляем создателя как первого участника
            creator = Participant(
                game_id=new_game.id,
                user_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                wishlist=message.text
            )
            db.add(creator)
            db.commit()

            # 3. Формируем инлайн-кнопку для приглашения
            invite_keyboard = InlineKeyboardMarkup()
            invite_button = InlineKeyboardButton(
                text="🎅 Присоединиться к игре!",
                callback_data=f"join_game_{new_game.id}"
            )
            invite_keyboard.add(invite_button)

            # 4. Отправляем создателю отчет
            success_message = (
                f"✅ *Игра создана!*\n\n"
                f"*Название:* {data['name']}\n"
                f"*Код игры:* `{new_game.id}`\n"
                f"*Бюджет:* {data['price']}\n"
                f"*Создатель:* {message.from_user.full_name}\n\n"
                f"*Чтобы присоединиться, участники могут:*\n"
                f"1. Нажать кнопку ниже👇\n"
                f"2. Использовать команду `/join {new_game.id}`\n\n"
                f"*Когда все соберутся, запустите распределение командой:* /start_game"
            )
            await message.answer(success_message, parse_mode="Markdown", reply_markup=invite_keyboard)

    except Exception as e:
        logger.error(f"Ошибка создания игры: {e}")
        await message.answer("❌ При создании игры произошла ошибка. Попробуйте еще раз.")
    finally:
        db.close()
        await state.finish()
        # Возвращаем главное меню
        await show_main_menu(message)

# ===================== ПРИСОЕДИНЕНИЕ ПО ИНЛАЙН-КНОПКЕ =====================
@dp.callback_query_handler(lambda c: c.data.startswith('join_game_'))
async def process_inline_join(callback_query: types.CallbackQuery):
    """Обработчик нажатия на инлайн-кнопку 'Присоединиться'."""
    db = SessionLocal()
    try:
        game_id = int(callback_query.data.split('_')[2])
        game = db.query(Game).filter(Game.id == game_id, Game.is_active == True).first()

        if not game:
            await callback_query.answer("Игра не найдена или уже завершена!", show_alert=True)
            return
        if game.is_started:
            await callback_query.answer("Игра уже началась, присоединиться нельзя!", show_alert=True)
            return

        # Проверка, не участвует ли уже
        existing = db.query(Participant).filter(
            Participant.game_id == game_id,
            Participant.user_id == callback_query.from_user.id
        ).first()
        if existing:
            await callback_query.answer("Вы уже участвуете в этой игре!", show_alert=True)
            return

        # Добавляем участника
        new_participant = Participant(
            game_id=game_id,
            user_id=callback_query.from_user.id,
            username=callback_query.from_user.username,
            full_name=callback_query.from_user.full_name
        )
        db.add(new_participant)
        db.commit()

        await callback_query.answer(f"Вы присоединились к игре '{game.name}'!", show_alert=True)

        # Просим указать пожелания
        await bot.send_message(
            callback_query.from_user.id,
            f"🎉 Вы присоединились к игре *«{game.name}»*!\n\n"
            f"*Создатель:* {game.admin_username or 'Неизвестно'}\n"
            f"*Бюджет:* {game.gift_price}\n\n"
            f"📝 Пожалуйста, напишите *ваши пожелания* к подарку.\n"
            f"Что вам нравится? (Это поможет вашему Тайному Санте)",
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Ошибка присоединения: {e}")
        await callback_query.answer("Произошла ошибка!", show_alert=True)
    finally:
        db.close()

# ===================== ПРИСОЕДИНЕНИЕ ПО КОМАНДЕ /join =====================
@dp.message_handler(state=JoinGame.waiting_for_code)
async def process_join_by_code(message: types.Message, state: FSMContext):
    """Присоединяет пользователя к игре по введенному коду."""
    db = SessionLocal()
    try:
        code = message.text.strip()
        if not code.isdigit():
            await message.answer("❌ Код игры должен быть числом. Попробуйте еще раз.")
            return

        game_id = int(code)
        game = db.query(Game).filter(Game.id == game_id, Game.is_active == True).first()

        if not game:
            await message.answer("❌ Игра с таким кодом не найдена или уже завершена.")
            await state.finish()
            await show_main_menu(message)
            return
        if game.is_started:
            await message.answer("❌ Игра уже началась, присоединиться нельзя.")
            await state.finish()
            await show_main_menu(message)
            return

        # Проверка, не участвует ли уже
        existing = db.query(Participant).filter(
            Participant.game_id == game_id,
            Participant.user_id == message.from_user.id
        ).first()
        if existing:
            await message.answer("ℹ️ Вы уже участвуете в этой игре.")
            await state.finish()
            await show_main_menu(message)
            return

        # Добавляем участника
        new_participant = Participant(
            game_id=game_id,
            user_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name
        )
        db.add(new_participant)
        db.commit()

        await message.answer(
            f"✅ Вы успешно присоединились к игре *«{game.name}»*!\n\n"
            f"📝 Теперь напишите *ваши пожелания* к подарку одним сообщением.\n"
            f"Что вам нравится? (Это поможет вашему Тайному Санте)",
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Ошибка присоединения по коду: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")
    finally:
        db.close()
        await state.finish()

# ===================== ОБРАБОТКА ПОЖЕЛАНИЙ УЧАСТНИКОВ =====================
@dp.message_handler()
async def process_user_wishlist(message: types.Message):
    """
    Ловит текстовые сообщения и проверяет, является ли это пожеланием
    нового участника, у которого оно ещё не заполнено.
    """
    if message.text.startswith('/'):
        return  # Игнорируем команды

    db = SessionLocal()
    try:
        # Ищем участника без пожеланий в активной, не начавшейся игре
        participant = db.query(Participant).join(Game).filter(
            Participant.user_id == message.from_user.id,
            Participant.wishlist.is_(None),
            Game.is_active == True,
            Game.is_started == False
        ).first()

        if participant:
            participant.wishlist = message.text
            db.commit()
            await message.answer(
                "✅ Ваши пожелания сохранены! Спасибо.\n\n"
                "Теперь дождитесь, пока создатель игры запустит распределение. "
                "Как только игра начнется, вы получите личное сообщение с именем того, кому нужно дарить подарок."
            )
        # Если это не пожелание, игнорируем сообщение
    except Exception as e:
        logger.error(f"Ошибка сохранения пожеланий: {e}")
    finally:
        db.close()

# ===================== КОМАНДА /start_game =====================
@dp.message_handler(commands=['start_game'])
async def cmd_start_game(message: types.Message):
    """Запуск распределения пар в игре (только для создателя)."""
    db = SessionLocal()
    try:
        # Ищем не начатые игры, где пользователь - создатель
        games = db.query(Game).filter(
            Game.admin_id == message.from_user.id,
            Game.is_active == True,
            Game.is_started == False
        ).all()

        if not games:
            await message.answer("У вас нет активных игр, готовых к запуску.")
            return

        if len(games) == 1:
            game = games[0]
            participants = db.query(Participant).filter(Participant.game_id == game.id).all()

            if len(participants) < 3:
                await message.answer("❌ Для начала игры нужно как минимум *3 участника*. Сейчас участников: " + str(len(participants)), parse_mode="Markdown")
                return

            # Создаем клавиатуру для подтверждения
            keyboard = InlineKeyboardMarkup()
            keyboard.row(
                InlineKeyboardButton("✅ Да, начинаем!", callback_data=f"confirm_start_{game.id}"),
                InlineKeyboardButton("❌ Отмена", callback_data="cancel_start")
            )

            await message.answer(
                f"🎅 *Подтверждение запуска игры*\n\n"
                f"*Название:* {game.name}\n"
                f"*Участников:* {len(participants)}\n"
                f"*Бюджет:* {game.gift_price}\n\n"
                f"После запуска:\n"
                f"• Новые участники не смогут присоединиться\n"
                f"• Каждый получит личное сообщение с именем получателя\n"
                f"• Распределение будет *невозможно отменить*\n\n"
                f"*Запустить игру?*",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        else:
            # Если несколько игр - показываем выбор
            keyboard = InlineKeyboardMarkup()
            for g in games:
                p_count = db.query(Participant).filter(Participant.game_id == g.id).count()
                keyboard.add(InlineKeyboardButton(
                    f"{g.name} ({p_count} участников)",
                    callback_data=f"select_game_{g.id}"
                ))
            await message.answer("Выберите игру для запуска:", reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Ошибка запуска игры: {e}")
        await message.answer("❌ Произошла ошибка.")
    finally:
        db.close()

@dp.callback_query_handler(lambda c: c.data.startswith('confirm_start_'))
async def process_confirm_start(callback_query: types.CallbackQuery):
    """Подтверждение и выполнение распределения пар."""
    db = SessionLocal()
    try:
        game_id = int(callback_query.data.split('_')[2])
        game = db.query(Game).filter(Game.id == game_id).first()

        if not game or game.admin_id != callback_query.from_user.id:
            await callback_query.answer("❌ Вы не можете запустить эту игру!", show_alert=True)
            return

        participants = db.query(Participant).filter(Participant.game_id == game_id).all()
        if len(participants) < 3:
            await callback_query.answer("❌ Нужно минимум 3 участника!", show_alert=True)
            return

        # Алгоритм "Тайный Санта" (круговое распределение)
        user_ids = [p.user_id for p in participants]
        random.shuffle(user_ids)

        # Создаем пары даритель -> получатель
        pairs_created = 0
        for i in range(len(user_ids)):
            giver_id = user_ids[i]
            receiver_id = user_ids[(i + 1) % len(user_ids)]  # Круг

            giver = db.query(Participant).filter(
                Participant.game_id == game_id,
                Participant.user_id == giver_id
            ).first()

            receiver = db.query(Participant).filter(
                Participant.game_id == game_id,
                Participant.user_id == receiver_id
            ).first()

            if giver and receiver:
                giver.target_id = receiver.user_id
                pairs_created += 1

        db.commit()

        # Помечаем игру как начатую
        game.is_started = True
        db.commit()

        # Отправляем личные сообщения всем участникам
        for participant in participants:
            receiver = db.query(Participant).filter(
                Participant.game_id == game_id,
                Participant.user_id == participant.target_id
            ).first()

            if receiver:
                try:
                    message_to_giver = (
                        f"🎄 *Тайный Санта начался!*\n\n"
                        f"*Игра:* {game.name}\n"
                        f"*Вы дарите подарок:* {receiver.full_name}\n"
                        f"*Пожелания получателя:*\n{receiver.wishlist or 'Не указано'}\n"
                        f"*Бюджет:* {game.gift_price}\n\n"
                        f"Чтобы снова посмотреть эту информацию, используйте команду /my_target"
                    )
                    await bot.send_message(participant.user_id, message_to_giver, parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Не удалось отправить сообщение {participant.user_id}: {e}")

        # Сообщение в общий чат
        success_msg = (
            f"✅ *Распределение завершено!*\n\n"
            f"Игра *«{game.name}»* официально начата.\n"
            f"Все *{pairs_created}* участников получили личные сообщения с именем того, кому они дарят подарок.\n\n"
            f"🎁 *Что дальше?*\n"
            f"1. Проверьте личные сообщения от бота\n"
            f"2. Используйте /my_target чтобы посмотреть информацию о получателе\n"
            f"3. Готовьте подарки согласно бюджету: {game.gift_price}"
        )

        await callback_query.message.edit_text(success_msg, parse_mode="Markdown")
        await callback_query.answer("Распределение завершено!")

    except Exception as e:
        logger.error(f"Ошибка подтверждения старта: {e}")
        await callback_query.answer("❌ Произошла ошибка!", show_alert=True)
    finally:
        db.close()

@dp.callback_query_handler(lambda c: c.data == 'cancel_start')
async def process_cancel_start(callback_query: types.CallbackQuery):
    """Отмена запуска игры."""
    await callback_query.message.edit_text("🚫 Запуск игры отменен.")
    await callback_query.answer()

# ===================== КОМАНДА /my_target =====================
@dp.message_handler(commands=['my_target'])
async def cmd_my_target(message: types.Message):
    """Показывает пользователю, кому он дарит подарок."""
    db = SessionLocal()
    try:
        participant = db.query(Participant).join(Game).filter(
            Participant.user_id == message.from_user.id,
            Game.is_started == True,
            Game.is_active == True,
            Participant.target_id.isnot(None)
        ).first()

        if not participant:
            await message.answer("Вы не участвуете в активных играх, где уже проведено распределение.")
            return

        receiver = db.query(Participant).filter(
            Participant.game_id == participant.game_id,
            Participant.user_id == participant.target_id
        ).first()

        game = participant.game

        if receiver:
            target_message = (
                f"🎁 *Ваш Тайный Санта*\n\n"
                f"*Игра:* {game.name}\n"
                f"*Вы дарите:* {receiver.full_name}\n"
                f"*Пожелания получателя:*\n{receiver.wishlist or 'Не указано'}\n"
                f"*Бюджет:* {game.gift_price}\n"
            )
            if receiver.username:
                target_message += f"\n*Username:* @{receiver.username}"

            await message.answer(target_message, parse_mode="Markdown")
        else:
            await message.answer("❌ Информация о вашем получателе временно недоступна.")

    except Exception as e:
        logger.error(f"Ошибка в /my_target: {e}")
        await message.answer("❌ Произошла ошибка при получении информации.")
    finally:
        db.close()

# ===================== КОМАНДА /game_info =====================
@dp.message_handler(commands=['game_info'])
async def cmd_game_info(message: types.Message):
    """Показывает информацию об играх пользователя."""
    db = SessionLocal()
    try:
        participants = db.query(Participant).filter(Participant.user_id == message.from_user.id).all()

        if not participants:
            await message.answer("Вы не участвуете ни в одной игре.")
            return

        for participant in participants[:3]:  # Ограничим вывод 3 играми
            game = participant.game
            game_participants = db.query(Participant).filter(Participant.game_id == game.id).all()

            status = "🟢 Активна" if game.is_active else "🔴 Завершена"
            started = "🎅 Распределение проведено" if game.is_started else "⏳ Ожидает запуска"

            participants_list = "\n".join([f"• {p.full_name}" for p in game_participants])

            game_info_msg = (
                f"🎮 *Игра: {game.name}*\n"
                f"*Код:* `{game.id}`\n"
                f"*Статус:* {status}\n"
                f"*Состояние:* {started}\n"
                f"*Участников:* {len(game_participants)}\n"
                f"*Бюджет:* {game.gift_price}\n\n"
                f"*Участники:*\n{participants_list}\n\n"
                f"*Ваша роль:* {'👑 Создатель' if game.admin_id == message.from_user.id else '🎅 Участник'}"
            )

            # Добавляем кнопки действий в зависимости от роли и статуса
            keyboard = InlineKeyboardMarkup()

            if game.admin_id == message.from_user.id and not game.is_started and game.is_active:
                keyboard.add(InlineKeyboardButton("▶️ Запустить игру", callback_data=f"select_game_{game.id}"))

            if game.is_started:
                keyboard.add(InlineKeyboardButton("🎁 Мой получатель", callback_data=f"show_target_{game.id}"))

            await message.answer(game_info_msg, parse_mode="Markdown", reply_markup=keyboard)

        if len(participants) > 3:
            await message.answer(f"*И еще {len(participants) - 3} игр...*\nИспользуйте /game_info снова для подробностей.", parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Ошибка в /game_info: {e}")
        await message.answer("❌ Произошла ошибка.")
    finally:
        db.close()

# ===================== КОМАНДА /my_wishlist =====================
@dp.message_handler(commands=['my_wishlist'])
async def cmd_my_wishlist(message: types.Message):
    """Позволяет изменить свои пожелания в активной, не начавшейся игре."""
    db = SessionLocal()
    try:
        participants = db.query(Participant).join(Game).filter(
            Participant.user_id == message.from_user.id,
            Game.is_active == True,
            Game.is_started == False
        ).all()

        if not participants:
            await message.answer("Вы не участвуете в активных играх, ожидающих запуска.")
            return

        if len(participants) == 1:
            await EditWishlist.waiting_for_new_wish.set()
            # Сохраняем game_id в состоянии
            state = dp.current_state(user=message.from_user.id, chat=message.chat.id)
            await state.update_data(game_id=participants[0].game_id)

            await message.answer(
                f"✏️ Вы изменяете пожелания для игры *«{participants[0].game.name}»*.\n\n"
                f"*Текущие пожелания:*\n{participants[0].wishlist or 'Не указаны'}\n\n"
                f"Напишите *новые пожелания* одним сообщением:",
                parse_mode="Markdown"
            )
        else:
            keyboard = InlineKeyboardMarkup()
            for participant in participants:
                keyboard.add(InlineKeyboardButton(
                    text=f"Изменить для '{participant.game.name}'",
                    callback_data=f"edit_wish_{participant.game_id}"
                ))
            await message.answer("Выберите игру для изменения пожеланий:", reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Ошибка в /my_wishlist: {e}")
        await message.answer("❌ Произошла ошибка.")
    finally:
        db.close()

@dp.message_handler(state=EditWishlist.waiting_for_new_wish)
async def process_new_wishlist(message: types.Message, state: FSMContext):
    """Сохраняет новые пожелания пользователя."""
    db = SessionLocal()
    try:
        user_data = await state.get_data()
        game_id = user_data.get('game_id')

        participant = db.query(Participant).filter(
            Participant.game_id == game_id,
            Participant.user_id == message.from_user.id
        ).first()

        if participant:
            old_wishlist = participant.wishlist
            participant.wishlist = message.text
            db.commit()

            await message.answer(
                f"✅ Ваши пожелания успешно обновлены!\n\n"
                f"*Было:*\n{old_wishlist or 'Не указаны'}\n\n"
                f"*Стало:*\n{message.text}"
            , parse_mode="Markdown")
        else:
            await message.answer("❌ Участник не найден.")

    except Exception as e:
        logger.error(f"Ошибка обновления пожеланий: {e}")
        await message.answer("❌ Произошла ошибка при обновлении.")
    finally:
        db.close()
        await state.finish()

# ===================== КОМАНДА /stats (АДМИН) =====================
@dp.message_handler(commands=['stats'])
async def cmd_stats(message: types.Message):
    """Статистика бота (только для администратора)."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Эта команда только для администратора.")
        return

    db = SessionLocal()
    try:
        total_games = db.query(Game).count()
        active_games = db.query(Game).filter(Game.is_active == True).count()
        started_games = db.query(Game).filter(Game.is_started == True).count()
        total_players = db.query(Participant).count()

        # Самые популярные игры
        from sqlalchemy import func
        popular_games = db.query(
            Game.name,
            func.count(Participant.id).label('players')
        ).join(Participant).group_by(Game.id).order_by(func.count(Participant.id).desc()).limit(3).all()

        stats_text = (
            f"📊 *Статистика бота Тайный Санта*\n\n"
            f"*Игры всего:* {total_games}\n"
            f"• Активных: {active_games}\n"
            f"• С распределением: {started_games}\n"
            f"• Завершенных: {total_games - active_games}\n\n"
            f"*Участники:* {total_players}\n"
            f"• Среднее на игру: {round(total_players / max(total_games, 1), 1)}\n\n"
            f"*Популярные игры:*\n"
        )

        for game in popular_games:
            stats_text += f"• {game.name}: {game.players} участников\n"

        stats_text += f"\n*Последнее обновление:* {datetime.now().strftime('%d.%m.%Y %H:%M')}"

        await message.answer(stats_text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Ошибка в /stats: {e}")
        await message.answer("❌ Ошибка при получении статистики.")
    finally:
        db.close()

# ===================== КОМАНДА /end_game =====================
@dp.message_handler(commands=['end_game'])
async def cmd_end_game(message: types.Message):
    """Завершение игры (только для создателя)."""
    db = SessionLocal()
    try:
        games = db.query(Game).filter(
            Game.admin_id == message.from_user.id,
            Game.is_active == True
        ).all()

        if not games:
            await message.answer("У вас нет активных игр.")
            return

        keyboard = InlineKeyboardMarkup()
        for game in games:
            p_count = db.query(Participant).filter(Participant.game_id == game.id).count()
            keyboard.add(InlineKeyboardButton(
                f"Завершить '{game.name}' ({p_count} участников)",
                callback_data=f"end_game_{game.id}"
            ))

        await message.answer("Выберите игру для завершения:", reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Ошибка в /end_game: {e}")
        await message.answer("❌ Произошла ошибка.")
    finally:
        db.close()

@dp.callback_query_handler(lambda c: c.data.startswith('end_game_'))
async def process_end_game(callback_query: types.CallbackQuery):
    """Подтверждение и выполнение завершения игры."""
    db = SessionLocal()
    try:
        game_id = int(callback_query.data.split('_')[2])
        game = db.query(Game).filter(Game.id == game_id).first()

        if not game or game.admin_id != callback_query.from_user.id:
            await callback_query.answer("❌ Вы не можете завершить эту игру!", show_alert=True)
            return

        game.is_active = False
        db.commit()

        # Уведомляем участников
        participants = db.query(Participant).filter(Participant.game_id == game_id).all()
        for participant in participants:
            try:
                await bot.send_message(
                    participant.user_id,
                    f"ℹ️ Игра *«{game.name}»* была завершена создателем.",
                    parse_mode="Markdown"
                )
            except:
                pass  # Игнорируем ошибки отправки

        await callback_query.message.edit_text(f"✅ Игра *«{game.name}»* завершена.", parse_mode="Markdown")
        await callback_query.answer("Игра завершена!")

    except Exception as e:
        logger.error(f"Ошибка завершения игры: {e}")
        await callback_query.answer("❌ Произошла ошибка!", show_alert=True)
    finally:
        db.close()

# ===================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====================
async def show_main_menu(message: types.Message):
    """Показывает главное меню с кнопками."""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(KeyboardButton("🎮 Создать игру"), KeyboardButton("🎅 Присоединиться"))
    keyboard.row(KeyboardButton("❓ Помощь"), KeyboardButton("📋 Мои игры"))
    await message.answer("Выберите действие:", reply_markup=keyboard)

# ===================== ЗАПУСК БОТА =====================
if __name__ == '__main__':
    logger.info("Бот Тайный Санта запущен...")
    executor.start_polling(dp, skip_updates=True)
