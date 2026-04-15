"""
Syndicate Coins (SC) operations — Кулинарный Синдикат.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from database.models import SCTransaction, User


async def add_sc(
    session: AsyncSession,
    user: User,
    amount: int,
    description: str,
) -> User:
    """Add SC to a user's balance and record the transaction. Returns updated user."""
    user.sc_balance = (user.sc_balance or 0) + amount
    tx = SCTransaction(
        user_id=user.id,
        amount=amount,
        description=description,
    )
    session.add(tx)
    await session.commit()
    await session.refresh(user)
    return user


async def deduct_sc(
    session: AsyncSession,
    user: User,
    amount: int,
    description: str,
) -> bool:
    """
    Deduct SC from a user if they have sufficient balance.
    Creates a negative SCTransaction.
    Returns True if deduction succeeded, False if insufficient funds.
    """
    if (user.sc_balance or 0) < amount:
        return False
    user.sc_balance -= amount
    tx = SCTransaction(
        user_id=user.id,
        amount=-amount,
        description=description,
    )
    session.add(tx)
    await session.commit()
    await session.refresh(user)
    return True


async def get_transactions(
    session: AsyncSession,
    user_id: int,
    limit: int = 20,
) -> list[SCTransaction]:
    """Return the most recent SC transactions for a user."""
    result = await session.execute(
        select(SCTransaction)
        .where(SCTransaction.user_id == user_id)
        .order_by(SCTransaction.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def burn_expired_coins(session: AsyncSession, bot) -> int:
    """
    Find users who are unsubscribed and whose subscription ended more than 168 h ago.
    Zero out their SC balance, create a burn transaction, and notify them via bot.
    Returns the count of users affected.
    """
    burn_threshold = datetime.utcnow() - timedelta(hours=config.SC_BURN_AFTER_HOURS)

    result = await session.execute(
        select(User).where(
            User.is_subscribed.is_(False),
            User.subscription_end < burn_threshold,
            User.sc_balance > 0,
        )
    )
    users = list(result.scalars().all())

    for user in users:
        burned_amount = user.sc_balance
        tx = SCTransaction(
            user_id=user.id,
            amount=-burned_amount,
            description=f"сгорели",
        )
        session.add(tx)
        user.sc_balance = 0

        try:
            await bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    f"🔥 {burned_amount} SC сгорели, так как твоя подписка "
                    f"истекла более 7 дней назад. Продли подписку, чтобы "
                    f"зарабатывать и хранить монеты Синдиката!"
                ),
            )
        except Exception:
            pass  # user may have blocked the bot

    await session.commit()
    return len(users)


async def get_users_to_warn_burn(session: AsyncSession) -> list[User]:
    """
    Return users who should receive a SC-burn warning:
    unsubscribed, subscription ended more than 144 h ago, and still have SC.
    (24 h before the actual 168 h burn window.)
    """
    warn_threshold = datetime.utcnow() - timedelta(hours=config.SC_BURN_WARN_HOURS)

    result = await session.execute(
        select(User).where(
            User.is_subscribed.is_(False),
            User.subscription_end < warn_threshold,
            User.sc_balance > 0,
        )
    )
    return list(result.scalars().all())
