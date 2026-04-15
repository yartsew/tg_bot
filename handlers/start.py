"""
handlers/start.py — /start command, new-user registration, referral code intake.
"""
from __future__ import annotations

import secrets
import string

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from keyboards.main import main_menu_kb
from services import referral as referral_service

router = Router()


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    **data,
) -> None:
    """Handle /start [ref<code>] — register new users, show main menu."""
    await state.clear()

    # Parse deep-link parameter: /start refXXXXXXXX
    ref_code: str | None = None
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) == 2 and parts[1].startswith("ref"):
            ref_code = parts[1][3:]  # strip "ref" prefix

    # Check if user already exists
    result = await session.execute(
        select(User).where(User.telegram_id == message.from_user.id)
    )
    existing_user: User | None = result.scalar_one_or_none()

    if existing_user is None:
        # --- New user registration ---
        referral_code = "".join(
            secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8)
        )
        new_user = User(
            telegram_id=message.from_user.id,
            first_name=message.from_user.first_name,
            username=message.from_user.username,
            referral_code=referral_code,
        )
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)

        if ref_code:
            await referral_service.process_referral(
                session=session,
                referred_user=new_user,
                referrer_code=ref_code,
            )

        welcome_text = (
            f"👋 Добро пожаловать в <b>Кулинарный Синдикат</b>, "
            f"<b>{message.from_user.first_name}</b>!\n\n"
            f"🍳 Здесь завтраки превращаются в прогресс.\n"
            f"Загружай фото завтрака, проходи квизы, копи SC и расти в рядах Синдиката.\n\n"
            f"Выбери действие в меню ниже:"
        )
    else:
        # --- Existing user — just show main menu ---
        welcome_text = (
            f"С возвращением, <b>{message.from_user.first_name}</b>! 🍽\n\n"
            f"Выбери действие:"
        )

    await message.answer(
        welcome_text,
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )
