from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

_OPTION_LABELS = ["A", "B", "C", "D"]


def quest_menu_kb() -> InlineKeyboardMarkup:
    """Top-level quest menu keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📸 Отправить завтрак", callback_data="submit_photo")
    builder.button(text="🌶 Специя дня", callback_data="daily_quiz")
    builder.button(text="👁 Народный контроль", callback_data="p2p_review")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def quiz_options_kb(options: list[str], question_id: int) -> InlineKeyboardMarkup:
    """
    Four answer-option buttons labelled A/B/C/D.

    Callback format: quiz_answer:{question_id}:{index}
    """
    builder = InlineKeyboardBuilder()
    for index, (label, text) in enumerate(zip(_OPTION_LABELS, options)):
        builder.button(
            text=f"{label}. {text}",
            callback_data=f"quiz_answer:{question_id}:{index}",
        )
    builder.adjust(1)
    return builder.as_markup()


def quiz_retry_kb(question_id: int) -> InlineKeyboardMarkup:
    """Retry button shown after a wrong quiz answer (costs 10 SC)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔄 Попробовать ещё раз (10 SC)",
        callback_data=f"quiz_retry:{question_id}",
    )
    builder.adjust(1)
    return builder.as_markup()


def control_photo_kb(control_photo_id: int) -> InlineKeyboardMarkup:
    """
    Approve / reject keyboard for anti-fraud control photo.

    Callback formats:
      control_approve:{control_photo_id}
      control_reject:{control_photo_id}
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Завтрак", callback_data=f"control_approve:{control_photo_id}")
    builder.button(text="❌ Не завтрак", callback_data=f"control_reject:{control_photo_id}")
    builder.adjust(2)
    return builder.as_markup()


def p2p_vote_kb(photo_id: int) -> InlineKeyboardMarkup:
    """
    Approve / reject keyboard for P2P photo review.

    Callback formats:
      p2p_approve:{photo_id}
      p2p_reject:{photo_id}
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Завтрак", callback_data=f"p2p_approve:{photo_id}")
    builder.button(text="❌ Не завтрак", callback_data=f"p2p_reject:{photo_id}")
    builder.adjust(2)
    return builder.as_markup()
