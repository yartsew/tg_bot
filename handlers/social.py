"""
handlers/social.py — Faction selection (triggered at 300 users broadcast).
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Faction, User, UserFaction

router = Router()


def _factions_kb(factions: list[Faction]) -> InlineKeyboardMarkup:
    """Build inline keyboard with one button per available faction."""
    builder = InlineKeyboardBuilder()
    for faction in factions:
        icon = faction.icon_emoji or "⚑"
        builder.button(
            text=f"{icon} {faction.name}",
            callback_data=f"join_faction_{faction.id}",
        )
    builder.adjust(1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# faction_select — show available factions
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "faction_select")
async def cb_faction_select(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    # Check if already in a faction
    if user.faction is not None:
        faction_name = user.faction.faction.name if user.faction.faction else "?"
        await callback.message.answer(
            f"Ты уже состоишь в фракции <b>{faction_name}</b>.",
            parse_mode="HTML",
        )
        return

    # Query all available factions from DB
    result = await session.execute(select(Faction).order_by(Faction.id))
    factions: list[Faction] = list(result.scalars().all())

    if not factions:
        await callback.message.answer(
            "⚑ Фракции пока не созданы. Загляни позже!"
        )
        return

    text = "⚑ <b>Фракции Синдиката</b>\n\nВыбери фракцию, к которой хочешь присоединиться:\n\n"
    for faction in factions:
        icon = faction.icon_emoji or "⚑"
        desc = faction.description or ""
        text += f"{icon} <b>{faction.name}</b>\n{desc}\n\n"

    await callback.message.answer(
        text.strip(),
        reply_markup=_factions_kb(factions),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# join_faction_{id} — save UserFaction
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("join_faction_"))
async def cb_join_faction(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    faction_id_str = callback.data.replace("join_faction_", "")
    try:
        faction_id = int(faction_id_str)
    except ValueError:
        await callback.message.answer("Некорректный ID фракции.")
        return

    # Verify faction exists
    result = await session.execute(select(Faction).where(Faction.id == faction_id))
    faction: Faction | None = result.scalar_one_or_none()

    if faction is None:
        await callback.message.answer("Фракция не найдена.")
        return

    # Check if user already has a faction
    if user.faction is not None:
        current_faction_name = user.faction.faction.name if user.faction.faction else "?"
        await callback.message.edit_text(
            f"Ты уже состоишь в фракции <b>{current_faction_name}</b>. "
            f"Смена фракции недоступна.",
            parse_mode="HTML",
        )
        return

    # Save faction membership
    user_faction = UserFaction(user_id=user.id, faction_id=faction_id)
    session.add(user_faction)
    await session.commit()

    icon = faction.icon_emoji or "⚑"
    await callback.message.edit_text(
        f"✅ Ты вступил во фракцию {icon} <b>{faction.name}</b>!\n\n"
        f"Добро пожаловать в ряды своих собратьев по кулинарному пути.",
        parse_mode="HTML",
    )
