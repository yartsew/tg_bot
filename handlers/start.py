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
from keyboards.main import main_menu_kb, onboarding_join_kb, onboarding_kb
from services import referral as referral_service

router = Router()

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
    "Нажми кнопку ниже — и добро пожаловать в Синдикат!"
)


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    **data,
) -> None:
    """Handle /start [ref<code>] — show onboarding or main menu."""
    await state.clear()

    # Check if user already exists
    result = await session.execute(
        select(User).where(User.telegram_id == message.from_user.id)
    )
    existing_user: User | None = result.scalar_one_or_none()

    if existing_user is not None:
        await message.answer(
            f"С возвращением, <b>{message.from_user.first_name}</b>! 🍽\n\n"
            f"Выбери действие:",
            reply_markup=main_menu_kb(),
            parse_mode="HTML",
        )
        return

    # --- New user: show onboarding before registration ---
    # Parse deep-link ref code and save to state for use after "Вступить"
    ref_code: str | None = None
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) == 2 and parts[1].startswith("ref"):
            ref_code = parts[1][3:]
    await state.update_data(ref_code=ref_code)

    count_result = await session.execute(select(func.count(User.id)))
    total_players = count_result.scalar_one()

    await message.answer(
        f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
        f"🍳 Это <b>Кулинарный Синдикат</b> — клуб осознанных завтраков.\n\n"
        f"👥 В Синдикате уже <b>{total_players}</b> поваров.\n\n"
        f"Узнай, как всё работает, или сразу вступай:",
        reply_markup=onboarding_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "onboarding_what")
async def cb_onboarding_what(
    callback: CallbackQuery,
    **data,
) -> None:
    """Show full game explanation with a join button."""
    await callback.answer()
    await callback.message.edit_text(
        _ONBOARDING_TEXT,
        reply_markup=onboarding_join_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "onboarding_register")
async def cb_onboarding_register(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    **data,
) -> None:
    """Register the user and show main menu."""
    await callback.answer()

    # Guard: user might have already registered (double-tap)
    result = await session.execute(
        select(User).where(User.telegram_id == callback.from_user.id)
    )
    if result.scalar_one_or_none() is not None:
        await callback.message.answer(
            "Ты уже в Синдикате! Выбери действие:",
            reply_markup=main_menu_kb(),
        )
        return

    # Get ref_code saved during /start
    fsm_data = await state.get_data()
    ref_code: str | None = fsm_data.get("ref_code")
    await state.clear()

    referral_code = "".join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8)
    )
    new_user = User(
        telegram_id=callback.from_user.id,
        first_name=callback.from_user.first_name,
        username=callback.from_user.username,
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

    await callback.message.edit_text(
        f"✅ <b>Добро пожаловать в Синдикат, {callback.from_user.first_name}!</b>\n\n"
        f"Начни с <b>🍳 Квест дня</b> — загрузи фото завтрака и заработай первые XP.",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "Главное меню:",
        reply_markup=main_menu_kb(),
    )
