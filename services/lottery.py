"""
Lottery service — Кулинарный Синдикат.
Monthly drawings with public Telegram channel report.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AdminSetting, LotteryTicket, User


def _current_month() -> str:
    """Return current month as YYYY-MM string."""
    return datetime.utcnow().strftime("%Y-%m")


async def issue_ticket(session: AsyncSession, user: User) -> LotteryTicket:
    """Create and persist a new lottery ticket for the current month."""
    ticket = LotteryTicket(
        user_id=user.id,
        ticket_number=str(uuid.uuid4()),
        lottery_month=_current_month(),
    )
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)
    return ticket


async def get_user_tickets(
    session: AsyncSession,
    user_id: int,
) -> list[LotteryTicket]:
    """Return all lottery tickets the user holds for the current month."""
    result = await session.execute(
        select(LotteryTicket).where(
            LotteryTicket.user_id == user_id,
            LotteryTicket.lottery_month == _current_month(),
        )
    )
    return list(result.scalars().all())


async def run_monthly_drawing(
    session: AsyncSession,
    bot,
    channel_id: str,
) -> list[LotteryTicket]:
    """
    Pick 3 random tickets from the current month's pool, mark them as winners,
    and post a public announcement to channel_id.

    If channel_id is not provided it is read from AdminSetting key 'lottery_channel'.
    Returns the list of winning LotteryTicket objects.
    """
    month = _current_month()

    # Resolve channel from AdminSetting if not overridden
    if not channel_id:
        setting_result = await session.execute(
            select(AdminSetting).where(AdminSetting.key == "lottery_channel")
        )
        setting = setting_result.scalar_one_or_none()
        channel_id = setting.value if setting else ""

    result = await session.execute(
        select(LotteryTicket).where(
            LotteryTicket.lottery_month == month,
            LotteryTicket.is_winner.is_(False),
        )
    )
    all_tickets = list(result.scalars().all())

    if not all_tickets:
        return []

    winners = random.sample(all_tickets, min(3, len(all_tickets)))

    prize_fund = await get_monthly_fund(session)
    prize_per_winner = round(prize_fund / len(winners), 2) if winners else 0.0

    winner_lines: list[str] = []
    for i, ticket in enumerate(winners, start=1):
        ticket.is_winner = True

        user_result = await session.execute(
            select(User).where(User.id == ticket.user_id)
        )
        winner_user = user_result.scalar_one_or_none()
        display = (
            f"@{winner_user.username}"
            if winner_user and winner_user.username
            else f"ID {ticket.user_id}"
        )
        winner_lines.append(
            f"{i}. {display} — билет {ticket.ticket_number[:8]}… — {prize_per_winner} ₽"
        )

    await session.commit()

    if channel_id:
        report = (
            f"🏆 Итоги лотереи Кулинарного Синдиката за {month}!\n\n"
            + "\n".join(winner_lines)
            + f"\n\nПризовой фонд: {prize_fund} ₽"
        )
        try:
            await bot.send_message(chat_id=channel_id, text=report)
        except Exception:
            pass  # channel may be unavailable

    return winners


async def get_last_drawing_result(session: AsyncSession) -> dict | None:
    """Return the most recent lottery winner info, or None if no drawing has happened."""
    from datetime import datetime
    now = datetime.utcnow()
    last_month = (now.replace(day=1) - __import__("datetime").timedelta(days=1)).strftime("%Y-%m")

    result = await session.execute(
        select(LotteryTicket).where(
            LotteryTicket.is_winner.is_(True),
            LotteryTicket.lottery_month == last_month,
        ).limit(1)
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        return None

    user_result = await session.execute(
        select(User).where(User.id == ticket.user_id)
    )
    winner = user_result.scalar_one_or_none()
    winner_name = f"@{winner.username}" if winner and winner.username else "Анонимный повар"

    fund = await get_monthly_fund(session)
    return {"winner_name": winner_name, "prize": round(fund / 3, 2)}


async def get_monthly_fund(session: AsyncSession) -> float:
    """Delegate to subscription service to get the current month's prize fund."""
    from services import subscription as subscription_service  # lazy import

    return await subscription_service.get_prize_fund(session)
