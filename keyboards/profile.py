from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def profile_kb(level: int, branch: str | None = None) -> InlineKeyboardMarkup:
    """
    Profile inline keyboard.

    :param level:  User's current level (determines which extra buttons appear).
    :param branch: User's current branch ('butcher'|'vegan'|None).
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🖼 Аватар", callback_data="get_avatar")
    builder.button(text="🪙 История SC", callback_data="sc_history")

    if level >= 10 and branch is None:
        builder.button(text="🔀 Выбрать ветку", callback_data="choose_branch")

    if level >= 50:
        builder.button(text="🎓 Код наставника", callback_data="gen_mentor_code")

    builder.adjust(1)
    return builder.as_markup()


def branch_kb() -> InlineKeyboardMarkup:
    """Branch selection keyboard shown at level 10."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🥩 Мясник", callback_data="branch_butcher")
    builder.button(text="🥗 Веган", callback_data="branch_vegan")
    builder.adjust(2)
    return builder.as_markup()
