import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./syndicate.db")

# Admins
ADMIN_IDS: set[int] = set(
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
)

# Subscription defaults (overridable via AdminSetting in DB)
DEFAULT_SUBSCRIPTION_PRICE: float = float(os.getenv("SUBSCRIPTION_PRICE", "299.0"))
DEFAULT_PRIZE_FUND_PERCENT: float = float(os.getenv("PRIZE_FUND_PERCENT", "0.30"))

# Payment provider token (Telegram Payments)
PAYMENT_PROVIDER_TOKEN: str = os.getenv("PAYMENT_PROVIDER_TOKEN", "")

# XP per activity
XP_BREAKFAST_PHOTO: int = 50
XP_QUIZ_CORRECT: int = 30
XP_P2P_REVIEW: int = 10

# SC
SC_QUIZ_RETRY_COST: int = 10
SC_BURN_AFTER_HOURS: int = 168  # 7 days
SC_BURN_WARN_HOURS: int = 144   # 6 days (24h before burn)

# Battle Pass
BP_XP_PER_LEVEL: int = 500          # base XP per level (1-50)
BP_INFINITE_BONUS_XP: int = 1000    # XP per reward after level 50

# P2P
P2P_REVIEWERS_PER_PHOTO: int = 5
P2P_APPROVALS_NEEDED: int = 3           # photos with EXIF
P2P_APPROVALS_NEEDED_NO_EXIF: int = 4   # photos without EXIF (stricter, anti-fraud)

# Referral
AMBASSADOR_FRIENDS_REQUIRED: int = 10

# Faction trigger
FACTION_TRIGGER_USERS: int = 300
