"""
Battle Pass progression — Кулинарный Синдикат.
Handles XP accumulation, level-up detection, and reward claiming.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from database.models import BattlePassLevel, LotteryTicket, User, UserReward


# ---------------------------------------------------------------------------
# Level thresholds
# ---------------------------------------------------------------------------


async def get_level_thresholds(session: AsyncSession) -> dict[int, int]:
    """
    Return {level: cumulative_xp_required} from BattlePassLevel table.
    Falls back to a generated table using BP_XP_PER_LEVEL (level * 500 each level).
    """
    result = await session.execute(
        select(BattlePassLevel).order_by(BattlePassLevel.level)
    )
    rows = list(result.scalars().all())

    if rows:
        return {row.level: row.xp_required for row in rows}

    # Default: each level costs BP_XP_PER_LEVEL cumulative XP
    return {lvl: lvl * config.BP_XP_PER_LEVEL for lvl in range(1, 51)}


# ---------------------------------------------------------------------------
# XP & level-up
# ---------------------------------------------------------------------------


async def add_xp(
    session: AsyncSession,
    user: User,
    xp_amount: int,
    description: str = "",
) -> dict:
    """
    Add XP to the user and check for level-ups.

    Level 1–50: compare cumulative user.xp against BattlePassLevel.xp_required.
    After level 50: reward every BP_INFINITE_BONUS_XP XP beyond the level-50 threshold.

    On level-up: creates UserReward record (unclaimed=False).

    Returns:
        {
            "leveled_up": bool,
            "new_level": int,
            "rewards_unlocked": list[int],   # list of level numbers
        }
    """
    user.xp = (user.xp or 0) + xp_amount

    thresholds = await get_level_thresholds(session)
    max_bp_level = max(thresholds.keys(), default=50)

    old_level = user.level or 1
    new_level = old_level
    rewards_unlocked: list[int] = []

    # Levels 1–50
    for lvl in range(old_level + 1, max_bp_level + 1):
        required = thresholds.get(lvl, lvl * config.BP_XP_PER_LEVEL)
        if user.xp >= required:
            new_level = lvl
        else:
            break

    # After level 50: infinite rewards every BP_INFINITE_BONUS_XP XP
    if user.xp >= thresholds.get(max_bp_level, max_bp_level * config.BP_XP_PER_LEVEL):
        base_xp = thresholds.get(max_bp_level, max_bp_level * config.BP_XP_PER_LEVEL)
        extra_xp = user.xp - base_xp
        infinite_rewards_earned = extra_xp // config.BP_INFINITE_BONUS_XP
        # Encode infinite reward levels as 50 + n
        for n in range(1, infinite_rewards_earned + 1):
            synthetic_level = max_bp_level + n
            exists = await session.execute(
                select(UserReward).where(
                    UserReward.user_id == user.id,
                    UserReward.level == synthetic_level,
                )
            )
            if not exists.scalar_one_or_none():
                reward = UserReward(
                    user_id=user.id,
                    level=synthetic_level,
                    claimed=False,
                )
                session.add(reward)
                rewards_unlocked.append(synthetic_level)

    # Create reward records for newly reached BP levels
    if new_level > old_level:
        for lvl in range(old_level + 1, new_level + 1):
            exists = await session.execute(
                select(UserReward).where(
                    UserReward.user_id == user.id,
                    UserReward.level == lvl,
                )
            )
            if not exists.scalar_one_or_none():
                reward = UserReward(
                    user_id=user.id,
                    level=lvl,
                    claimed=False,
                )
                session.add(reward)
                rewards_unlocked.append(lvl)

        user.level = new_level

    await session.commit()

    return {
        "leveled_up": new_level > old_level,
        "new_level": user.level,
        "rewards_unlocked": rewards_unlocked,
    }


# ---------------------------------------------------------------------------
# Rewards
# ---------------------------------------------------------------------------


async def get_claimable_rewards(
    session: AsyncSession,
    user_id: int,
) -> list[UserReward]:
    """Return all unclaimed UserReward records for the user."""
    result = await session.execute(
        select(UserReward).where(
            UserReward.user_id == user_id,
            UserReward.claimed.is_(False),
        )
    )
    return list(result.scalars().all())


async def claim_reward(
    session: AsyncSession,
    user: User,
    level: int,
) -> dict:
    """
    Mark a UserReward as claimed and deliver the reward (SC or lottery ticket).
    Returns dict with keys: success, reason, reward_type, reward_amount, reward_description.
    """
    reward_result = await session.execute(
        select(UserReward).where(
            UserReward.user_id == user.id,
            UserReward.level == level,
            UserReward.claimed.is_(False),
        )
    )
    user_reward = reward_result.scalar_one_or_none()
    if user_reward is None:
        return {"success": False, "reason": "Награда не найдена или уже получена."}

    # Load BattlePassLevel definition (may not exist for infinite levels)
    bp_result = await session.execute(
        select(BattlePassLevel).where(BattlePassLevel.level == level)
    )
    bp_level = bp_result.scalar_one_or_none()

    user_reward.claimed = True
    user_reward.claimed_at = datetime.utcnow()

    if bp_level is None:
        # Infinite-tier reward: issue a lottery ticket
        import uuid

        ticket = LotteryTicket(
            user_id=user.id,
            ticket_number=str(uuid.uuid4()),
            lottery_month=datetime.utcnow().strftime("%Y-%m"),
        )
        session.add(ticket)
        await session.commit()
        return {
            "success": True,
            "reward_type": "ticket",
            "reward_amount": 1,
            "reward_description": "Лотерейный билет за бесконечный режим",
        }

    if bp_level.reward_type == "sc":
        from services import coins as coins_service  # lazy import

        await coins_service.add_sc(
            session,
            user,
            bp_level.reward_amount,
            description=f"награда за уровень {level}",
        )
        await session.commit()
        return {
            "success": True,
            "reward_type": "sc",
            "reward_amount": bp_level.reward_amount,
            "reward_description": bp_level.reward_description,
        }

    if bp_level.reward_type == "ticket":
        import uuid

        ticket = LotteryTicket(
            user_id=user.id,
            ticket_number=str(uuid.uuid4()),
            lottery_month=datetime.utcnow().strftime("%Y-%m"),
        )
        session.add(ticket)
        await session.commit()
        return {
            "success": True,
            "reward_type": "ticket",
            "reward_amount": 1,
            "reward_description": bp_level.reward_description,
        }

    if bp_level.reward_type == "guide":
        await session.commit()
        return {
            "success": True,
            "reward_type": "guide",
            "reward_amount": 0,
            "reward_description": bp_level.reward_description,
        }

    await session.commit()
    return {
        "success": True,
        "reward_type": "",
        "reward_amount": 0,
        "reward_description": f"Награда за уровень {level}",
    }


# ---------------------------------------------------------------------------
# Progress summary
# ---------------------------------------------------------------------------


async def get_progress_summary(session: AsyncSession, user: User) -> dict:
    """
    Return a progress snapshot for display.

    {
        "level": int,
        "xp": int,
        "xp_for_next": int | None,   # None after level 50 (infinite)
        "percent": float,            # 0.0–100.0
        "claimable_count": int,
    }
    """
    thresholds = await get_level_thresholds(session)
    current_level = user.level or 1
    current_xp = user.xp or 0
    max_level = max(thresholds.keys(), default=50)

    if current_level >= max_level:
        base_xp = thresholds.get(max_level, max_level * config.BP_XP_PER_LEVEL)
        extra = current_xp - base_xp
        next_bonus_xp = config.BP_INFINITE_BONUS_XP - (extra % config.BP_INFINITE_BONUS_XP)
        percent = ((extra % config.BP_INFINITE_BONUS_XP) / config.BP_INFINITE_BONUS_XP) * 100
        xp_for_next: int | None = next_bonus_xp
    else:
        current_level_xp = thresholds.get(current_level, current_level * config.BP_XP_PER_LEVEL)
        next_level_xp = thresholds.get(current_level + 1, (current_level + 1) * config.BP_XP_PER_LEVEL)
        xp_in_level = current_xp - current_level_xp
        xp_needed = next_level_xp - current_level_xp
        percent = (xp_in_level / xp_needed * 100) if xp_needed > 0 else 100.0
        xp_for_next = next_level_xp - current_xp

    # JOIN UserReward with BattlePassLevel to get reward type for each claimable reward
    from sqlalchemy import outerjoin as sa_outerjoin
    claimable_result = await session.execute(
        select(UserReward, BattlePassLevel)
        .outerjoin(BattlePassLevel, UserReward.level == BattlePassLevel.level)
        .where(
            UserReward.user_id == user.id,
            UserReward.claimed.is_(False),
        )
        .order_by(UserReward.level)
    )
    claimable_rows = claimable_result.all()

    claimable_levels = [row[0].level for row in claimable_rows]
    claimable_rewards = [
        {
            "level": row[0].level,
            "reward_type": row[1].reward_type if row[1] else "ticket",   # infinite → ticket
            "reward_amount": row[1].reward_amount if row[1] else 1,
            "reward_description": row[1].reward_description if row[1] else "Лотерейный билет",
        }
        for row in claimable_rows
    ]

    return {
        # canonical keys (used internally)
        "level": current_level,
        "xp": current_xp,
        "xp_for_next": xp_for_next,
        "percent": round(percent, 1),
        "claimable_count": len(claimable_rows),
        # aliases expected by handlers/battle_pass.py
        "current_level": current_level,
        "xp_to_next_level": xp_for_next if xp_for_next is not None else 0,
        "level_progress_pct": round(percent, 1),
        "claimable_levels": claimable_levels,
        "claimable_rewards": claimable_rewards,  # enriched: [{level, reward_type, reward_amount, reward_description}]
    }
