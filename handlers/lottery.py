"""
handlers/lottery.py — /lottery, ticket list, prize fund display.
"""
from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import LotteryTicket, User
from services import lottery as lottery_service
from services import subscription as subscription_service

router = Router()


# ---------------------------------------------------------------------------
# /lottery — show user's tickets and prize fund
# ---------------------------------------------------------------------------

@router.message(Command("lottery"))
@router.message(F.text == "🎰 Лотерея")
async def cmd_lottery(
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

    current_month = datetime.utcnow().strftime("%Y-%m")

    # Fetch user's tickets for this month
    result = await session.execute(
        select(LotteryTicket).where(
            LotteryTicket.user_id == user.id,
            LotteryTicket.lottery_month == current_month,
        )
    )
    tickets: list[LotteryTicket] = list(result.scalars().all())

    # Fetch prize fund
    prize_fund = await subscription_service.get_prize_fund(session)

    # Build ticket list text
    if tickets:
        ticket_lines = "\n".join(
            f"  🎟 <code>{t.ticket_number}</code>"
            + (" ✨" if t.is_winner else "")
            for t in tickets
        )
        tickets_text = f"Твои билеты ({len(tickets)}):\n{ticket_lines}"
    else:
        tickets_text = "У тебя пока нет билетов на этот месяц."

    # Check last month winners
    last_month_result = await lottery_service.get_last_drawing_result(session)
    winners_text = ""
    if last_month_result:
        winners_text = (
            f"\n\n🏆 <b>Прошлый розыгрыш:</b>\n"
            f"Победитель: <b>{last_month_result.get('winner_name', 'Анонимный повар')}</b>\n"
            f"Выигрыш: <b>{last_month_result.get('prize', 0):.0f}₽</b>"
        )

    text = (
        f"🎰 <b>Лотерея Синдиката</b>\n\n"
        f"📅 Текущий месяц: <b>{current_month}</b>\n"
        f"🏆 Призовой фонд: <b>{prize_fund:.0f}₽</b>\n\n"
        f"{tickets_text}"
        f"{winners_text}\n\n"
        f"💡 Билеты начисляются за активность и Battle Pass."
    )

    await message.answer(text, parse_mode="HTML")
