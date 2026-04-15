"""
Subscription management — Кулинарный Синдикат.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

import config
from database.models import AdminSetting, Subscription, User


async def get_active_subscription(
    session: AsyncSession,
    user_id: int,
) -> Subscription | None:
    """Return the current active subscription for a user, or None."""
    result = await session.execute(
        select(Subscription)
        .where(
            Subscription.user_id == user_id,
            Subscription.status == "active",
        )
        .order_by(Subscription.end_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_subscription_price(session: AsyncSession) -> float:
    """Read subscription_price from AdminSetting; fall back to config default."""
    result = await session.execute(
        select(AdminSetting).where(AdminSetting.key == "subscription_price")
    )
    setting = result.scalar_one_or_none()
    if setting is not None:
        try:
            return float(setting.value)
        except (ValueError, TypeError):
            pass
    return config.DEFAULT_SUBSCRIPTION_PRICE


async def get_prize_fund_percent(session: AsyncSession) -> float:
    """Read prize_fund_percent from AdminSetting; fall back to config default."""
    result = await session.execute(
        select(AdminSetting).where(AdminSetting.key == "prize_fund_percent")
    )
    setting = result.scalar_one_or_none()
    if setting is not None:
        try:
            return float(setting.value)
        except (ValueError, TypeError):
            pass
    return config.DEFAULT_PRIZE_FUND_PERCENT


async def get_prize_fund(session: AsyncSession) -> float:
    """
    Calculate the prize fund for the current calendar month.
    = sum(price_paid) of all active subscriptions created this month
      * prize_fund_percent.
    """
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    result = await session.execute(
        select(func.coalesce(func.sum(Subscription.price_paid), 0.0)).where(
            Subscription.status == "active",
            Subscription.start_date >= month_start,
        )
    )
    total_revenue: float = result.scalar_one()
    percent = await get_prize_fund_percent(session)
    return round(total_revenue * percent, 2)


async def create_subscription(
    session: AsyncSession,
    user: User,
    price: float,
    sc_used: int = 0,
    payment_id: str | None = None,
) -> Subscription:
    """
    Create a 30-day subscription for the user.
    Updates user.is_subscribed and user.subscription_end.
    """
    now = datetime.utcnow()
    end_date = now + timedelta(days=30)

    subscription = Subscription(
        user_id=user.id,
        start_date=now,
        end_date=end_date,
        price_paid=price,
        sc_paid=sc_used,
        status="active",
        renewal_attempts=0,
        telegram_payment_id=payment_id,
    )
    session.add(subscription)

    user.is_subscribed = True
    user.subscription_end = end_date

    await session.commit()
    await session.refresh(subscription)
    return subscription


async def expire_subscription(session: AsyncSession, user: User) -> None:
    """Mark the user's active subscription as expired and update user flags."""
    result = await session.execute(
        select(Subscription)
        .where(
            Subscription.user_id == user.id,
            Subscription.status == "active",
        )
        .order_by(Subscription.end_date.desc())
        .limit(1)
    )
    subscription = result.scalar_one_or_none()
    if subscription:
        subscription.status = "expired"

    user.is_subscribed = False
    await session.commit()


async def retry_failed_subscriptions(session: AsyncSession, bot) -> None:
    """
    Find failed subscriptions with fewer than 3 renewal attempts whose last attempt
    was more than 24 h ago. Increment attempts and send a payment request to the user.
    After 3 failed attempts, set status='blocked' and block the user account.
    """
    retry_threshold = datetime.utcnow() - timedelta(hours=24)

    result = await session.execute(
        select(Subscription).where(
            Subscription.status == "failed",
            Subscription.renewal_attempts < 3,
            (Subscription.last_attempt == None)  # noqa: E711
            | (Subscription.last_attempt < retry_threshold),
        )
    )
    subscriptions = list(result.scalars().all())

    for sub in subscriptions:
        sub.renewal_attempts += 1
        sub.last_attempt = datetime.utcnow()

        # Load related user
        user_result = await session.execute(
            select(User).where(User.id == sub.user_id)
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            continue

        if sub.renewal_attempts >= 3:
            sub.status = "blocked"
            user.subscription_blocked = True
            try:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        "🚫 Твоя подписка заблокирована после трёх неудачных "
                        "попыток списания. Пожалуйста, обратись к администратору."
                    ),
                )
            except Exception:
                pass
        else:
            try:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        f"⚠️ Попытка {sub.renewal_attempts}/3: не удалось продлить "
                        f"подписку. Пожалуйста, оплати подписку, чтобы продолжить "
                        f"пользоваться Кулинарным Синдикатом. Следующая попытка — "
                        f"через 24 часа."
                    ),
                )
            except Exception:
                pass

    await session.commit()


async def check_and_expire_subscriptions(session: AsyncSession) -> list[User]:
    """
    Find users whose subscription_end is in the past and who are still marked
    as subscribed. Call expire_subscription for each and return the list.
    """
    now = datetime.utcnow()

    result = await session.execute(
        select(User).where(
            User.subscription_end < now,
            User.is_subscribed.is_(True),
        )
    )
    users = list(result.scalars().all())

    for user in users:
        await expire_subscription(session, user)

    return users
