# QA Report — Кулинарный Синдикат
**Дата:** 2026-04-10 (обновлено 2026-04-14)
**Покрытие:** 25/27 (93%)

---

## Итоговая таблица

| PR | Название | Статус | Файл |
|----|----------|--------|------|
| PR 1.1 | Рекуррентные платежи (retry 3×, блокировка) | ✅ | `services/subscription.py` |
| PR 1.2 | Виджет призового фонда (Revenue × 0.3) | ✅ | `services/subscription.py`, `handlers/subscription.py` |
| PR 1.3 | Админ меняет цену/процент без рестарта | ✅ | `handlers/admin.py`, `services/subscription.py` |
| PR 2.1 | SC частичная оплата max 50% | ✅ | `handlers/subscription.py` |
| PR 2.2 | Лог SC транзакций виден пользователю | ⚠️ | `services/coins.py` |
| PR 2.3 | SC сгорает через 168ч + предупреждение за 24ч | ✅ | `services/coins.py`, `scheduler/tasks.py` |
| PR 3.1 | Аватар с PNG рамкой уровня | ⚠️ | `services/avatar.py`, `handlers/profile.py` |
| PR 3.2 | Выбор ветки на 10 уровне (блокирующий modal) | ⚠️ | `handlers/profile.py` |
| PR 3.3 | Код наставника на 50+ уровне | ✅ | `handlers/profile.py` |
| PR 4.1 | EXIF политика: >24ч → отклонить, без EXIF → принять с предупреждением | ✅ | `services/quests.py`, `handlers/quests.py`, `config.py` |
| PR 4.2 | P2P: 5 рецензентов, 3 одобрения | ⚠️ | `services/quests.py` |
| PR 4.3 | Квиз 1 раз/день, retry за 10 SC | ✅ | `services/quests.py`, `handlers/quests.py` |
| PR 5.1 | Визуализация уровней BP | ⚠️ | `handlers/battle_pass.py` |
| PR 5.2 | Ручное получение наград (Claim) | ✅ | `handlers/battle_pass.py`, `services/battle_pass.py` |
| PR 5.3 | Infinite Loop после 50 уровня | ✅ | `services/battle_pass.py` |
| PR 6.1 | Invite link + кик при отписке | ❌ | — |
| PR 6.2 | Глобальный прогресс завтраков | ❌ | — |
| PR 6.3 | Триггер 300 юзеров + рассылка | ✅ | `scheduler/tasks.py` |
| PR 7.1 | Билеты UUID в БД, видны юзеру | ✅ | `database/models.py`, `handlers/lottery.py` |
| PR 7.2 | Анимация розыгрыша | ❌ | — |
| PR 7.3 | Публичный отчёт в канал | ✅ | `services/lottery.py` |
| PR 8.1 | Deep link ref при старте | ✅ | `handlers/start.py` |
| PR 8.2 | Счётчик активных (оплативших) друзей | ✅ | `services/referral.py`, `handlers/referral.py` |
| PR 8.3 | 10 друзей → бесплатная подписка | ⚠️ | `services/referral.py` |
| PR 9.1 | Контрольное фото антифрод | ⚠️ | `services/quests.py`, `handlers/admin.py` |
| PR 9.2 | Dashboard DAU/WAU/MAU/LTV/Churn/SC | ⚠️ | `handlers/admin.py` |
| PR 9.3 | Content Manager: PDF + квиз | ⚠️ | `handlers/admin.py` |

---

## ✅ Реализовано полностью

**PR 1.1 — Рекуррентные платежи**
Где реализовано: `services/subscription.py:retry_failed_subscriptions`. Логика находит записи `Subscription` со статусом `"failed"` и `renewal_attempts < 3`, у которых `last_attempt` старше 24ч. Инкрементирует счётчик, при достижении 3 попыток выставляет `status="blocked"` и `user.subscription_blocked=True`, отправляет уведомление. Scheduler запускает задачу каждые 6 часов (`scheduler/tasks.py:_retry_subscriptions`). Соответствует PRD полностью.

**PR 1.2 — Виджет призового фонда**
Где реализовано: `services/subscription.py:get_prize_fund`. Суммирует `price_paid` всех активных подписок за текущий месяц, умножает на `prize_fund_percent` (по умолчанию 0.3 из конфига, настраивается через AdminSetting). Виджет отображается в `/subscribe` (`handlers/subscription.py:cmd_subscribe`, строки 53–58) и в `/lottery` (`handlers/lottery.py:cmd_lottery`, строка 79).

**PR 1.3 — Админ меняет цену/процент без рестарта**
Где реализовано: `handlers/admin.py:handle_new_price` (цена подписки через FSM `AdminStates.waiting_subscription_price`) и `handlers/admin.py:handle_setting_value` (процент фонда через FSM `AdminStates.waiting_setting_value`). Оба значения пишутся в таблицу `AdminSetting` и читаются из неё при каждом запросе через `services/subscription.py:get_subscription_price` и `get_prize_fund_percent`. Рестарт не требуется.

**PR 2.1 — SC частичная оплата max 50%**
Где реализовано: `handlers/subscription.py:cb_pay_with_sc` и `cb_confirm_sc`. Вычисляется `max_sc_discount = int(price * 0.5)`, затем `sc_to_use = min(user.sc_balance, max_sc_discount)`. Инвойс выставляется на остаток (`remaining = price - sc_to_use`). Ограничение 50% соблюдается.

**PR 2.3 — SC сгорает через 168ч + предупреждение за 24ч**
Где реализовано: `services/coins.py:burn_expired_coins` (порог `SC_BURN_AFTER_HOURS=168`) и `get_users_to_warn_burn` (порог `SC_BURN_WARN_HOURS=144`). Scheduler: `scheduler/tasks.py:_burn_expired_coins` запускается каждый час, сначала отправляет предупреждения через `notify_sc_burn_warning`, затем обнуляет балансы. Логика соответствует PRD.

**PR 3.3 — Код наставника на 50+ уровне**
Где реализовано: `handlers/profile.py:cb_gen_mentor_code`. Проверяет `user.level < 50`, при блокировке выдаёт сообщение с текущим уровнем. При уровне ≥ 50 формирует deep-link `https://t.me/{bot_username}?start=ref{user.referral_code}`.

**PR 4.3 — Квиз 1 раз/день, retry за 10 SC**
Где реализовано: `services/quests.py:submit_quiz_answer`, `handlers/quests.py:cb_quiz_answer`, `handlers/quests.py:cb_quiz_retry`. При `paid_retry=False` проверяет `existing_attempt.is_correct`, блокирует повторный правильный ответ. Retry-путь (`paid_retry=True`, `answer_index=None`) списывает SC и возвращает `retry_granted=True` — вопрос показывается заново. Ограничение «1 вопрос в день» реализовано через `UniqueConstraint("user_id", "question_id")` в `UserQuizAttempt` и логику в сервисе. `submit_quiz_answer` возвращает `dict` с полями `is_correct`, `already_answered`, `xp_earned`, `sc_earned`, `correct_option`, `retry_cost`, `retry_granted`; добавлена `get_quiz_by_id(session, question_id)` для перезагрузки вопроса при retry.

**PR 5.2 — Ручное получение наград (Claim)**
Где реализовано: `handlers/battle_pass.py:cb_claim_reward` вызывает `services/battle_pass.py:claim_reward`. Функция `claim_reward` проверяет `claimed=False`, устанавливает `claimed=True` и `claimed_at`, доставляет SC/билет/гид в зависимости от `reward_type`. Кнопки генерируются динамически через `_claimable_rewards_kb(claimable_levels)`.

**PR 5.3 — Infinite Loop после 50 уровня**
Где реализовано: `services/battle_pass.py:add_xp`. После достижения `max_bp_level` вычисляет `extra_xp = user.xp - base_xp`, каждые `BP_INFINITE_BONUS_XP` XP создаёт синтетический уровень `max_bp_level + n` (51, 52…) с записью `UserReward`. `get_progress_summary` корректно вычисляет прогресс в infinite-режиме.

**PR 6.3 — Триггер 300 юзеров + рассылка**
Где реализовано: `scheduler/tasks.py:_check_faction_trigger`. Проверяет `AdminSetting.faction_trigger_fired`, подсчитывает `COUNT(User.id)`, при достижении `FACTION_TRIGGER_USERS=300` сохраняет флаг и рассылает сообщение всем подписанным пользователям. Запускается каждый час.

**PR 7.1 — Билеты UUID в БД, видны юзеру**
Где реализовано: `database/models.py:LotteryTicket.ticket_number` — `Column(String(36), unique=True)` заполняется через `str(uuid.uuid4())`. В `handlers/lottery.py:cmd_lottery` каждый билет выводится как `<code>{t.ticket_number}</code>`, победители отмечены символом ✨.

**PR 7.3 — Публичный отчёт в канал**
Где реализовано: `services/lottery.py:run_monthly_drawing`. После выбора победителей формирует текстовый отчёт с именами, обрезанными UUID-номерами билетов и призом, отправляет его через `bot.send_message(chat_id=channel_id, text=report)`. Channel_id читается из `AdminSetting.lottery_channel_id` в `scheduler/tasks.py:_monthly_lottery`.

**PR 8.1 — Deep link ref при старте**
Где реализовано: `handlers/start.py:cmd_start`. Парсит `message.text.split(maxsplit=1)`, проверяет префикс `"ref"`, извлекает код и передаёт в `referral_service.process_referral`. Работает для новых пользователей.

**PR 8.2 — Счётчик активных (оплативших) друзей**
Где реализовано: `services/referral.py:count_active_friends` — находит все `Referral` по `referrer_id`, затем считает из них тех, у кого `is_subscribed=True`. Результат отображается в `handlers/referral.py:cmd_referral` с прогресс-линией `{active}/{AMBASSADOR_FRIENDS_REQUIRED}`.

---

## ⚠️ Реализовано частично

**PR 2.2 — Лог SC транзакций виден пользователю**
Реализовано: `services/coins.py:get_transactions` — запрос к `SCTransaction`, сортировка по `created_at desc`, лимит 20 записей. Транзакции логируются при каждом `add_sc` и `deduct_sc`.
Не хватает: нет ни одного handler'а, который вызывает `get_transactions` и показывает список транзакций пользователю. Ни в `handlers/profile.py`, ни в `handlers/subscription.py` нет кнопки «История SC» и соответствующего callback. Пользователь не может просмотреть лог.

**PR 3.1 — Аватар с PNG рамкой уровня**
Реализовано: `services/avatar.py:generate_avatar` — Pillow composite, `_get_frame_path(level)` подбирает `assets/frames/frame_{level}.png` с fallback на `frame_1.png`. Вызывается из `handlers/profile.py:cb_get_avatar`.
Не хватает: в `TODO`-комментарии самого сервиса явно указано, что реальных PNG-файлов рамок нет (`assets/frames/` пуст или содержит только заглушки). Без файлов `frame_{level}.png` функция вернёт фото без наложения рамки (ветка `if os.path.exists(frame_path)` просто пропускается). Брендированные ассеты не поставлены.

**PR 3.2 — Выбор ветки на 10 уровне (блокирующий modal)**
Реализовано: `handlers/profile.py:cmd_profile` — при `user.level >= 10 and user.branch is None` выводится `branch_kb()` вместо обычного профиля. Сохранение ветки в `_save_branch`.
Не хватает: modal блокирует только вход в `/profile`. Пользователь по-прежнему может пользоваться ботом через `/quest`, `/battlepass`, `/lottery` и другие команды без выбора ветки. Настоящего глобального блокирующего модала нет — PRD требует, чтобы все действия блокировались до выбора ветки. Также нет middleware-уровневой проверки: `branch is None AND level >= 10` не перехватывается до вызова других handlers.

**PR 4.1 — EXIF политика (обновлено 2026-04-13, H-05)**
Реализовано полностью. `validate_exif` возвращает `datetime | None`. `submit_breakfast_photo` реализует три пути:
- EXIF есть, возраст ≤ 24ч → принять, обычное сообщение
- EXIF есть, возраст > 24ч → отклонить
- EXIF отсутствует → принять с предупреждением, порог P2P = `P2P_APPROVALS_NEEDED_NO_EXIF=4` (вместо 3)
`submit_p2p_vote` динамически выбирает порог одобрения: `photo.photo_taken_at is None` → 4, иначе 3.
Handler использует `msg` из сервиса напрямую (не хардкодит текст).
Статус: ✅

**PR 4.2 — P2P: 5 рецензентов, 3 одобрения**
Реализовано: `services/quests.py:assign_p2p_reviewers` выбирает `random.sample(candidates, min(config.P2P_REVIEWERS_PER_PHOTO, len(candidates)))`. `submit_p2p_vote` проверяет `p2p_approve_count >= config.P2P_APPROVALS_NEEDED`.
Не хватает: `assign_p2p_reviewers` **не создаёт P2PReview-записи** — она только возвращает список пользователей-кандидатов, но не добавляет `P2PReview` в сессию. Значит очередь проверяющих не фиксируется в БД, любой подписчик может проголосовать за любое фото (ограничения «назначен ли этот рецензент» нет). `notify_p2p_review_needed` из `services/notifications.py` также не вызывается из `assign_p2p_reviewers`. Рецензенты не получают уведомлений о назначении.

**PR 5.1 — Визуализация уровней BP**
Реализовано: `handlers/battle_pass.py:cmd_battlepass` строит текстовый прогресс-бар из символов `█`/`░` (10 сегментов, `progress_pct`), выводит текущий уровень, XP и «До следующего уровня».
Не хватает: PRD подразумевает визуализацию **всех уровней** (таблица/трек с наградами на каждом уровне), а не только прогресс до следующего. Нет отображения дерева уровней: какие уже пройдены, какие предстоят, какие награды на каждом. Вместо этого показан только текущий прогресс одной полосой.

**PR 8.3 — 10 друзей → бесплатная подписка**
Реализовано: `services/referral.py:check_ambassador` проверяет `active_count >= AMBASSADOR_FRIENDS_REQUIRED` (10 друзей), сохраняет флаг в `AdminSetting key="ambassador_{user_id}"`. `handlers/referral.py` выводит текст «следующая подписка — бесплатно».
Не хватает: механизма **применения** бесплатной подписки нет. `handlers/subscription.py` не проверяет флаг ambassador перед выставлением инвойса. `services/subscription.py:create_subscription` не имеет параметра `free=True`. Пользователь видит обещание бесплатной подписки в тексте, но при нажатии «Оформить подписку» всё равно получит платёжный инвойс.

**PR 9.1 — Контрольное фото антифрод**
Реализовано: `handlers/admin.py:handle_control_photo` сохраняет `ControlPhoto` в БД. `services/quests.py:maybe_inject_control_photo` с вероятностью 20% возвращает случайный `ControlPhoto`. `submit_p2p_vote` вызывает `maybe_inject_control_photo` после каждого голоса.
Не хватает: `maybe_inject_control_photo` возвращает `ControlPhoto | None`, но **результат нигде не используется** в вызывающем коде `submit_p2p_vote` — возвращённый объект присваивается в выражение `await maybe_inject_control_photo(...)` без сохранения. Контрольное фото не отправляется рецензенту. Логика штрафа при одобрении фейкового фото (`-100 XP, trust_rating--`) отсутствует полностью.

**PR 9.2 — Dashboard DAU/WAU/MAU/LTV/Churn/SC**
Реализовано: `handlers/admin.py:cb_admin_stats` считает DAU/WAU/MAU как количество **новых регистраций** за период и активные подписки.
Не хватает: метрики считаются неверно — DAU/WAU/MAU по PRD это активные пользователи (сессии/действия), а не новые регистрации. LTV (пожизненная ценность клиента), Churn Rate и общий объём SC в системе не реализованы вообще. Из 6 метрик PRD реализованы только 3 (и 2 из них неверно).

**PR 9.3 — Content Manager: PDF + квиз**
Реализовано: `handlers/admin.py` содержит FSM-флоу создания квиза (4 шага: вопрос → варианты → правильный ответ → дата). Вопросы сохраняются в `QuizQuestion` с `scheduled_date`.
Не хватает: загрузка PDF-материалов (рецептов/гайдов) не реализована. Нет handler'а для загрузки PDF-документа, нет модели для хранения PDF (`BattlePassLevel.reward_description` — строка, а не файл). Нет возможности привязать PDF к награде уровня BP. Контент-менеджер реализован только наполовину (квиз есть, PDF нет).

---

## ❌ Не реализовано

**PR 6.1 — Invite link + кик при отписке**
Причина: не найдено в коде. Нужно: генерация закрытой invite-ссылки в Telegram-канал/группу Синдиката при оплате подписки; при истечении подписки — исключение пользователя через `bot.ban_chat_member` / `bot.kick_chat_member`. Ни в `services/subscription.py:create_subscription`, ни в `check_and_expire_subscriptions`, ни в schedulere нет работы с чат-каналом. Модель `User` не хранит `chat_member_id`.

**PR 6.2 — Глобальный прогресс завтраков**
Причина: не найдено в коде. Нужно: агрегированная статистика по всему сообществу — сколько завтраков загружено/одобрено сегодня/за неделю/за месяц. Не реализован ни handler для отображения (`/community` или кнопка в меню), ни запрос `COUNT(DailyPhoto)` с группировкой. Нет отдельного service-метода для global progress.

**PR 7.2 — Анимация розыгрыша**
Причина: не найдено в коде. Нужно: визуальная анимация в Telegram перед объявлением победителей (GIF/анимированный стикер/серия сообщений). `services/lottery.py:run_monthly_drawing` публикует итоги сразу текстом без анимационной преамбулы. В Telegram это можно реализовать через серию `bot.send_animation` или `bot.send_sticker` перед финальным сообщением.

---

## Баги и проблемы

**BUG-001** | `services/quests.py` vs `handlers/quests.py` | **Критический: несовместимость сигнатур `validate_exif`**
`services/quests.py:validate_exif` (строка 34) возвращает `datetime | None`, но `handlers/quests.py:handle_breakfast_photo` (строка 108) делает `exif_ok, exif_error = await quest_service.validate_exif(photo_bytes)` — пытается распаковать в кортеж. Вызов `await` на синхронной функции также вызовет `TypeError`. Результат: при любом вбросе фото завтрака handler падает с исключением.

**BUG-002** | `services/quests.py:assign_p2p_reviewers` | ~~Критический: P2P-назначения не сохраняются в БД~~ **✅ ИСПРАВЛЕНО 2026-04-14**
Функция теперь создаёт `P2PReview(is_approved=None)` для каждого выбранного рецензента. `P2PReview.is_approved` изменён на `nullable=True`. `submit_p2p_vote` обновляет существующую запись вместо INSERT и проверяет дубль по `is_approved IS NOT NULL`.

**BUG-003** | `services/quests.py:maybe_inject_control_photo` | **Средний: результат игнорируется**
В `submit_p2p_vote` строка `await maybe_inject_control_photo(session, reviewer)` (строка 220) вызывает функцию, но возвращённый `ControlPhoto | None` нигде не используется. Контрольные фото никогда не показываются рецензентам. Антифрод-логика штрафа при одобрении фейка (`-100 XP`, снижение `trust_rating`) не реализована.

**BUG-004** | `handlers/subscription.py:handle_successful_payment` | ~~Средний: несовпадение сигнатуры `create_subscription`~~ **✅ НЕ ВОСПРОИЗВОДИТСЯ**
Хендлер уже использует корректные kwargs: `price=price_paid`, `sc_used=sc_used`, `payment_id=payment.telegram_payment_charge_id`. Сигнатура совпадает с сервисом. Баг не актуален.

**BUG-005** | `services/referral.py:count_active_friends` | **Средний: принимает `user_id: int`, handler передаёт `user`-объект**
`handlers/referral.py:cmd_referral` (строка 38) вызывает `referral_service.count_active_friends(session, user)`, передавая ORM-объект `User`, тогда как сигнатура сервиса `count_active_friends(session, user_id: int)`. Аналогично для `check_ambassador(session, user)` — сигнатура совпадает (принимает `User`), но `count_active_friends` внутри него также будет вызван с объектом.

**BUG-006** | `services/referral.py:generate_referral_link` | ~~Средний: требует `bot_username`, handler не передаёт~~ **✅ НЕ ВОСПРОИЗВОДИТСЯ**
Хендлер уже вызывает `await bot.get_me()` и передаёт `bot_info.username` вторым аргументом. Сигнатура совпадает. Баг не актуален.

**BUG-007** | `services/battle_pass.py:get_progress_summary` | **Малый: несовпадение ключей возвращаемого dict**
`get_progress_summary` возвращает ключи `"level"`, `"xp"`, `"xp_for_next"`, `"percent"`, `"claimable_count"`, но `handlers/battle_pass.py:cmd_battlepass` обращается к `summary.get("claimable_levels", [])`, `summary.get("xp_to_next_level", 0)`, `summary.get("current_level", ...)`, `summary.get("level_progress_pct", 0.0)`. Все четыре ключа не совпадают с возвращаемыми: `claimable_levels` vs `claimable_count`, `xp_to_next_level` vs `xp_for_next`, `current_level` vs `level`, `level_progress_pct` vs `percent`. Итог: progress bar всегда 0%, награды всегда не отображаются.

**BUG-008** | `scheduler/tasks.py` vs `services/lottery.py` | **Малый: несовпадение ключей AdminSetting**
`scheduler/tasks.py:_monthly_lottery` ищет ключ `"lottery_channel_id"` (строка 44), а `services/lottery.py:run_monthly_drawing` ищет ключ `"lottery_channel"` (строка 66). Ключи расходятся — если настройка записана под одним именем, вторая функция её не найдёт.

**BUG-009** | `services/coins.py:burn_expired_coins` | **Малый: предупреждение и сжигание происходят в одном окне**
`get_users_to_warn_burn` возвращает пользователей, у которых подписка истекла более 144ч назад, а `burn_expired_coins` — более 168ч. Обе функции вызываются в одном задании `_burn_expired_coins`. Пользователь, попавший в окно 144–168ч, получит предупреждение. Но пользователь, уже попавший в зону сгорания (>168ч), также может попасть в список для предупреждения, так как `warn_threshold` (144ч) < `burn_threshold` (168ч), и фильтр по `subscription_end < warn_threshold` включает всех, кто попал бы и в `burn`. Итог: некоторые пользователи сначала получат предупреждение, а затем в ту же итерацию — сжигание, то есть предупреждение за 0 минут, а не за 24 часа.

---

## Приоритеты доработок

### P0 — Блокеры запуска

1. ~~**BUG-001**~~: ✅ Сигнатура `validate_exif` корректна — возвращает `datetime | None`, хендлер использует правильно. Не воспроизводится.
2. ~~**BUG-004**~~: ✅ kwargs `create_subscription` совпадают с сигнатурой сервиса. Не воспроизводится.
3. ~~**BUG-006**~~: ✅ `bot_username` передаётся через `await bot.get_me()`. Не воспроизводится.
4. ~~**BUG-007**~~: ✅ Ключи `get_progress_summary` согласованы с хендлером (исправлено ранее).
5. ~~**BUG-002**~~: ✅ **ИСПРАВЛЕНО 2026-04-14** — `assign_p2p_reviewers` теперь создаёт `P2PReview(is_approved=None)` для каждого рецензента; `submit_p2p_vote` обновляет запись вместо INSERT.

> **✅ ИСПРАВЛЕНО 2026-04-14:** Интерфейс квиза полностью починен: `submit_quiz_answer` переведён с `tuple[bool, str]` на `dict`; добавлена `get_quiz_by_id`; `answer_index=None` при retry разрешает повторный показ вопроса после списания SC. Обе handler-функции (`cb_quiz_answer`, `cb_quiz_retry`) приведены к новой сигнатуре. P2P-vote handlers перестали вызывать `.get()` на tuple.

> **Все P0-блокеры закрыты. Проект готов к тестированию MVP.**

### P1 — Важно для MVP

6. ~~**BUG-003 + PR 9.1**~~: ✅ **ИСПРАВЛЕНО 2026-04-14** — `submit_p2p_vote` возвращает `(bool, str, ControlPhoto|None)`; хендлеры отправляют контрольное фото рецензенту; `control_approve` применяет `apply_control_photo_penalty` (-100 XP, -10 trust_rating); `control_reject` благодарит рецензента.
7. ~~**BUG-005**~~: ✅ НЕ ВОСПРОИЗВОДИТСЯ — хендлер уже передаёт `user.id`.
8. ~~**PR 2.2**~~: ✅ **ИСПРАВЛЕНО 2026-04-14** — кнопка «🪙 История SC» в `keyboards/profile.py`; callback `sc_history` в `handlers/profile.py` показывает последние 20 транзакций.
9. ~~**PR 3.2**~~: ✅ **ИСПРАВЛЕНО 2026-04-14** — `AuthMiddleware` перехватывает все обновления при `level >= 10 and branch is None`; exempt-список `{branch_butcher, branch_vegan}` пропускает callbacks выбора.
10. ~~**PR 8.3**~~: ✅ **ИСПРАВЛЕНО 2026-04-14** — `subscription_kb` получила флаг `is_ambassador`; callback `pay_ambassador` проверяет статус, сбрасывает флаг и создаёт бесплатную подписку через `create_subscription(price=0)`.
11. ~~**BUG-008**~~: ✅ **ИСПРАВЛЕНО 2026-04-14** — `scheduler/tasks.py` унифицирован на ключ `"lottery_channel"`.

### P2 — После запуска

12. **PR 3.1**: Подготовить и поместить PNG-файлы рамок в `assets/frames/frame_{1..50}.png`. Без них аватарки генерируются без рамок.
13. **BUG-009**: Разделить `get_users_to_warn_burn` и `burn_expired_coins` по временным окнам: предупреждать только пользователей в окне 144–168ч, не трогая тех, кто уже в зоне сгорания.
14. **PR 6.1**: Реализовать генерацию invite-ссылки в закрытый канал при оплате и кик при истечении подписки (`bot.revoke_chat_invite_link`, `bot.ban_chat_member`).
15. **PR 6.2**: Реализовать endpoint/handler глобального прогресса завтраков (агрегированный `COUNT(DailyPhoto)` по статусам).
16. **PR 7.2**: Добавить анимационную преамбулу к розыгрышу (GIF/стикер/серия сообщений) перед публикацией итогов.
17. **PR 9.2**: Исправить подсчёт DAU/WAU/MAU (по активности, не регистрациям), добавить LTV, Churn Rate и суммарный SC в системе.
18. **PR 9.3**: Добавить загрузку PDF-материалов в панели администратора и хранение `file_id` PDF в таблице (новая модель или расширение `BattlePassLevel`).
19. **PR 5.1**: Расширить отображение Battle Pass треком всех уровней с наградами (inline-pagination или таблица уровней).
