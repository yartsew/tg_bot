# Кулинарный Синдикат — Telegram Bot

## Stack
- aiogram 3.13.1 (async Telegram bot framework)
- SQLAlchemy 2.x async + aiosqlite (SQLite in dev)
- APScheduler (cron tasks)
- Pillow + piexif (image processing)

## Project Structure
```
tg_bot/
├── bot.py                  # Entry point: Bot, Dispatcher, routers, scheduler
├── config.py               # All settings (env vars + constants)
├── database/
│   ├── engine.py           # create_async_engine, AsyncSessionLocal, init_db()
│   └── models.py           # All SQLAlchemy ORM models
├── handlers/               # One file per feature domain
│   ├── start.py            # /start, registration, referral code intake
│   ├── subscription.py     # /subscribe, payment flow, SC partial payment
│   ├── profile.py          # /profile, branch choice (lvl10), mentor code (lvl50)
│   ├── quests.py           # /quest, breakfast photo upload, EXIF validation, P2P review, quiz
│   ├── battle_pass.py      # /battlepass, progress view, claim rewards
│   ├── lottery.py          # /lottery, ticket list, drawing results
│   ├── referral.py         # /referral, deep link, ambassador status
│   ├── social.py           # Faction selection, community events
│   └── admin.py            # /admin panel (restricted to ADMIN_IDS)
├── services/               # Pure business logic, no Telegram objects
│   ├── subscription.py     # renew_subscription, retry logic, prize fund calc
│   ├── coins.py            # add_sc, deduct_sc, burn_expired
│   ├── quests.py           # submit_photo, validate_exif, assign_p2p, vote_p2p
│   ├── battle_pass.py      # add_xp, level_up check, claimable_rewards
│   ├── lottery.py          # issue_ticket, run_drawing, public_report
│   ├── referral.py         # process_referral, count_active_friends, ambassador_check
│   ├── notifications.py    # send_push (bot.send_message wrappers)
│   └── avatar.py           # overlay PNG frame on user avatar (Pillow)
├── middlewares/
│   ├── db.py               # Inject AsyncSession into handler data dict
│   ├── auth.py             # Check subscription, inject user object
│   └── throttling.py       # Anti-flood (0.5s rate limit)
├── keyboards/
│   ├── main.py             # Main menu reply keyboard
│   ├── subscription.py     # Subscription inline keyboards
│   ├── profile.py          # Profile keyboards (branch choice, mentor)
│   ├── quests.py           # Quest keyboards (submit, quiz options, P2P vote)
│   └── admin.py            # Admin panel keyboards
├── states/
│   └── forms.py            # All FSM StatesGroup definitions
└── scheduler/
    └── tasks.py            # APScheduler jobs: renewal retries, SC burn, lottery drawing
```

## Key Conventions
- Handlers: thin — call service, send response. NO business logic.
- Services: receive AsyncSession as first arg. Return domain objects/values.
- DB session: injected by DbMiddleware into handler data as `session`.
- Current user: injected by AuthMiddleware into handler data as `user` (User ORM object or None for /start).
- Config constants imported from `config.py`.
- All database operations use `await session.execute(select(...))` pattern.

## Database Models (import from `database.models`)
- User — telegram_id, level, xp, sc_balance, trust_rating, branch, is_subscribed, referral_code, mentor_id
- Subscription — user_id, end_date, status, renewal_attempts, price_paid, sc_paid
- SCTransaction — user_id, amount (+/-), description
- DailyPhoto — user_id, photo_file_id, photo_taken_at (EXIF), status, p2p_approve_count
- P2PReview — photo_id, reviewer_id, is_approved
- QuizQuestion — question, options (list via .options property), correct_index, scheduled_date
- UserQuizAttempt — user_id, question_id, date, is_correct, sc_spent, attempts
- BattlePassLevel — level (PK), xp_required, reward_type, reward_amount
- UserReward — user_id, level, claimed, claimed_at
- LotteryTicket — user_id, ticket_number (UUID), lottery_month (YYYY-MM)
- AdminSetting — key (PK), value (str, cast at use site)
- ControlPhoto — photo_file_id, is_fake, added_by_admin
- Referral — referrer_id, referred_id (unique)
- Faction / UserFaction — faction choice per user

## Key Business Rules (from PRD)
- Subscription: 30-day cycle, 3 renewal retries over 3 days, then block
- SC partial payment: max 50% of subscription price
- SC burn: if not subscribed >168h → balance = 0; warn at 144h
- Photo EXIF: reject if photo_taken_at older than 24h from upload
- P2P: 5 random reviewers per photo, 3 approvals = quest done
- Battle Pass: levels 1-50, then infinite (gold, +reward every 1000 XP)
- Branch choice: forced modal at level 10
- Mentor code: available at level 50+
- Ambassador: 10 active paid friends → next subscription free
- Faction trigger: broadcast + faction selection at 300 users
- Control photos (anti-fraud): admin uploads fake image, if user approves it → -100 XP, trust_rating drops
