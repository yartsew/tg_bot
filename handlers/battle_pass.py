"""
handlers/battle_pass.py — /battlepass, progress view, claim rewards.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from services import battle_pass as battle_pass_service

router = Router()


def _claimable_rewards_kb(claimable_rewards: list[dict]) -> InlineKeyboardMarkup:
    """Build inline keyboard with one claim button per unclaimed reward, showing type."""
    _icons = {"sc": "🪙", "ticket": "🎟", "guide": "📖"}
    builder = InlineKeyboardBuilder()
    for r in claimable_rewards:
        level = r["level"]
        rtype = r.get("reward_type", "")
        amount = r.get("reward_amount", 0)
        icon = _icons.get(rtype, "🎁")
        if rtype == "sc":
            label = f"{icon} {amount} SC — уровень {level}"
        elif rtype == "ticket":
            label = f"{icon} Лотерейный билет — уровень {level}"
        elif rtype == "guide":
            label = f"{icon} Кулинарный гайд — уровень {level}"
        else:
            label = f"🎁 Уровень {level}"
        builder.button(text=label, callback_data=f"claim_reward_{level}")
    builder.adjust(1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# /battlepass — show progress summary and claimable rewards
# ---------------------------------------------------------------------------

@router.message(Command("battlepass"))
@router.message(F.text == "⚔️ Battle Pass")
async def cmd_battlepass(
    message: Message,
    session: AsyncSession,
    user: User | None,
    state: FSMContext,
    **data,
) -> None:
    await state.clear()

    if user is None:
        await message.answer("Сначала введи /start, чтобы зарегистрироваться.")
        return

    summary = await battle_pass_service.get_progress_summary(session, user)

    claimable_rewards: list[dict] = summary.get("claimable_rewards", [])
    next_level_xp: int = summary.get("xp_to_next_level", 0)
    current_level: int = summary.get("current_level", user.level)

    # Build progress bar (10 segments)
    progress_pct = summary.get("level_progress_pct", 0.0)
    filled = int(progress_pct / 10)
    bar = "█" * filled + "░" * (10 - filled)

    text = (
        f"⚔️ <b>Battle Pass</b>\n\n"
        f"Уровень: <b>{current_level}</b>\n"
        f"XP: <b>{user.xp}</b>\n"
        f"До следующего уровня: <b>{next_level_xp} XP</b>\n"
        f"[{bar}] {progress_pct:.0f}%\n"
    )

    if current_level >= 50:
        text += "\n🏆 <b>Бесконечный режим активен!</b> Каждые 1000 XP — новая награда.\n"

    if claimable_rewards:
        text += f"\n🎁 <b>Доступно наград: {len(claimable_rewards)}</b>\nЗабери их ниже!"
        await message.answer(text, reply_markup=_claimable_rewards_kb(claimable_rewards), parse_mode="HTML")
    else:
        text += "\nВсе текущие награды получены. Продолжай зарабатывать XP!"
        await message.answer(text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# claim_reward_{level} — claim a specific level reward
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("claim_reward_"))
async def cb_claim_reward(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    level_str = callback.data.replace("claim_reward_", "")
    try:
        level = int(level_str)
    except ValueError:
        await callback.message.answer("Некорректный уровень.")
        return

    result = await battle_pass_service.claim_reward(
        session=session,
        user=user,
        level=level,
    )

    if not result.get("success"):
        reason = result.get("reason", "Неизвестная ошибка")
        await callback.message.answer(
            f"❌ Не удалось получить награду: {reason}",
            parse_mode="HTML",
        )
        return

    reward_type = result.get("reward_type", "")
    reward_amount = result.get("reward_amount", 0)
    reward_desc = result.get("reward_description", "")

    reward_text = ""
    if reward_type == "sc":
        reward_text = f"🪙 <b>{reward_amount} SC</b> зачислены на твой баланс"
    elif reward_type == "ticket":
        reward_text = f"🎟 <b>Лотерейный билет</b> добавлен в твою коллекцию"
    elif reward_type == "guide":
        reward_text = f"📖 <b>Кулинарный гайд разблокирован</b>\n{reward_desc}"
    else:
        reward_text = f"<b>{reward_desc}</b>"

    await callback.message.edit_text(
        f"🎁 <b>Награда получена!</b>\n\n"
        f"Уровень <b>{level}</b>: {reward_text}",
        parse_mode="HTML",
    )
