from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def start_kb() -> ReplyKeyboardMarkup:
    """Keyboard shown to unregistered users — single 'Start' button."""
    builder = ReplyKeyboardBuilder()
    builder.button(text="🚀 Начать")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)


def main_menu_kb() -> ReplyKeyboardMarkup:
    """Main reply keyboard shown to all registered users."""
    builder = ReplyKeyboardBuilder()
    builder.button(text="👤 Профиль")
    builder.button(text="💰 Кошелёк")
    builder.button(text="🍳 Квест дня")
    builder.button(text="⚔️ Battle Pass")
    builder.button(text="🎰 Лотерея")
    builder.button(text="👥 Реферал")
    builder.button(text="💳 Подписка")
    # 2 columns: rows of 2, last row centred with 1
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup(resize_keyboard=True)
