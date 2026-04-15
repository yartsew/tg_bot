import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN
from database.engine import init_db
from middlewares.db import DbMiddleware
from middlewares.auth import AuthMiddleware
from middlewares.throttling import ThrottlingMiddleware

# Import all routers
from handlers import start, subscription, profile, quests, battle_pass, lottery, referral, social, admin as admin_handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


async def main() -> None:
    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Middlewares (order matters: throttling first, then db, then auth)
    dp.message.middleware(ThrottlingMiddleware(rate_limit=0.5))
    dp.message.middleware(DbMiddleware())
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(DbMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    # Routers
    dp.include_router(start.router)
    dp.include_router(subscription.router)
    dp.include_router(profile.router)
    dp.include_router(quests.router)
    dp.include_router(battle_pass.router)
    dp.include_router(lottery.router)
    dp.include_router(referral.router)
    dp.include_router(social.router)
    dp.include_router(admin_handler.router)

    # Scheduler
    from scheduler.tasks import setup_scheduler
    scheduler = AsyncIOScheduler()
    setup_scheduler(scheduler, bot)
    scheduler.start()

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
