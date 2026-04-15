from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def subscription_kb(
    has_sc: bool,
    price: float | int = 299,
    is_ambassador: bool = False,
) -> InlineKeyboardMarkup:
    """
    Subscription payment keyboard.

    :param has_sc:        Whether to show the partial-SC payment button.
    :param price:         Subscription price displayed on the main button.
    :param is_ambassador: Whether to show the free ambassador subscription button.
    """
    builder = InlineKeyboardBuilder()
    if is_ambassador:
        builder.button(text="🦅 Активировать бесплатную подписку", callback_data="pay_ambassador")
    builder.button(text=f"💳 Оплатить {price}₽", callback_data="pay_full")
    if has_sc:
        builder.button(text="🪙 Частично SC", callback_data="pay_with_sc")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def sc_amount_kb() -> InlineKeyboardMarkup:
    """Ask the user whether they want to apply SC toward the subscription."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Использовать SC", callback_data="confirm_sc")
    builder.button(text="Нет", callback_data="skip_sc")
    builder.adjust(2)
    return builder.as_markup()
