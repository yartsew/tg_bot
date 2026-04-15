import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from database.engine import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def _retry_subscriptions(bot: Bot) -> None:
    """Retry failed subscription payments (runs every 6h)."""
    from services.subscription import retry_failed_subscriptions, check_and_expire_subscriptions
    async with AsyncSessionLocal() as session:
        await check_and_expire_subscriptions(session)
        await retry_failed_subscriptions(session, bot)


async def _burn_expired_coins(bot: Bot) -> None:
    """Burn SC for long-unsubscribed users and send 24h warnings (runs every hour)."""
    from services.coins import burn_expired_coins, get_users_to_warn_burn
    from services.notifications import notify_sc_burn_warning
    async with AsyncSessionLocal() as session:
        # Send warnings first
        users_to_warn = await get_users_to_warn_burn(session)
        for user in users_to_warn:
            await notify_sc_burn_warning(bot, user)
        # Then burn
        burned = await burn_expired_coins(session, bot)
        if burned:
            logger.info("Burned SC for %d users", burned)


async def _monthly_lottery(bot: Bot) -> None:
    """Run monthly lottery drawing on the last day of each month at 20:00."""
    from services.lottery import run_monthly_drawing
    from database.models import AdminSetting
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AdminSetting).where(AdminSetting.key == "lottery_channel")
        )
        setting = result.scalar_one_or_none()
        channel_id = setting.value if setting else None

        if not channel_id:
            logger.warning("lottery_channel not configured, skipping drawing")
            return

        winners = await run_monthly_drawing(session, bot, channel_id)
        logger.info("Lottery drawing done: %d winners", len(winners))


async def _check_faction_trigger(bot: Bot) -> None:
    """Broadcast faction selection when user count hits 300."""
    from database.models import User, AdminSetting
    from sqlalchemy import select, func

    async with AsyncSessionLocal() as session:
        # Check if trigger already fired
        result = await session.execute(
            select(AdminSetting).where(AdminSetting.key == "faction_trigger_fired")
        )
        fired = result.scalar_one_or_none()
        if fired:
            return

        count_result = await session.execute(select(func.count(User.id)))
        total = count_result.scalar()

        from config import FACTION_TRIGGER_USERS
        if total >= FACTION_TRIGGER_USERS:
            # Mark as fired
            session.add(AdminSetting(key="faction_trigger_fired", value="1"))
            await session.commit()

            # Broadcast to all subscribed users
            users_result = await session.execute(
                select(User).where(User.is_subscribed == True)
            )
            users = users_result.scalars().all()
            text = (
                "🎉 <b>Синдикат растёт!</b>\n\n"
                "Нас уже 300! Пора определиться с фракцией.\n"
                "Заходи в профиль и выбери свой путь!"
            )
            sent = 0
            for user in users:
                try:
                    await bot.send_message(user.telegram_id, text)
                    sent += 1
                except Exception:
                    pass
            logger.info("Faction trigger broadcast sent to %d users", sent)


def setup_scheduler(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    """Register all periodic jobs."""
    # Retry failed payments every 6 hours
    scheduler.add_job(
        _retry_subscriptions,
        trigger="interval",
        hours=6,
        args=[bot],
        id="retry_subscriptions",
        replace_existing=True,
    )

    # SC burn check every hour
    scheduler.add_job(
        _burn_expired_coins,
        trigger="interval",
        hours=1,
        args=[bot],
        id="burn_coins",
        replace_existing=True,
    )

    # Monthly lottery: last day of month at 20:00
    scheduler.add_job(
        _monthly_lottery,
        trigger="cron",
        day="last",
        hour=20,
        minute=0,
        args=[bot],
        id="monthly_lottery",
        replace_existing=True,
    )

    # Faction trigger check every hour
    scheduler.add_job(
        _check_faction_trigger,
        trigger="interval",
        hours=1,
        args=[bot],
        id="faction_trigger",
        replace_existing=True,
    )

    logger.info("Scheduler configured: 4 jobs registered")
