from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_menu_kb() -> InlineKeyboardMarkup:
    """Main admin panel keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="⚙️ Настройки", callback_data="admin_settings")
    builder.button(text="🖼 Анти-фрод фото", callback_data="admin_control_photo")
    builder.button(text="📝 Квиз", callback_data="admin_quiz")
    builder.button(text="📢 Рассылка", callback_data="admin_broadcast")
    builder.button(text="🔙 Выход", callback_data="admin_exit")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def settings_kb() -> InlineKeyboardMarkup:
    """Settings sub-menu keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Цена подписки", callback_data="set_price")
    builder.button(text="🏆 % в фонд", callback_data="set_fund_percent")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    builder.adjust(2, 1)
    return builder.as_markup()


def confirm_kb(action: str) -> InlineKeyboardMarkup:
    """
    Generic Yes/No confirmation keyboard.

    Callback formats:
      confirm_{action}
      cancel_{action}
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да", callback_data=f"confirm_{action}")
    builder.button(text="❌ Нет", callback_data=f"cancel_{action}")
    builder.adjust(2)
    return builder.as_markup()
