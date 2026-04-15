"""
Referral & Ambassador system — Кулинарный Синдикат.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from database.models import AdminSetting, Referral, User


async def process_referral(
    session: AsyncSession,
    new_user: User,
    referral_code: str,
) -> bool:
    """
    Link new_user to the owner of referral_code.
    Creates a Referral record and gives the referrer a 50 SC bonus.
    Returns True if successful, False if the code is invalid or already used.
    """
    # Find the referrer
    referrer_result = await session.execute(
        select(User).where(User.referral_code == referral_code)
    )
    referrer = referrer_result.scalar_one_or_none()

    if referrer is None or referrer.id == new_user.id:
        return False

    # Prevent duplicate referral records
    existing = await session.execute(
        select(Referral).where(Referral.referred_id == new_user.id)
    )
    if existing.scalar_one_or_none():
        return False

    referral = Referral(
        referrer_id=referrer.id,
        referred_id=new_user.id,
    )
    session.add(referral)
    await session.flush()

    # Give the referrer their SC bonus
    from services import coins as coins_service  # lazy import

    await coins_service.add_sc(
        session,
        referrer,
        50,
        description=f"реферальный бонус за приглашение пользователя {new_user.id}",
    )
    await session.commit()
    return True


async def count_active_friends(session: AsyncSession, user_id: int) -> int:
    """
    Count how many users referred by user_id currently hold an active subscription.
    """
    result = await session.execute(
        select(Referral).where(Referral.referrer_id == user_id)
    )
    referrals = list(result.scalars().all())

    if not referrals:
        return 0

    referred_ids = [r.referred_id for r in referrals]

    active_result = await session.execute(
        select(User).where(
            User.id.in_(referred_ids),
            User.is_subscribed.is_(True),
        )
    )
    return len(list(active_result.scalars().all()))


async def check_ambassador(session: AsyncSession, user: User) -> bool:
    """
    Check if the user qualifies for Ambassador status
    (AMBASSADOR_FRIENDS_REQUIRED or more active paid referrals).

    If qualified, store the flag in AdminSetting "ambassador_{user_id}": "1".
    Returns True if the user is (or just became) an Ambassador.
    """
    active_count = await count_active_friends(session, user.id)
    if active_count < config.AMBASSADOR_FRIENDS_REQUIRED:
        return False

    key = f"ambassador_{user.id}"
    existing = await session.execute(
        select(AdminSetting).where(AdminSetting.key == key)
    )
    setting = existing.scalar_one_or_none()
    if setting is None:
        setting = AdminSetting(key=key, value="1")
        session.add(setting)
        await session.commit()
    return True


def generate_referral_link(user: User, bot_username: str) -> str:
    """Return the deep-link URL for the user's referral code."""
    return f"https://t.me/{bot_username}?start=ref{user.referral_code}"
