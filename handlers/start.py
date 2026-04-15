"""
handlers/start.py — /start command, new-user registration, referral code intake.
"""
from __future__ import annotations

import secrets
import string

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from keyboards.main import main_menu_kb, onboarding_kb, start_kb
from services import referral as referral_service

router = Router()


@router.message(F.text == "🚀 Начать")
async def btn_start(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    **data,
) -> None:
    """Handle '🚀 Начать' button — same as /start."""
    await cmd_start(message, session=session, state=state)


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

        # Count total players (including the one just registered)
        count_result = await session.execute(select(func.count(User.id)))
        total_players = count_result.scalar_one()

        # Onboarding message with player count + "Что это?" button
        await message.answer(
            f"👋 Добро пожаловать в <b>Кулинарный Синдикат</b>, "
            f"<b>{message.from_user.first_name}</b>!\n\n"
            f"👥 В Синдикате уже <b>{total_players}</b> поваров.\n\n"
            f"Нажми <b>«Что это?»</b>, чтобы узнать, как всё работает,\n"
            f"или сразу выбери действие в меню ниже:",
            reply_markup=onboarding_kb(),
            parse_mode="HTML",
        )
        await message.answer(
            "Главное меню:",
            reply_markup=main_menu_kb(),
            parse_mode="HTML",
        )
        return

    # --- Existing user — just show main menu ---
    await message.answer(
        f"С возвращением, <b>{message.from_user.first_name}</b>! 🍽\n\n"
        f"Выбери действие:",
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Onboarding — explain what this bot is
# ---------------------------------------------------------------------------

_ONBOARDING_TEXT = (
    "🍳 <b>Кулинарный Синдикат</b> — это клуб осознанных завтраков.\n\n"
    "<b>Как играть:</b>\n"
    "1. Каждое утро загружай фото завтрака — получай XP\n"
    "2. Другие участники оценивают твоё фото (P2P-проверка)\n"
    "3. Проходи ежедневный квиз <i>«Специя дня»</i> за бонусные SC\n"
    "4. Копи XP → повышай уровень → открывай награды в Battle Pass\n"
    "5. Зарабатывай SC (Syndicate Coins) и трать их на подписку\n\n"
    "<b>Что дальше:</b>\n"
    "— На уровне 10 выбираешь ветку: 🥩 Мясник или 🥗 Веган\n"
    "— На уровне 50 становишься наставником и получаешь реферальный код\n"
    "— Каждый месяц среди подписчиков разыгрывается призовой фонд\n"
    "— Приведи 10 друзей на платную подписку → следующий месяц бесплатно\n\n"
    "Начни прямо сейчас — отправь фото завтрака через <b>🍳 Квест дня</b>!"
)


@router.callback_query(F.data == "onboarding_what")
async def cb_onboarding_what(
    callback: CallbackQuery,
    **data,
) -> None:
    """Show full game explanation."""
    await callback.answer()
    await callback.message.edit_text(
        _ONBOARDING_TEXT,
        parse_mode="HTML",
    )


