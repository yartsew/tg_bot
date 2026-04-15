"""
Notification helpers — Кулинарный Синдикат.
Thin wrappers around bot.send_message for push notifications.
All functions are fire-and-forget; exceptions are swallowed so that a single
unreachable user never breaks a batch job.
"""
from __future__ import annotations

from database.models import DailyPhoto, LotteryTicket, User


async def notify_subscription_expiring(bot, user: User) -> None:
    """Inform the user that their subscription is about to expire."""
    end_str = (
        user.subscription_end.strftime("%d.%m.%Y")
        if user.subscription_end
        else "скоро"
    )
    try:
        await bot.send_message(
            chat_id=user.telegram_id,
            text=(
                f"⏳ Твоя подписка в Кулинарном Синдикате истекает {end_str}. "
                f"Продли её, чтобы не потерять прогресс и монеты!"
            ),
        )
    except Exception:
        pass


async def notify_sc_burn_warning(bot, user: User) -> None:
    """Warn the user that their SC will be burned in ~24 h."""
    try:
        await bot.send_message(
            chat_id=user.telegram_id,
            text=(
                f"⚠️ Через 24 часа твои SC сгорят! "
                f"У тебя на счету {user.sc_balance} SC. "
                f"Продли подписку, чтобы сохранить монеты Синдиката."
            ),
        )
    except Exception:
        pass


async def notify_p2p_review_needed(
    bot,
    user: User,
    photo: DailyPhoto,
) -> None:
    """
    Ask the user to review a breakfast photo.
    Sends the photo itself together with Approve / Reject inline buttons.
    The keyboard is imported here to avoid circular deps with keyboards module.
    """
    try:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Одобрить",
                        callback_data=f"p2p_approve:{photo.id}",
                    ),
                    InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"p2p_reject:{photo.id}",
                    ),
                ]
            ]
        )
        await bot.send_photo(
            chat_id=user.telegram_id,
            photo=photo.photo_file_id,
            caption=(
                "🍳 Новое фото на проверке!\n"
                "Это завтрак участника Синдиката. "
                "Выгляди как настоящий завтрак? Голосуй!"
            ),
            reply_markup=keyboard,
        )
    except Exception:
        pass


async def notify_quest_approved(bot, user: User) -> None:
    """Tell the user their breakfast photo was approved and they earned XP."""
    try:
        await bot.send_message(
            chat_id=user.telegram_id,
            text=f"✅ Твой завтрак одобрен! +{50} XP",
        )
    except Exception:
        pass


async def notify_level_up(bot, user: User, new_level: int) -> None:
    """Congratulate the user on levelling up."""
    try:
        await bot.send_message(
            chat_id=user.telegram_id,
            text=(
                f"🎉 Поздравляем! Ты достиг уровня {new_level} в Боевом Пропуске "
                f"Кулинарного Синдиката! Проверь новые награды в /battlepass."
            ),
        )
    except Exception:
        pass


async def notify_winner(bot, user: User, ticket: LotteryTicket) -> None:
    """Congratulate a lottery winner via private message."""
    try:
        await bot.send_message(
            chat_id=user.telegram_id,
            text=(
                f"🏆 Поздравляем! Твой лотерейный билет "
                f"{ticket.ticket_number[:8]}… выиграл в розыгрыше "
                f"Кулинарного Синдиката за {ticket.lottery_month}! "
                f"Свяжись с администратором для получения приза."
            ),
        )
    except Exception:
        pass
