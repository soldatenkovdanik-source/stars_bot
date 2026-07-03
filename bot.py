import asyncio
import logging
from datetime import datetime
import aiosqlite

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from aiohttp import web

from config import *
from database import *
from keyboards import *

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_withdraw_state = {}

# ========== ВЕБ-СЕРВЕР ДЛЯ RENDER ==========

async def health_check(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    print("✅ Веб-сервер запущен на порту 8080")

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def format_balance(balance):
    return f"{balance:.4f}"

def format_speed(speed):
    return f"{speed:.1f}"

async def get_main_menu_text(user_id):
    balance = await get_balance(user_id)
    speed = await update_user_speed(user_id)
    referrals = await get_referrals_count(user_id)
    is_mining_active = await is_mining(user_id)

    status = "🟢 МАЙНИНГ АКТИВЕН" if is_mining_active else "🔴 МАЙНЕР ОСТАНОВЛЕН"
    text = (
        f"{status}\n\n"
        f"• Баланс — {format_balance(balance)}\n"
        f"• Скорость — {format_speed(speed)} 🥳/час\n"
        f"• Активных рефералов — {referrals}\n\n"
    )
    if is_mining_active:
        text += "🥳 Майнинг идёт...\n"
    else:
        text += "Нажмите «Запустить майнер» чтобы начать майнить.\n"
    return text

async def safe_edit_text(message, text, reply_markup=None, parse_mode=None):
    """Безопасно редактирует сообщение, избегая ошибки 'message is not modified'"""
    try:
        await message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception as e:
        if "message is not modified" in str(e):
            pass
        else:
            raise e

# ========== ОБРАБОТЧИК ЗАЯВОК ==========

@dp.chat_join_request()
async def handle_join_request(update: types.ChatJoinRequest):
    user_id = update.from_user.id
    chat_id = update.chat.id

    required_channels = await get_required_channels()
    for ch_id, channel_id, invite_link, title in required_channels:
        if channel_id == chat_id:
            task_type = f"required_{ch_id}"
            if not await is_task_completed(user_id, task_type):
                await complete_task(user_id, task_type)
                print(f"✅ Задание {task_type} выполнено для {user_id} (подана заявка)")
            
            all_done = True
            for ch_id2, channel_id2, _, _ in required_channels:
                task_type2 = f"required_{ch_id2}"
                if not await is_task_completed(user_id, task_type2):
                    all_done = False
                    break
            
            if all_done:
                await set_verified(user_id)
                await bot.send_message(
                    user_id,
                    "🎉 Вы подали заявки во все обязательные каналы! Ожидайте одобрения администратором."
                )
            break

    boost_items = await get_boost_items()
    for item_id, item_type, link, channel_id, title in boost_items:
        if item_type == "channel" and channel_id == chat_id:
            task_type = f"boost_{item_id}"
            if not await is_task_completed(user_id, task_type):
                await complete_task(user_id, task_type)
                print(f"✅ Задание для ускорения {task_type} выполнено для {user_id} (подана заявка)")
            break

# ========== ПОКАЗ ОБЯЗАТЕЛЬНЫХ КАНАЛОВ ПРИ СТАРТЕ ==========

async def show_required_channels(message: types.Message, user_id: int):
    channels = await get_required_channels()
    
    if not channels:
        await set_verified(user_id)
        text = await get_main_menu_text(user_id)
        await message.answer(
            text,
            parse_mode=None,
            reply_markup=main_menu(await is_mining(user_id))
        )
        return
    
    text = "🌟 *ДОБРО ПОЖАЛОВАТЬ!*\n\nДля получения доступа к боту, нажми на кнопку канала и подай заявку на вступление.\n\n"
    keyboard = []
    
    for idx, (ch_id, channel_id, invite_link, title) in enumerate(channels, 1):
        task_type = f"required_{ch_id}"
        status = "✅" if await is_task_completed(user_id, task_type) else "⬜"
        name = title or f"Канал {idx}"
        keyboard.append([InlineKeyboardButton(text=f"{status} {name}", url=invite_link)])
    
    keyboard.append([InlineKeyboardButton(text="🔄 Проверить статус", callback_data="check_required")])
    
    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@dp.callback_query(lambda c: c.data == "check_required")
async def check_required(callback: types.CallbackQuery):
    await callback.answer()  # <-- Сразу подтверждаем колбэк
    user_id = callback.from_user.id
    channels = await get_required_channels()
    all_completed = True
    errors = []

    for ch_id, channel_id, invite_link, title in channels:
        task_type = f"required_{ch_id}"
        if await is_task_completed(user_id, task_type):
            continue
        else:
            all_completed = False
            errors.append(f"❌ Вы не подали заявку в канал {title or channel_id}")

    if all_completed:
        await set_verified(user_id)
        text = await get_main_menu_text(user_id)
        await safe_edit_text(callback.message, text, main_menu(await is_mining(user_id)), parse_mode=None)
    else:
        error_text = "❌ Вы не подали заявки во все каналы.\n\n" + "\n".join(errors[:5])
        await safe_edit_text(
            callback.message,
            error_text,
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Проверить снова", callback_data="check_required")]
            ]),
            parse_mode=None
        )

# ========== СТАРТ ==========

@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username

    referrer_id = None
    if message.text and " " in message.text:
        ref_code = message.text.split(" ")[1]
        if ref_code.isdigit():
            referrer_id = int(ref_code)

    user = await get_user(user_id)
    if not user:
        await create_user(user_id, username, referrer_id)
        if referrer_id:
            await bot.send_message(referrer_id, f"👤 По вашей ссылке зарегистрировался новый пользователь! Скорость майнинга увеличена.")
    else:
        if referrer_id and not user[5]:
            async with aiosqlite.connect(DB_NAME) as conn:
                await conn.execute("UPDATE users SET referrer_id = ? WHERE user_id = ?", (referrer_id, user_id))
                await conn.execute("UPDATE users SET speed = speed + 0.1 WHERE user_id = ?", (referrer_id,))
                await conn.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referrer_id, user_id))
                await conn.commit()
            await bot.send_message(referrer_id, f"👤 По вашей ссылке зарегистрировался новый пользователь! Скорость майнинга увеличена.")

    if not user or not user[6]:
        async with aiosqlite.connect(DB_NAME) as conn:
            await conn.execute("UPDATE users SET ref_link_created = 1 WHERE user_id = ?", (user_id,))
            await conn.commit()

    if not await is_verified(user_id):
        await show_required_channels(message, user_id)
    else:
        text = await get_main_menu_text(user_id)
        await message.answer(
            text,
            parse_mode=None,
            reply_markup=main_menu(await is_mining(user_id))
        )

# ========== ОСТАЛЬНЫЕ ОБРАБОТЧИКИ ==========

@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    text = await get_main_menu_text(user_id)
    await safe_edit_text(callback.message, text, main_menu(await is_mining(user_id)), parse_mode=None)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "toggle_mining")
async def toggle_mining(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if await is_mining(user_id):
        await stop_mining(user_id)
        await callback.answer("⏹ Майнер остановлен")
    else:
        await start_mining(user_id)
        await callback.answer("▶️ Майнер запущен")
    text = await get_main_menu_text(user_id)
    await safe_edit_text(callback.message, text, main_menu(await is_mining(user_id)), parse_mode=None)

@dp.callback_query(lambda c: c.data == "refresh_balance")
async def refresh_balance(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    balance = await get_balance(user_id)
    await callback.answer(f"💰 Твой баланс: {format_balance(balance)} 🥳", show_alert=True)
    text = await get_main_menu_text(user_id)
    await safe_edit_text(callback.message, text, main_menu(await is_mining(user_id)), parse_mode=None)

# ========== УСКОРЕНИЕ x2 ==========

@dp.callback_query(lambda c: c.data == "boost")
async def boost_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if await is_boost_active(user_id):
        await callback.answer("⏳ Ускорение x2 уже активно!", show_alert=True)
        return

    items = await get_boost_items()
    if not items:
        await safe_edit_text(
            callback.message,
            "❌ Нет доступных элементов для ускорения. Добавьте их в config.py (BOOST_ITEMS)",
            back_keyboard(),
            parse_mode=None
        )
        await callback.answer()
        return

    text = "УСКОРЕНИЕ x2 НА 1 ЧАС\n\nВыполни задания и получи скорость x2 на 1 час!\n"
    keyboard = []

    for idx, (item_id, item_type, link, channel_id, title) in enumerate(items, 1):
        task_type = f"boost_{item_id}"
        status = "✅" if await is_task_completed(user_id, task_type) else "⬜"
        name = title or f"Задание {idx}"
        
        if link:
            url = link
            button_text = f"{status} {name}"
            keyboard.append([InlineKeyboardButton(text=button_text, url=url)])
        else:
            text += f"\n{status} {name} (ссылка недоступна)"

    keyboard.append([InlineKeyboardButton(text="🔄 Проверить", callback_data="check_boost")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])

    await safe_edit_text(
        callback.message,
        text,
        InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode=None
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "check_boost")
async def check_boost(callback: types.CallbackQuery):
    await callback.answer()  # <-- Сразу подтверждаем
    user_id = callback.from_user.id
    items = await get_boost_items()
    
    if not items:
        return

    all_completed = True
    errors = []

    for item_id, item_type, link, channel_id, title in items:
        task_type = f"boost_{item_id}"
        if await is_task_completed(user_id, task_type):
            continue

        if item_type == "bot":
            await complete_task(user_id, task_type)
            print(f"✅ Задание для бота {title} выполнено для {user_id} (автоматически)")
        elif item_type == "channel":
            if channel_id is None:
                errors.append(f"❌ Неизвестный ID для канала {title}")
                all_completed = False
                continue
            try:
                member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
                if member.status in ["member", "administrator", "creator"]:
                    await complete_task(user_id, task_type)
                else:
                    all_completed = False
                    errors.append(f"❌ Вы не подали заявку в канал {title or channel_id}")
            except Exception as e:
                all_completed = False
                errors.append(f"❌ Ошибка проверки заявки в канал {title or channel_id}: {e}")
        else:
            all_completed = False
            errors.append(f"❌ Неизвестный тип элемента: {item_type}")

    if all_completed:
        await set_boost(user_id, 1)
        await update_user_speed(user_id)
        text = await get_main_menu_text(user_id)
        await safe_edit_text(callback.message, text, main_menu(await is_mining(user_id)), parse_mode=None)
    else:
        error_text = "❌ Вы не выполнили все задания.\n\n" + "\n".join(errors[:5])
        await safe_edit_text(
            callback.message,
            error_text,
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Проверить снова", callback_data="check_boost")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
            ]),
            parse_mode=None
        )

# ========== РЕФЕРАЛКА ==========

@dp.callback_query(lambda c: c.data == "referral")
async def referral_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    me = await bot.get_me()
    bot_username = me.username
    ref_link = f"https://t.me/{bot_username}?start={user_id}"
    referrals = await get_referrals_count(user_id)
    text = (
        f"ВАША РЕФЕРАЛЬНАЯ ССЫЛКА:\n"
        f"{ref_link}\n\n"
        f"+0.1 🥳/час за каждого реферала с активным майнером.\n"
        f"Активных рефералов: {referrals}"
    )
    keyboard = [
        [InlineKeyboardButton(text="👥 Пригласить друга", url=f"https://t.me/share/url?url={ref_link}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
    ]
    await safe_edit_text(callback.message, text, InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode=None)
    await callback.answer()

# ========== ВЫВОД ==========

@dp.callback_query(lambda c: c.data == "withdraw")
async def withdraw_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_withdraw_state[user_id] = {"step": "awaiting_username"}
    text = "ВЫВОД ЗВЁЗД\n\nШаг 1/2 — на какой юзернейм вывести?\n\nОтправьте @username"
    keyboard = [[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]]
    await safe_edit_text(callback.message, text, InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode=None)
    await callback.answer()

@dp.message()
async def handle_withdraw_input(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_withdraw_state:
        return

    step = user_withdraw_state[user_id].get("step")
    if step == "awaiting_username":
        target_username = message.text.strip()
        if not target_username.startswith("@"):
            await message.answer("❌ Используйте @username")
            return
        user_withdraw_state[user_id]["target"] = target_username
        user_withdraw_state[user_id]["step"] = "awaiting_amount"
        await message.answer("Шаг 2/2 — сколько звёзд вывести?\n\nОтправьте число")
    elif step == "awaiting_amount":
        try:
            amount = float(message.text.strip())
            if amount <= 0:
                await message.answer("❌ Сумма должна быть положительной")
                return
        except ValueError:
            await message.answer("❌ Введите число")
            return

        target_username = user_withdraw_state[user_id]["target"]
        balance = await get_balance(user_id)
        if amount > balance:
            await message.answer(f"❌ Недостаточно. Баланс: {format_balance(balance)}")
            return

        await update_balance(user_id, -amount)

        await bot.send_message(
            ADMIN_ID,
            f"🔔 ЗАЯВКА НА ВЫВОД\n\n👤 @{message.from_user.username or user_id}\n📤 Получатель: {target_username}\n💰 Сумма: {format_balance(amount)} 🥳"
        )

        await message.answer(f"✅ Заявка на вывод {format_balance(amount)} 🥳 для {target_username} отправлена!")

        del user_withdraw_state[user_id]
        text = await get_main_menu_text(user_id)
        await message.answer(text, parse_mode=None, reply_markup=main_menu(await is_mining(user_id)))

# ========== МАЙНИНГ ==========

async def mining_loop():
    while True:
        await asyncio.sleep(10)
        try:
            async with aiosqlite.connect(DB_NAME) as conn:
                cursor = await conn.execute("SELECT user_id, mining_start FROM users WHERE is_mining = 1")
                miners = await cursor.fetchall()
                now = datetime.now().timestamp()
                for user_id, mining_start in miners:
                    elapsed = now - mining_start
                    if elapsed > 0:
                        speed = await get_speed(user_id)
                        reward = (speed / 3600) * elapsed
                        if reward > 0:
                            await update_balance(user_id, reward)
                            await conn.execute("UPDATE users SET mining_start = ? WHERE user_id = ?", (now, user_id))
                            print(f"✅ Начислено {reward} пользователю {user_id}")
                await conn.commit()
        except Exception as e:
            logging.error(f"Ошибка в mining_loop: {e}")

# ========== ЗАПУСК ==========

async def main():
    await init_db(bot)
    print("🤖 Бот-майнер запущен!")
    asyncio.create_task(mining_loop())
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
