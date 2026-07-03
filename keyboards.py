from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu(is_mining):
    status_text = "⏹ Остановить майнер" if is_mining else "▶️ Запустить майнер"
    keyboard = [
        [InlineKeyboardButton(text=status_text, callback_data="toggle_mining")],
        [InlineKeyboardButton(text="🔄 Обновить баланс", callback_data="refresh_balance")],
        [InlineKeyboardButton(text="💎 Ускорить x2", callback_data="boost")],
        [InlineKeyboardButton(text="💳 Вывод", callback_data="withdraw")],
        [InlineKeyboardButton(text="👥 Пригласить друга", callback_data="referral")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])