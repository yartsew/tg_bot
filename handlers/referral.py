"""
handlers/referral.py — /referral, referral link, active friends, ambassador status.
"""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from services import referral as referral_service

router = Router()


# ---------------------------------------------------------------------------
# /referral — show referral info
# ---------------------------------------------------------------------------

@router.message(Command("referral"))
@router.message(F.text == "👥 Реферал")
async def cmd_referral(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    user: User | None,
    state: FSMContext,
    **data,
) -> None:
    await state.clear()

    if user is None:
        await message.answer("Сначала введи /start, чтобы зарегистрироваться.")
        return

    bot_info = await bot.get_me()
    referral_link = referral_service.generate_referral_link(user, bot_info.username)
    active_friends_count = await referral_service.count_active_friends(session, user.id)
    ambassador_status = await referral_service.ambassador_check(session, user)

    from config import AMBASSADOR_FRIENDS_REQUIRED

    if ambassador_status:
        ambassador_text = (
            "🦅 <b>Ты Амбассадор Синдиката!</b>\n"
            "Следующая подписка для тебя — <b>бесплатно</b>!"
        )
    else:
        remaining = AMBASSADOR_FRIENDS_REQUIRED - active_friends_count
        ambassador_text = (
            f"Осталось привести: <b>{remaining}</b> активных друзей "
            f"до статуса Амбассадора"
        )

    text = (
        f"👥 <b>Реферальная программа</b>\n\n"
        f"Твоя реферальная ссылка:\n"
        f"{referral_link}\n\n"
        f"Активных друзей: <b>{active_friends_count}</b> / {AMBASSADOR_FRIENDS_REQUIRED}\n\n"
        f"{ambassador_text}\n\n"
        f"💡 Приглашай друзей — за каждого активного получаешь бонусы SC!"
    )

    await message.answer(text, parse_mode="HTML")
