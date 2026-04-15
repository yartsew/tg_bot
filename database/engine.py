from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    from database.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed Battle Pass levels if table is empty
    from database.seed_battle_pass import seed_battle_pass
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select, func
        from database.models import BattlePassLevel
        result = await session.execute(select(func.count()).select_from(BattlePassLevel))
        count = result.scalar()
        if count == 0:
            await seed_battle_pass(session)
