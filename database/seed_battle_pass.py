"""
Seed script: populate battle_pass_levels table with 50-level reward track.

Run standalone:
    python3 -m database.seed_battle_pass

Or call seed_battle_pass(session) inside an existing async context.

Idempotent: uses INSERT OR REPLACE (SQLite) / upsert on conflict.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.engine import AsyncSessionLocal, init_db
from database.models import BattlePassLevel

# ---------------------------------------------------------------------------
# Reward data  (level, xp_required, reward_type, reward_amount, reward_description)
# ---------------------------------------------------------------------------
# Design rationale:
#   - xp_required = level * 500  (cumulative; active user earns ~110 XP/day)
#   - SC total: exactly 1 500 SC across 40 SC-levels  (≈ 5 subscription discounts)
#   - Tickets: 4 штуки  на уровнях 15, 25, 35, 50  (milestone "lottery pass")
#   - Guides:  6 штук   на уровнях 5, 12, 20, 30, 40, 48 (culinary PDF every ~30-40 дней)
#   - SC curve: flat 15→25 SC early (engagement hook), steady ramp to 60 SC late
#
# Tempo:
#   Level 10  ≈ 45 дней   Level 25 ≈ 114 дней
#   Level 35  ≈ 159 дней  Level 50 ≈ 227 дней

BATTLE_PASS_REWARDS: list[dict] = [
    # ── Ранний трек (1–10): частые малые SC, первый гайд на 5-м ──────────
    {"level": 1,  "xp_required": 500,  "reward_type": "sc",     "reward_amount": 15, "reward_description": "15 SC — Добро пожаловать в Синдикат!"},
    {"level": 2,  "xp_required": 1000, "reward_type": "sc",     "reward_amount": 15, "reward_description": "15 SC — Первые шаги сделаны, продолжай!"},
    {"level": 3,  "xp_required": 1500, "reward_type": "sc",     "reward_amount": 15, "reward_description": "15 SC — Завтраки уже в привычке!"},
    {"level": 4,  "xp_required": 2000, "reward_type": "sc",     "reward_amount": 15, "reward_description": "15 SC — Синдикат замечает твой прогресс"},
    {"level": 5,  "xp_required": 2500, "reward_type": "guide",  "reward_amount": 0,  "reward_description": "Гайд «Идеальный завтрак за 10 минут» — твой первый кулинарный секрет"},
    {"level": 6,  "xp_required": 3000, "reward_type": "sc",     "reward_amount": 20, "reward_description": "20 SC — Первый этап позади!"},
    {"level": 7,  "xp_required": 3500, "reward_type": "sc",     "reward_amount": 20, "reward_description": "20 SC — Неделя в строю Синдиката"},
    {"level": 8,  "xp_required": 4000, "reward_type": "sc",     "reward_amount": 20, "reward_description": "20 SC — Ты опытнее половины новичков"},
    {"level": 9,  "xp_required": 4500, "reward_type": "sc",     "reward_amount": 20, "reward_description": "20 SC — До milestone один шаг!"},
    {"level": 10, "xp_required": 5000, "reward_type": "sc",     "reward_amount": 25, "reward_description": "25 SC — Уровень 10: ты в Синдикате всерьёз! 🎖"},

    # ── Средний трек (11–25): рост SC, второй гайд, первый билет ─────────
    {"level": 11, "xp_required": 5500,  "reward_type": "sc",     "reward_amount": 20, "reward_description": "20 SC — Вперёд, до следующего рубежа!"},
    {"level": 12, "xp_required": 6000,  "reward_type": "guide",  "reward_amount": 0,  "reward_description": "Гайд «Яйца 12 способами» — техники, которые изменят твой завтрак"},
    {"level": 13, "xp_required": 6500,  "reward_type": "sc",     "reward_amount": 25, "reward_description": "25 SC — Мастерство растёт вместе с уровнем"},
    {"level": 14, "xp_required": 7000,  "reward_type": "sc",     "reward_amount": 30, "reward_description": "30 SC — Синдикат ценит твою настойчивость"},
    {"level": 15, "xp_required": 7500,  "reward_type": "ticket", "reward_amount": 1,  "reward_description": "🎟 Лотерейный билет — твой первый шанс на приз Синдиката!"},
    {"level": 16, "xp_required": 8000,  "reward_type": "sc",     "reward_amount": 30, "reward_description": "30 SC — Удача любит настойчивых"},
    {"level": 17, "xp_required": 8500,  "reward_type": "sc",     "reward_amount": 30, "reward_description": "30 SC — Полпути до следующего milestone!"},
    {"level": 18, "xp_required": 9000,  "reward_type": "sc",     "reward_amount": 30, "reward_description": "30 SC — Завтраки стали твоей суперсилой"},
    {"level": 19, "xp_required": 9500,  "reward_type": "sc",     "reward_amount": 30, "reward_description": "30 SC — Почти у цели второго этапа!"},
    {"level": 20, "xp_required": 10000, "reward_type": "guide",  "reward_amount": 0,  "reward_description": "Гайд «Суперфуды: мифы и правда» — наука на твоей кухне"},
    {"level": 21, "xp_required": 10500, "reward_type": "sc",     "reward_amount": 35, "reward_description": "35 SC — Второй этап позади, Синдикат гордится тобой!"},
    {"level": 22, "xp_required": 11000, "reward_type": "sc",     "reward_amount": 35, "reward_description": "35 SC — Твой рейтинг в топе!"},
    {"level": 23, "xp_required": 11500, "reward_type": "sc",     "reward_amount": 35, "reward_description": "35 SC — Три четверти пути до следующего milestone"},
    {"level": 24, "xp_required": 12000, "reward_type": "sc",     "reward_amount": 35, "reward_description": "35 SC — Синдикат знает твоё имя"},
    {"level": 25, "xp_required": 12500, "reward_type": "ticket", "reward_amount": 1,  "reward_description": "🎟 Лотерейный билет — полпути пройдено, удача с тобой!"},

    # ── Поздний трек (26–40): уверенный рост, третий гайд ────────────────
    {"level": 26, "xp_required": 13000, "reward_type": "sc",     "reward_amount": 40, "reward_description": "40 SC — За экватором — только лучшее!"},
    {"level": 27, "xp_required": 13500, "reward_type": "sc",     "reward_amount": 40, "reward_description": "40 SC — Ты в элите Синдиката"},
    {"level": 28, "xp_required": 14000, "reward_type": "sc",     "reward_amount": 40, "reward_description": "40 SC — Ритм завтраков стал твоей нормой"},
    {"level": 29, "xp_required": 14500, "reward_type": "sc",     "reward_amount": 40, "reward_description": "40 SC — До следующей вехи совсем близко!"},
    {"level": 30, "xp_required": 15000, "reward_type": "guide",  "reward_amount": 0,  "reward_description": "Гайд «Meal Prep: готовим на неделю» — профессиональный подход"},
    {"level": 31, "xp_required": 15500, "reward_type": "sc",     "reward_amount": 45, "reward_description": "45 SC — Тридцатый уровень — это серьёзно!"},
    {"level": 32, "xp_required": 16000, "reward_type": "sc",     "reward_amount": 45, "reward_description": "45 SC — Синдикат в восторге от твоего прогресса"},
    {"level": 33, "xp_required": 16500, "reward_type": "sc",     "reward_amount": 45, "reward_description": "45 SC — Твои фото вдохновляют других участников"},
    {"level": 34, "xp_required": 17000, "reward_type": "sc",     "reward_amount": 45, "reward_description": "45 SC — Финишная прямая приближается"},
    {"level": 35, "xp_required": 17500, "reward_type": "ticket", "reward_amount": 1,  "reward_description": "🎟 Лотерейный билет — ещё один шанс стать победителем!"},
    {"level": 36, "xp_required": 18000, "reward_type": "sc",     "reward_amount": 50, "reward_description": "50 SC — Ты прошёл 70% пути — это впечатляет!"},
    {"level": 37, "xp_required": 18500, "reward_type": "sc",     "reward_amount": 50, "reward_description": "50 SC — Синдикат выдаёт серьёзные награды"},
    {"level": 38, "xp_required": 19000, "reward_type": "sc",     "reward_amount": 50, "reward_description": "50 SC — Финал уже виден на горизонте"},
    {"level": 39, "xp_required": 19500, "reward_type": "sc",     "reward_amount": 50, "reward_description": "50 SC — Последний рывок начинается!"},
    {"level": 40, "xp_required": 20000, "reward_type": "guide",  "reward_amount": 0,  "reward_description": "Гайд «Завтраки мира: от Токио до Стамбула» — глобальная кухня"},

    # ── Финальный трек (41–50): крупный SC, финальный гайд, эпик-билет ──
    {"level": 41, "xp_required": 20500, "reward_type": "sc",     "reward_amount": 55, "reward_description": "55 SC — Сорок уровней — ты легенда!"},
    {"level": 42, "xp_required": 21000, "reward_type": "sc",     "reward_amount": 55, "reward_description": "55 SC — Синдикат чеканит медали для тебя"},
    {"level": 43, "xp_required": 21500, "reward_type": "sc",     "reward_amount": 55, "reward_description": "55 SC — Каждый завтрак теперь — произведение искусства"},
    {"level": 44, "xp_required": 22000, "reward_type": "sc",     "reward_amount": 55, "reward_description": "55 SC — До финала пять шагов!"},
    {"level": 45, "xp_required": 22500, "reward_type": "sc",     "reward_amount": 60, "reward_description": "60 SC — Ты в топ-5% Синдиката"},
    {"level": 46, "xp_required": 23000, "reward_type": "sc",     "reward_amount": 60, "reward_description": "60 SC — Синдикат преклоняется перед твоей выдержкой"},
    {"level": 47, "xp_required": 23500, "reward_type": "sc",     "reward_amount": 60, "reward_description": "60 SC — Предпоследний рывок!"},
    {"level": 48, "xp_required": 24000, "reward_type": "guide",  "reward_amount": 0,  "reward_description": "Гайд «Фотография еды: снимаем как профи» — финальный секрет Синдиката"},
    {"level": 49, "xp_required": 24500, "reward_type": "sc",     "reward_amount": 60, "reward_description": "60 SC — Один шаг до вершины!"},
    {"level": 50, "xp_required": 25000, "reward_type": "ticket", "reward_amount": 1,  "reward_description": "🎟 Лотерейный билет — ты достиг вершины Синдиката. Легенда!"},
]


async def seed_battle_pass(session: AsyncSession) -> int:
    """
    Upsert all 50 BattlePassLevel rows.
    Returns the number of rows inserted/updated.
    """
    stmt = sqlite_insert(BattlePassLevel)
    stmt = stmt.on_conflict_do_update(
        index_elements=["level"],
        set_={
            "xp_required": stmt.excluded.xp_required,
            "reward_type": stmt.excluded.reward_type,
            "reward_amount": stmt.excluded.reward_amount,
            "reward_description": stmt.excluded.reward_description,
        },
    )
    await session.execute(stmt, BATTLE_PASS_REWARDS)
    await session.commit()
    return len(BATTLE_PASS_REWARDS)


async def _main() -> None:
    await init_db()
    async with AsyncSessionLocal() as session:
        count = await seed_battle_pass(session)
    print(f"✅ Seeded {count} Battle Pass levels.")

    # Print summary
    total_sc = sum(r["reward_amount"] for r in BATTLE_PASS_REWARDS if r["reward_type"] == "sc")
    tickets = sum(1 for r in BATTLE_PASS_REWARDS if r["reward_type"] == "ticket")
    guides = sum(1 for r in BATTLE_PASS_REWARDS if r["reward_type"] == "guide")
    print(f"   SC total:  {total_sc}")
    print(f"   Tickets:   {tickets}  (levels 15, 25, 35, 50)")
    print(f"   Guides:    {guides}   (levels 5, 12, 20, 30, 40, 48)")


if __name__ == "__main__":
    asyncio.run(_main())
