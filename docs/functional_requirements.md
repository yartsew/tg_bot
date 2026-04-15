# Функциональные требования — Кулинарный Синдикат

**Версия:** 1.1  
**Дата:** 2026-04-15  
**Статус:** Актуально (синхронизировано с PRD v1.1)

## Условные обозначения

- **Приоритет:** P0 (блокер запуска), P1 (MVP — до первого публичного релиза), P2 (после запуска)
- **Агент:** файл(ы) сервиса / хендлера, которые реализуют требование
- **Модели:** таблицы SQLAlchemy из `database/models.py`, затрагиваемые требованием
- **EC** — edge case (граничный сценарий)

---

## 1. Экономика и подписка

### FR-001: Рекуррентное продление подписки
**Источник:** PR 1.1
**Описание:** После истечения 30-дневного периода система автоматически инициирует повторное списание. При неудаче платёжного провайдера — делает три попытки с интервалом 24 ч (итого за 3 дня). После третьей неудачной попытки устанавливает статус `blocked` и запрещает доступ к функциям бота.
**Входные данные:**
- `Subscription.end_date < now()` и `Subscription.status == "active"` → переход в `"failed"`
- `Subscription.status == "failed"`, `renewal_attempts < 3`, `last_attempt < now - 24h` → повторная попытка
**Изменения состояния:**
- `Subscription.renewal_attempts += 1`, `Subscription.last_attempt = now`
- При успехе: создаётся новая запись `Subscription` (status=`active`), `User.is_subscribed = True`, `User.subscription_end = now + 30d`
- При трёх провалах: `Subscription.status = "blocked"`, `User.subscription_blocked = True`
**Реализует:** `services/subscription.py::retry_failed_subscriptions`, `services/subscription.py::check_and_expire_subscriptions`, `scheduler/tasks.py::_retry_subscriptions` (каждые 6 ч)
**Модели:** `Subscription`, `User`
**Edge cases:**
- EC1: Телеграм-платёж завис (pending у провайдера) — система не получает webhook; нужна проверка тайм-аута на стороне провайдера или ручной сброс администратором.
- EC2: Пользователь заблокировал бота — `bot.send_message` выбросит исключение; оно поглощается, статус всё равно обновляется.
- EC3: Пользователь вручную оплатил подписку между двумя автоматическими попытками — нужен сброс `renewal_attempts = 0` и `status = "active"` при получении `successful_payment`.
- EC4: Часы сервера рассинхронизированы с Telegram — ошибочное истечение раньше срока; хранить `end_date` в UTC, сверять с UTC.
**Приоритет:** P0

---

### FR-002: Виджет «Призовой фонд месяца» в TWA
**Источник:** PR 1.2
**Описание:** В TWA (Telegram Web App) отображается виджет, показывающий текущий призовой фонд месяца в реальном времени. Фонд = `SUM(price_paid) по active-подпискам текущего месяца × prize_fund_percent`.
**Входные данные:** Запрос к TWA-эндпоинту (WebApp-вызов или Telegram Bot API Mini App data).
**Изменения состояния:** Только чтение; состояние не меняется.
**Реализует:** `services/subscription.py::get_prize_fund`, `services/subscription.py::get_prize_fund_percent`. Отдельный TWA-маршрут (пока не реализован — требуется создать FastAPI/aiohttp endpoint или отдельный TWA HTML-файл, вызывающий бот-API).
**Модели:** `Subscription`, `AdminSetting` (key=`prize_fund_percent`)
**Edge cases:**
- EC1: В текущем месяце нет ни одной активной подписки — `SUM` возвращает `NULL`; `func.coalesce(..., 0.0)` уже обрабатывает это в `get_prize_fund`.
- EC2: `prize_fund_percent` не задан в `AdminSetting` — используется `config.DEFAULT_PRIZE_FUND_PERCENT` (30 % по умолчанию из PRD).
- EC3: Пользователь видит значение с задержкой до следующего SSE/polling-тика — необходим механизм обновления (WebSocket / Server-Sent Events / poll каждые 30 с).
- EC4: Возврат платежа (refund) уменьшает реальную выручку, но `Subscription` уже создана; нужен механизм корректировки через `admin.py`.
**Приоритет:** P1

---

### FR-003: Изменение цены подписки и процента фонда администратором без остановки бота
**Источник:** PR 1.3
**Описание:** Администратор из панели `/admin` меняет цену подписки (ключ `subscription_price`) и процент призового фонда (ключ `prize_fund_percent`) через FSM-диалог. Новые значения сохраняются в `AdminSetting` и применяются немедленно при следующем запросе `get_subscription_price` / `get_prize_fund_percent` — без перезапуска бота.
**Входные данные:** Сообщение администратора с числовым значением в состояниях `AdminStates.waiting_subscription_price` / `AdminStates.waiting_setting_value`.
**Изменения состояния:** Upsert `AdminSetting` (key=`subscription_price` или `prize_fund_percent`).
**Реализует:** `handlers/admin.py::handle_new_price`, `handlers/admin.py::handle_setting_value`, `services/subscription.py::get_subscription_price`, `services/subscription.py::get_prize_fund_percent`
**Модели:** `AdminSetting`
**Edge cases:**
- EC1: Вводится отрицательное или нулевое число — необходима валидация `new_price > 0`.
- EC2: Вводится строка вместо числа — `float(message.text)` вызовет `ValueError`; уже обработано через `try/except`.
- EC3: Параллельный запрос подписки в момент обновления цены — нет транзакционного конфликта, так как чтение и запись атомарны на уровне SQLite/Postgres row; при переходе на Postgres нужен `SELECT FOR UPDATE`.
- EC4: `prize_fund_percent` сохраняется как дробь (0–1), отображается как %; некорректный ввод «0.3» вместо «30» — обработка через нормализацию `/ 100.0` в `handle_setting_value`.
**Приоритет:** P0

---

## 2. Синдикат Коинс (SC)

### FR-004: Частичная оплата подписки монетами SC
**Источник:** PR 2.1
**Описание:** На экране оплаты подписки отображается чекбокс/кнопка «Использовать SC». Пользователь может списать SC в счёт скидки максимум на 50 % от цены подписки. Оставшаяся сумма оплачивается через Telegram Payments.
**Входные данные:**
- `user.sc_balance` — текущий баланс
- `subscription_price` — текущая цена из `AdminSetting`
- `max_sc_discount = int(price * 0.5)` — ограничение
- `sc_to_use = min(sc_balance, max_sc_discount)`
**Изменения состояния:**
- `User.sc_balance -= sc_to_use`
- Запись `SCTransaction(amount=-sc_to_use, description="частичная оплата подписки")`
- Инвойс выставляется на `remaining = price - sc_to_use` рублей
- `Subscription.sc_paid = sc_to_use`
**Реализует:** `handlers/subscription.py::cb_pay_with_sc`, `handlers/subscription.py::cb_confirm_sc`, `handlers/subscription.py::handle_successful_payment`, `services/coins.py::deduct_sc`
**Модели:** `User`, `SCTransaction`, `Subscription`
**Edge cases:**
- EC1: Баланс SC = 0 — кнопка «Использовать SC» должна быть скрыта или заблокирована (`has_sc` флаг в `subscription_kb`).
- EC2: SC списаны, но Telegram-платёж отклонён — SC должны быть возвращены; требуется rollback или компенсационная транзакция (сейчас не реализована).
- EC3: `remaining` после скидки < минимальный платёж провайдера (обычно 1 ₽) — инвойс на 0 нельзя выставить; необходима проверка `remaining >= 1.0`.
- EC4: Цена подписки изменилась администратором между показом экрана и подтверждением — нужно перерасчитать `sc_to_use` в момент `confirm_sc`, не доверять кэшу FSM.
**Приоритет:** P0

---

### FR-005: Транзакционный лог SC для пользователя
**Источник:** PR 2.2  
**Обновлено:** 2026-04-15 (PRD v1.1 — функция полностью реализована)
**Описание:** Пользователь может просмотреть историю начислений и списаний SC в хронологическом порядке (от новых к старым). Каждая строка содержит знак `+`/`-`, количество SC и читаемое описание операции, например: `«+50 SC за 25 уровень»`, `«-745 SC за подписку»`. Последние 20 транзакций отображаются без пагинации.
**Входные данные:** Кнопка «История SC» в профиле (callback `sc_history`) → вызов `services/coins.py::get_transactions`.
**Изменения состояния:** Только чтение.
**Реализует:** `services/coins.py::get_transactions`, `handlers/profile.py::cb_sc_history` (callback `sc_history`), `keyboards/profile.py` (кнопка «История SC» в клавиатуре профиля)
**Модели:** `SCTransaction`
**Edge cases:**
- EC1: История пустая (новый пользователь) — показать заглушку «Транзакций пока нет».
- EC2: Более 20 транзакций — `get_transactions(limit=20)` возвращает только 20; нужна пагинация или кнопка «Ещё».
- EC3: `description` содержит спецсимволы HTML — нужно экранировать через `html.escape()` при отправке с `parse_mode="HTML"`.
- EC4: Транзакция создана автоматически (burn) — в описании стоит `"сгорели"` без суммы; исправить шаблон описания в `burn_expired_coins` на `f"сгорели {burned_amount} SC"`.
**Приоритет:** P1 → **реализовано**

---

### FR-006: Сгорание SC при длительной неподписке
**Источник:** PR 2.3
**Описание:** Если пользователь не является подписчиком (`is_subscribed = False`) более 168 ч (7 дней) с момента истечения подписки, его баланс SC обнуляется. За 24 ч до обнуления (то есть при `subscription_end < now - 144 h`) отправляется предупреждение.
**Входные данные:** Планировщик каждые 1 ч вызывает `_burn_expired_coins`.
**Изменения состояния:**
- Предупреждение: `bot.send_message` пользователю (состояние не меняется)
- Сжигание: `User.sc_balance = 0`, `SCTransaction(amount=-burned_amount, description="сгорели")`
**Реализует:** `services/coins.py::burn_expired_coins`, `services/coins.py::get_users_to_warn_burn`, `services/notifications.py::notify_sc_burn_warning`, `scheduler/tasks.py::_burn_expired_coins` (каждые 1 ч)
**Модели:** `User`, `SCTransaction`
**Edge cases:**
- EC1: Пользователь продлил подписку между предупреждением и сжиганием — `is_subscribed` станет `True`, запрос `get_users_to_warn_burn` и `burn_expired_coins` его уже не затронет.
- EC2: `subscription_end = NULL` (подписка никогда не оформлялась) — фильтр `User.subscription_end < threshold` вернёт `False` для NULL; такие пользователи не попадают в выборку (корректно).
- EC3: Пользователь заблокировал бота — `bot.send_message` упадёт с `TelegramForbiddenError`; исключение поглощается, сжигание происходит.
- EC4: Предупреждение отправляется повторно при каждом запуске планировщика (каждый час, пока `subscription_end < now - 144h`); необходим флаг `sc_burn_warned` на модели `User` или запись в `AdminSetting` для дедупликации.
**Приоритет:** P0

---

## 3. Профиль и прогрессия

### FR-007: Аватар с PNG-рамкой уровня
**Источник:** PR 3.1
**Описание:** Пользователь запрашивает генерацию аватара. Сервис скачивает фото профиля Telegram, накладывает PNG-рамку уровня (из `assets/frames/frame_{level}.png`) через Pillow и возвращает результат как JPEG-фото.
**Входные данные:** Callback `get_avatar`, фото профиля из `bot.get_user_profile_photos`, `user.level`.
**Изменения состояния:** Только чтение + отправка сгенерированного изображения.
**Реализует:** `handlers/profile.py::cb_get_avatar`, `services/avatar.py::generate_avatar`
**Модели:** `User`
**Edge cases:**
- EC1: У пользователя нет фото профиля — `photos.total_count == 0`; показать сообщение «Установи аватар в Telegram».
- EC2: Файл `frame_{level}.png` отсутствует — фоллбэк на `frame_1.png`; если и он отсутствует, `Image.open` упадёт с `FileNotFoundError`; нужен `try/except` с ответом об ошибке.
- EC3: Фото профиля в формате, который Pillow не поддерживает — `Image.open` выбросит исключение; поймать и вернуть понятное сообщение.
- EC4: Фото слишком большое (>10 МБ) — Telegram не позволит скачать через `download_file`; ограничение на стороне Telegram API; логировать ошибку.
- EC5: Параллельные запросы от одного пользователя (двойное нажатие) — Pillow не потокобезопасен при записи одного файла; операция полностью in-memory (`io.BytesIO`), конфликтов нет.
**Приоритет:** P1

---

### FR-008: Modal выбора ветки на уровне 10
**Источник:** PR 3.2  
**Обновлено:** 2026-04-15 (PRD v1.1 — блокирующий modal перенесён в `AuthMiddleware`)
**Описание:** При достижении уровня 10 пользователь обязан выбрать ветку («Мясник» или «Веган») перед выполнением любого другого действия в боте. Выбор необратим и меняет тип рекомендуемых гайдов. Блокировка обеспечивается на уровне `AuthMiddleware`, а не только в хендлере `/profile` — `AuthMiddleware` перехватывает любые обновления при `user.level >= 10 and user.branch is None` и показывает modal выбора ветки, прерывая обработку.
**Входные данные:** `user.level >= 10` и `user.branch is None` — проверяется в `AuthMiddleware` на каждом апдейте.
**Изменения состояния:** `User.branch = "butcher"` или `"vegan"`.
**Реализует:** `middlewares/auth.py` (перехват любого апдейта при `level >= 10 and branch is None`; exempt-callbacks: `{branch_butcher, branch_vegan}`), `handlers/profile.py::cb_branch_butcher`, `handlers/profile.py::cb_branch_vegan`, `handlers/profile.py::_save_branch`
**Модели:** `User`
**Edge cases:**
- EC1: Пользователь попытался изменить ветку после выбора — `user.branch is not None`; блокировать с сообщением «Ветка уже выбрана».
- EC2: Пользователь закрыл Modal, не выбрав ветку — при следующем любом действии `AuthMiddleware` снова показывает modal (пока `branch is None`); выйти из блокировки невозможно без выбора.
- EC3: Два параллельных запроса на сохранение ветки (двойное нажатие) — второй `_save_branch` обнаружит `user.branch is not None` и вернёт уже выбранную ветку.
- EC4: Гайды, зависящие от ветки, ещё не реализованы — обеспечить graceful degradation: ветка сохраняется, но фильтрация гайдов появится позже.
- EC5: Callback `branch_butcher` / `branch_vegan` должны быть в списке exempt в `AuthMiddleware`, иначе middleware заблокирует и сами ответы на выбор ветки.
**Приоритет:** P1

---

### FR-009: Код наставника на уровне 50+
**Источник:** PR 3.3
**Описание:** Пользователь уровня 50+ получает доступ к кнопке «Код наставника» в профиле. Нажатие отображает уникальный `referral_code` пользователя и deep-link вида `t.me/{bot}?start=ref{code}`. Новичок вводит этот код при регистрации (через `/start refCODE`), и в `User.mentor_id` записывается ID наставника.
**Входные данные:** Callback `gen_mentor_code`, `user.level >= 50`.
**Изменения состояния:** Только чтение (код уже существует в `User.referral_code`). При использовании кода новичком: `User.mentor_id = mentor.id`, запись `Referral`.
**Реализует:** `handlers/profile.py::cb_gen_mentor_code`, `handlers/start.py::cmd_start`, `services/referral.py::process_referral`
**Модели:** `User`, `Referral`
**Edge cases:**
- EC1: Пользователь уровня < 50 нажимает кнопку — показать сообщение «Доступно с уровня 50».
- EC2: Новичок вводит несуществующий код — `process_referral` вернёт `False`; регистрация завершается без реферала.
- EC3: Новичок вводит свой собственный код — проверка `referrer.id == new_user.id` блокирует это.
- EC4: Новичок уже зарегистрирован (повторный `/start refCODE`) — `process_referral` проверяет `Referral.referred_id` на уникальность; повторная запись не создаётся.
- EC5: Наставник ещё не набрал уровень 50, но уже имеет `referral_code` — кнопка «Код наставника» скрыта; `referral_code` генерируется при регистрации для всех пользователей, но экспонируется только после уровня 50.
**Приоритет:** P1

---

## 4. Квесты

### FR-010: EXIF-политика фото завтрака
**Источник:** PR 4.1  
**Обновлено:** 2026-04-13 (H-05, Softcopy EXIF)
**Описание:** При загрузке фото завтрака система извлекает `DateTimeOriginal` из EXIF и применяет трёхпутевую логику:

| Условие | Действие | Порог P2P |
|---------|----------|-----------|
| EXIF есть, возраст ≤ 24 ч | Принять | 3 из 5 (`P2P_APPROVALS_NEEDED`) |
| EXIF есть, возраст > 24 ч | Отклонить | — |
| EXIF отсутствует (`photo_taken_at = None`) | Принять с предупреждением | 4 из 5 (`P2P_APPROVALS_NEEDED_NO_EXIF`) |

Пользователь получает контекстное сообщение, явно указывающее на причину: стандартный приём, предупреждение об отсутствии EXIF, или ошибку устаревшего фото.

**Входные данные:** Байты фото из `bot.download_file`, `datetime.utcnow()`.
**Изменения состояния:** При отклонении: состояние не меняется. При принятии: создаётся `DailyPhoto` с `photo_taken_at` (может быть `None`).
**Реализует:** `services/quests.py::validate_exif` (sync, возвращает `datetime | None`), `services/quests.py::submit_breakfast_photo`, `services/quests.py::submit_p2p_vote` (динамический порог), `handlers/quests.py::handle_breakfast_photo`
**Конфиг:** `config.P2P_APPROVALS_NEEDED = 3`, `config.P2P_APPROVALS_NEEDED_NO_EXIF = 4`
**Модели:** `DailyPhoto.photo_taken_at` используется как прокси-флаг наличия EXIF (не требует отдельного поля в схеме)
**Edge cases:**
- EC1: ~~EXIF отсутствует — решено:~~ принять с порогом 4/5 и предупреждением. (Закрыт H-05, 2026-04-13)
- EC2: EXIF-время в локальной временной зоне устройства — расхождение с UTC сервера может дать ложное отклонение; нужна нормализация или допуск ±нескольких часов.
- EC3: Пользователь отправляет фото без сжатия (как файл) — Telegram передаёт документ, а не `photo`; хендлер `QuestStates.waiting_photo, F.photo` не сработает; нужен дополнительный хендлер для `F.document`.
- EC4: ~~Пересланное фото (EXIF очищен Telegram)~~ — обрабатывается как отсутствие EXIF (принять с порогом 4/5). (Закрыт H-05, 2026-04-13)
- EC5: Дата съёмки в будущем (некорректные часы устройства) — `age` будет отрицательным; формально проверка `age > 24h` не сработает; добавить проверку `photo_taken_at > now + 1h → reject`.
**Приоритет:** P0

---

### FR-011: P2P-проверка фото (5 рецензентов, порог по EXIF)
**Источник:** PR 4.2  
**Обновлено:** 2026-04-15 (PRD v1.1 — двойной порог одобрения, новая схема назначения P2PReview, submit_p2p_vote возвращает ControlPhoto)
**Описание:** После принятия фото оно получает статус `p2p_pending` и назначается 5 случайным активным подписчикам (исключая автора). Каждый рецензент голосует «Одобрить» или «Отклонить». Порог одобрения зависит от наличия EXIF: **3 из 5** (фото с EXIF) или **4 из 5** (фото без EXIF, повышенный антифрод). При достижении порога фото переходит в статус `approved`, автор получает XP.
**Входные данные:** `DailyPhoto` со статусом `p2p_pending`, список активных подписчиков. Порог определяется по `DailyPhoto.photo_taken_at`: `None` → 4/5, иначе → 3/5.
**Изменения состояния:**
- `assign_p2p_reviewers` создаёт `P2PReview(photo_id, reviewer_id, is_approved=None)` для каждого из 5 назначенных рецензентов — **записи создаются в момент назначения, не в момент голосования**
- `submit_p2p_vote` обновляет существующую запись `P2PReview` (UPDATE `is_approved = True/False`), а не создаёт новую (INSERT)
- `P2PReview.is_approved` — `nullable=True` (`None` = голос ещё не подан, `True` = одобрено, `False` = отклонено)
- `DailyPhoto.p2p_approve_count++` при каждом одобрении
- При `approve_count >= порог`: `DailyPhoto.status = "approved"`, `User.xp += XP_BREAKFAST_PHOTO`
- `submit_p2p_vote` возвращает `(bool, str, ControlPhoto | None)` — третий элемент не `None`, если голосование пришлось на контрольное фото
**Реализует:** `services/quests.py::assign_p2p_reviewers`, `services/quests.py::submit_p2p_vote` (возвращает `tuple[bool, str, ControlPhoto | None]`), `handlers/quests.py::cb_p2p_approve`, `handlers/quests.py::cb_p2p_reject` (обрабатывают третий элемент кортежа и показывают рецензенту контрольное фото при необходимости), `services/notifications.py::notify_p2p_review_needed`
**Модели:** `DailyPhoto`, `P2PReview` (`is_approved nullable=True`), `User`
**Edge cases:**
- EC1: Меньше 5 активных подписчиков — `random.sample(candidates, min(5, len))` корректно обрабатывает это; однако порог 3 (или 4) одобрений недостижим при < 3 (< 4) подписчиков — необходим динамический порог или минимальный размер пула.
- EC2: Рецензент пытается проголосовать дважды — `submit_p2p_vote` проверяет, что `P2PReview.is_approved is not None` для данной пары `(photo_id, reviewer_id)`, и возвращает ошибку без повторного обновления.
- EC3: Автор фото попадает в список рецензентов — `assign_p2p_reviewers` исключает `photo.user_id`; корректно.
- EC4: Фото набирает 5 отклонений раньше порога одобрений — текущая логика не устанавливает статус `rejected` при избытке reject; нужно добавить порог отклонения (например, `reject_count >= 3`).
- EC5: Рецензент голосует, но `P2PReview`-запись для него отсутствует (назначение не было выполнено) — `submit_p2p_vote` должна возвращать ошибку «не назначен рецензентом».
- EC6: Рецензент одобряет контрольное (фейковое) фото — `submit_p2p_vote` возвращает `(True, ..., ControlPhoto)`; хендлер `cb_p2p_approve` передаёт фото рецензенту и вызывает `apply_control_photo_penalty` (см. FR-025).
**Приоритет:** P0

---

### FR-012: Ежедневный квиз «Специя дня» с платным retry
**Источник:** PR 4.3  
**Обновлено:** 2026-04-14 (исправление интерфейса сервис↔хендлер)
**Описание:** Каждый день доступен один вопрос квиза (4 варианта ответа), заранее запланированный администратором. Неверный ответ показывает кнопку «Попробовать ещё раз за 10 SC». Оплаченная попытка списывает SC и показывает вопрос повторно.
**Входные данные:** Callback `daily_quiz`; `QuizQuestion.scheduled_date == today`; ответ: `quiz_answer:{qid}:{index}`; retry: `quiz_retry:{qid}`.
**Изменения состояния:**
- `UserQuizAttempt` — создаётся/обновляется (одна запись на пару `user_id + question_id` в день)
- При retry: `SCTransaction(amount=-10, description="повторная попытка квиза")`, `User.sc_balance -= 10`
- При верном ответе: `User.xp += XP_QUIZ_CORRECT`
**Реализует:** `handlers/quests.py::cb_daily_quiz`, `handlers/quests.py::cb_quiz_answer`, `handlers/quests.py::cb_quiz_retry`, `services/quests.py::get_todays_quiz`, `services/quests.py::get_quiz_by_id`, `services/quests.py::submit_quiz_answer`, `services/coins.py::deduct_sc`
**Сигнатура `submit_quiz_answer`:**
```
submit_quiz_answer(session, user, question_id, answer_index: int | None, paid_retry: bool = False) -> dict
```
Возвращает: `{success, already_answered, is_correct, xp_earned, sc_earned, correct_option, retry_cost, retry_granted, message}`.
При `paid_retry=True, answer_index=None` — списывает SC и возвращает `retry_granted=True`; вопрос показывается заново через `get_quiz_by_id`.
**Модели:** `QuizQuestion`, `UserQuizAttempt`, `User`, `SCTransaction`
**Edge cases:**
- EC1: На сегодня вопрос не запланирован — `get_todays_quiz` возвращает `None`; показать заглушку «Вопрос ещё не добавлен».
- EC2: Пользователь уже ответил верно — `already_answered=True` в ответе сервиса; повторный вход блокируется.
- EC3: Недостаточно SC для retry — `retry_granted=False`, `success=False`; показать сообщение с текущим балансом.
- EC4: Два вопроса запланированы на одну дату — `get_todays_quiz` может вернуть `MultipleResultsFound`; нужен `order_by(id).limit(1)`.
- EC5: Пользователь нажимает retry многократно до получения правильного ответа — каждый вызов списывает 10 SC; рассмотреть лимит попыток в день (например, 3).
**Приоритет:** P1

---

## 5. Battle Pass

### FR-013: Горизонтальный скролл уровней в TWA
**Источник:** PR 5.1
**Описание:** В TWA-интерфейсе отображается горизонтальная полоса уровней Battle Pass (1–50, затем бесконечный режим). Текущий уровень выделен, пройденные — закрашены, будущие — серые. Нажатие на уровень показывает описание награды.
**Входные данные:** `services/battle_pass.py::get_progress_summary`, `services/battle_pass.py::get_level_thresholds`.
**Изменения состояния:** Только чтение.
**Реализует:** TWA frontend (HTML/JS, пока не реализован); данные предоставляет `services/battle_pass.py::get_progress_summary`; нужен REST/JSON-эндпоинт для TWA.
**Модели:** `BattlePassLevel`, `UserReward`, `User`
**Edge cases:**
- EC1: Таблица `BattlePassLevel` пустая — `get_level_thresholds` генерирует дефолтную таблицу `lvl * BP_XP_PER_LEVEL`; TWA отображает без наград из БД.
- EC2: Более 50 уровней в бесконечном режиме — UI должен поддерживать динамическую генерацию плиток `50+n`.
- EC3: Медленное соединение — TWA делает запрос и ждёт ответа; добавить skeleton-loader.
**Приоритет:** P2

---

### FR-014: Ручное получение наград (Claim Rewards)
**Источник:** PR 5.2
**Описание:** После достижения нового уровня награды НЕ выдаются автоматически. Пользователь видит список доступных наград в `/battlepass` и нажимает «Забрать» для каждой. После нажатия SC/лотерейный билет/гайд зачисляются на аккаунт.
**Входные данные:** Callback `claim_reward_{level}`, `UserReward.claimed == False`.
**Изменения состояния:**
- `UserReward.claimed = True`, `UserReward.claimed_at = now`
- Для `reward_type="sc"`: `User.sc_balance += reward_amount`, `SCTransaction(+amount, description=f"награда за уровень {level}")`
- Для `reward_type="ticket"`: создаётся `LotteryTicket(uuid4)`
- Для `reward_type="guide"`: нет изменений состояния, текст отображается в ответе
**Реализует:** `handlers/battle_pass.py::cb_claim_reward`, `services/battle_pass.py::claim_reward`, `services/coins.py::add_sc`, `services/lottery.py::issue_ticket`
**Модели:** `UserReward`, `BattlePassLevel`, `User`, `SCTransaction`, `LotteryTicket`
**Edge cases:**
- EC1: Пользователь нажимает «Забрать» дважды (двойной клик) — второй запрос не найдёт запись с `claimed=False`; вернёт «Награда не найдена».
- EC2: Награда типа `guide` — нет файла PDF; нужен механизм доставки (ссылка или `send_document`).
- EC3: Бесконечный уровень (50+n) не имеет записи в `BattlePassLevel` — `bp_level = None`; в `claim_reward` уже реализован fallback: выдаётся лотерейный билет.
**Приоритет:** P1

---

### FR-015: Бесконечный режим после уровня 50
**Источник:** PR 5.3
**Описание:** После достижения уровня 50 накопленный XP продолжает расти. Каждые `BP_INFINITE_BONUS_XP` (1000 XP по PRD) сверх порога уровня 50 автоматически создаётся запись `UserReward` для синтетического уровня `50+n`, которую пользователь может забрать вручную.
**Входные данные:** `user.xp`, `thresholds[50]`, `config.BP_INFINITE_BONUS_XP = 1000`.
**Изменения состояния:** При каждом добавлении XP: `UserReward(level=50+n, claimed=False)` для ещё не созданных наград.
**Реализует:** `services/battle_pass.py::add_xp` (блок «After level 50»), `handlers/battle_pass.py::cmd_battlepass`
**Модели:** `UserReward`, `User`
**Edge cases:**
- EC1: Пользователь получает большой XP-буст (+5000 XP за одну операцию) — создаётся 5 записей `UserReward` сразу; корректно обрабатывается циклом `range(1, infinite_rewards_earned + 1)`.
- EC2: `UserReward` уже существует для данного синтетического уровня (повторный вызов `add_xp`) — `SELECT` перед `INSERT` предотвращает дублирование.
- EC3: `BP_INFINITE_BONUS_XP` изменяется в рантайме — старые накопленные XP пересчитываются некорректно; значение должно быть иммутабельным в `config.py`.
**Приоритет:** P1

---

## 6. Сообщество и социальные функции

### FR-016: Хранение invite link и кик при отписке
**Источник:** PR 6.1
**Описание:** Бот хранит ссылку-приглашение в закрытый чат Синдиката (`AdminSetting` key=`community_invite_link`). При оформлении подписки пользователь получает ссылку. При истечении/блокировке подписки бот кикает пользователя из чата через `bot.ban_chat_member` / `bot.unban_chat_member`.
**Входные данные:** `Subscription.status → "expired"` или `"blocked"`, `AdminSetting.community_chat_id`.
**Изменения состояния:** Внешнее: пользователь удаляется из Telegram-чата. Внутреннее: нет.
**Реализует:** Новый метод или расширение `services/subscription.py::expire_subscription`; добавить вызов `bot.ban_chat_member(chat_id, user.telegram_id)` + немедленный `bot.unban_chat_member` (для «мягкого» кика без перманентного бана). Хранение ссылки: `handlers/admin.py` (добавить FSM-шаг для сохранения invite link).
**Модели:** `AdminSetting` (keys: `community_chat_id`, `community_invite_link`)
**Edge cases:**
- EC1: `community_chat_id` не настроен — пропустить кик, залогировать предупреждение.
- EC2: Бот не является администратором чата — `TelegramForbiddenError`; поймать, алертировать администратора.
- EC3: Пользователь уже покинул чат сам — `ban_chat_member` вернёт ошибку; поглотить исключение.
- EC4: Пользователь продлил подписку сразу после кика — нужно повторно отправить invite link; в `create_subscription` добавить отправку ссылки.
**Приоритет:** P1

---

### FR-017: Глобальный прогресс-бар «10 000 завтраков в месяц»
**Источник:** PR 6.2
**Описание:** В профиле или отдельном разделе TWA отображается общий счётчик одобренных фото-завтраков за текущий месяц и прогресс-бар к цели 10 000. Виджет обновляется в реальном времени или при каждом заходе.
**Входные данные:** `SELECT COUNT(*) FROM daily_photos WHERE status='approved' AND uploaded_at >= month_start`.
**Изменения состояния:** Только чтение.
**Реализует:** Новый endpoint или расширение `services/quests.py`; `handlers/social.py` или TWA-маршрут.
**Модели:** `DailyPhoto`
**Edge cases:**
- EC1: Цель достигнута — показать «Цель выполнена!»; сбросить счётчик в начале следующего месяца.
- EC2: Пустой месяц (старт продукта) — счётчик = 0; прогресс-бар = 0 %.
- EC3: Фото отклонено после одобрения (административная правка) — `status` меняется; счётчик уменьшается; нужна атомарная операция обновления.
**Приоритет:** P2

---

### FR-018: Массовая рассылка и выбор фракции при достижении 300 пользователей
**Источник:** PR 6.3
**Описание:** Когда общее количество пользователей в таблице `users` достигает 300 (триггер срабатывает один раз), бот отправляет массовую рассылку всем активным подписчикам с призывом выбрать фракцию. Пользователь выбирает фракцию через inline-кнопки.
**Входные данные:** `SELECT COUNT(*) FROM users >= 300`, `AdminSetting.faction_trigger_fired IS NULL`.
**Изменения состояния:** `AdminSetting(key="faction_trigger_fired", value="1")`, `UserFaction(user_id, faction_id)`.
**Реализует:** `scheduler/tasks.py::_check_faction_trigger` (каждые 1 ч), `handlers/social.py::cb_faction_select`, `handlers/social.py::cb_join_faction`
**Модели:** `User`, `AdminSetting`, `Faction`, `UserFaction`
**Edge cases:**
- EC1: Фракции не созданы в таблице `Faction` — `cb_faction_select` показывает «Фракции пока не созданы»; необходимо заранее заполнить таблицу через `admin.py` или сидинг.
- EC2: Пользователь уже в фракции — повторный вход показывает текущую фракцию; смена запрещена.
- EC3: Рассылка блокируется из-за flood control Telegram (30 сообщений/с) — добавить `asyncio.sleep(0.05)` между отправками.
- EC4: Триггер уже сработал, но `AdminSetting` удалена администратором — рассылка произойдёт повторно; необходима дополнительная проверка.
**Приоритет:** P1

---

## 7. Лотерея

### FR-019: Лотерейные билеты с UUID
**Источник:** PR 7.1
**Описание:** Каждый лотерейный билет хранится в `LotteryTicket` с уникальным UUID4 в поле `ticket_number`. Пользователь может просмотреть список своих билетов текущего месяца через `/lottery`.
**Входные данные:** Выдача билета: вызов `services/lottery.py::issue_ticket`. Просмотр: `/lottery`.
**Изменения состояния:** `LotteryTicket(user_id, ticket_number=uuid4, lottery_month=YYYY-MM)`.
**Реализует:** `services/lottery.py::issue_ticket`, `services/lottery.py::get_user_tickets`, `handlers/lottery.py::cmd_lottery`
**Модели:** `LotteryTicket`
**Edge cases:**
- EC1: UUID коллизия — вероятность пренебрежимо мала, но `ticket_number` имеет `unique=True`; при коллизии `commit` вызовет `IntegrityError`; добавить retry с новым UUID.
- EC2: Пользователь не имеет билетов — показать «У тебя пока нет билетов».
- EC3: Очень много билетов у одного пользователя — добавить пагинацию или ограничение вывода.
**Приоритет:** P1

---

### FR-020: Анимация розыгрыша в TWA
**Источник:** PR 7.2
**Описание:** В TWA-интерфейсе воспроизводится анимация розыгрыша (JS/CSS или Lottie-анимация) в момент запуска розыгрыша. По завершении анимации отображаются имена победителей.
**Входные данные:** Дата последнего дня месяца 20:00 UTC (триггер `_monthly_lottery`).
**Изменения состояния:** Только UI; данные предоставляет `services/lottery.py::run_monthly_drawing`.
**Реализует:** TWA frontend (не реализован); бэкенд: `scheduler/tasks.py::_monthly_lottery`, `services/lottery.py::run_monthly_drawing`.
**Модели:** `LotteryTicket`
**Edge cases:**
- EC1: TWA не открыта в момент розыгрыша — пользователь видит результаты позже при следующем заходе.
- EC2: Нет билетов в текущем месяце — `run_monthly_drawing` возвращает `[]`; TWA показывает «Билетов нет».
**Приоритет:** P2

---

### FR-021: Публичный отчёт победителей в канал
**Источник:** PR 7.3
**Описание:** После проведения розыгрыша бот публикует в Telegram-канал (channel_id из `AdminSetting`) сообщение с именами победителей, номерами билетов (первые 8 символов UUID) и размером приза.
**Входные данные:** `winners: list[LotteryTicket]`, `prize_fund: float`, `channel_id: str` из `AdminSetting(key="lottery_channel_id")`.
**Изменения состояния:** Публикация сообщения в канал; `LotteryTicket.is_winner = True`.
**Реализует:** `services/lottery.py::run_monthly_drawing`, `scheduler/tasks.py::_monthly_lottery`
**Модели:** `LotteryTicket`, `AdminSetting`
**Edge cases:**
- EC1: `lottery_channel_id` не задан — розыгрыш проходит, но сообщение не публикуется; `logger.warning`.
- EC2: Бот не является участником/администратором канала — `TelegramForbiddenError`; поглотить, залогировать.
- EC3: Победитель удалил Telegram-аккаунт — `username = None`; в отчёте отображается `"ID {user_id}"`.
- EC4: Приз делится на трёх победителей с нецелым результатом — `round(prize_fund / 3, 2)`; возможна погрешность 1 копейка; приемлемо для отображения.
**Приоритет:** P1

---

## 8. Реферальная система

### FR-022: Deep link с реферальным кодом
**Источник:** PR 8.1
**Описание:** При регистрации через ссылку `t.me/{bot}?start=refXXXXXXXX` параметр `refXXXXXXXX` извлекается из `/start`. Код используется для поиска реферера; создаётся запись `Referral(referrer_id, referred_id)`, реферер получает 50 SC.
**Входные данные:** `message.text` содержит `"refCODE"` как второй токен.
**Изменения состояния:** `Referral(referrer_id=referrer.id, referred_id=new_user.id)`, `User.sc_balance += 50` (реферер), `SCTransaction(+50, "реферальный бонус")`.
**Реализует:** `handlers/start.py::cmd_start`, `services/referral.py::process_referral`
**Модели:** `User`, `Referral`, `SCTransaction`
**Edge cases:**
- EC1: Код не существует — `process_referral` возвращает `False`; регистрация проходит без реферала.
- EC2: Уже зарегистрированный пользователь переходит по реферальной ссылке — `/start` показывает главное меню; `existing_user != None`; `process_referral` не вызывается.
- EC3: Самореферал — `referrer.id == new_user.id`; проверка в `process_referral` блокирует.
- EC4: Один пользователь пытается иметь двух рефереров — `Referral.referred_id` имеет `unique=True`; второй `INSERT` вызовет `IntegrityError`.
**Приоритет:** P0

---

### FR-023: Счётчик активных друзей
**Источник:** PR 8.2
**Описание:** В разделе `/referral` отображается счётчик активных рефералов пользователя — только те из приглашённых, у кого в данный момент активная подписка (`is_subscribed = True`).
**Входные данные:** `Referral.referrer_id = user.id`, `User.is_subscribed = True`.
**Изменения состояния:** Только чтение.
**Реализует:** `services/referral.py::count_active_friends`, `handlers/referral.py::cmd_referral`
**Модели:** `Referral`, `User`
**Edge cases:**
- EC1: Реферал отписался — его статус `is_subscribed = False`; он исключается из счётчика немедленно после экспирации.
- EC2: Большое число рефералов (1000+) — `SELECT User WHERE id IN (...)` может быть медленным; оптимизировать через JOIN с индексом.
**Приоритет:** P1

---

### FR-024: Бесплатная подписка за 10 активных друзей (Ambassador)
**Источник:** PR 8.3  
**Обновлено:** 2026-04-15 (PRD v1.1 — функция полностью реализована: кнопка `pay_ambassador`, сброс флага, `create_subscription(price=0)`)
**Описание:** Когда у пользователя 10 и более активных рефералов, он получает статус Амбассадора. Пользователь видит кнопку «Активировать бесплатную подписку» (`pay_ambassador`) на экране оплаты. По нажатию: проверяется флаг амбассадора, флаг сбрасывается (одноразовый), вызывается `create_subscription(price=0)` — подписка создаётся без выставления инвойса Telegram Payments.
**Входные данные:** `count_active_friends >= 10`; callback `pay_ambassador`.
**Изменения состояния:**
- `AdminSetting(key="ambassador_{user_id}", value="1")` — устанавливается при достижении порога 10 активных рефералов
- По нажатию `pay_ambassador`: флаг `ambassador_{user_id}` сбрасывается (удаляется или `value="0"`), вызывается `services/subscription.py::create_subscription(session, user, price=0)`, `Subscription.price_paid = 0`, `User.is_subscribed = True`
**Реализует:** `services/referral.py::check_ambassador`, `handlers/referral.py::cmd_referral`, `keyboards/subscription.py` (кнопка `pay_ambassador`), `handlers/subscription.py::cb_pay_ambassador` (callback `pay_ambassador`: проверяет флаг, сбрасывает, вызывает `create_subscription(price=0)`), `services/subscription.py::create_subscription`
**Модели:** `AdminSetting`, `Referral`, `User`, `Subscription`
**Edge cases:**
- EC1: Пользователь был Амбассадором, но один из рефералов отписался (стало 9) — статус должен быть отозван на следующий период; текущая реализация не предусматривает отзыва флага при потере рефералов.
- EC2: Бесплатная подписка — разовая: флаг сбрасывается сразу после активации; следующее продление будет по стандартной цене.
- EC3: Два пользователя одновременно достигают порога 10 — нет конкурентного конфликта; каждый проверяется независимо.
- EC4: Пользователь нажимает `pay_ambassador`, но флаг уже сброшен (двойное нажатие или повторная попытка) — callback обнаруживает отсутствие флага и возвращает «Бесплатная подписка уже использована».
- EC5: Кнопка `pay_ambassador` отображается только при наличии флага `ambassador_{user_id} == "1"` в `AdminSetting`; при отсутствии флага кнопка скрыта.
**Приоритет:** P1 → **реализовано**

---

## 9. Антифрод и аналитика

### FR-025: Контрольные фото (антифрод)
**Источник:** PR 9.1  
**Обновлено:** 2026-04-15 (PRD v1.1 — реализована `apply_control_photo_penalty`; `submit_p2p_vote` возвращает `ControlPhoto`; хендлеры отправляют фото рецензенту)
**Описание:** Администратор загружает «фейковые» фото (не завтраки) через панель `/admin`. С вероятностью 20 % рецензент получает контрольное фото вместо реального. Хендлер `cb_p2p_approve` / `cb_p2p_reject` получает третий элемент из кортежа `submit_p2p_vote` и, если это `ControlPhoto`, отправляет фото рецензенту (как «результат проверки»). Если рецензент одобрил фейк — вызывается `apply_control_photo_penalty`: штраф `-100 XP`, `trust_rating -= 10`.
**Входные данные:** `ControlPhoto.is_fake = True`, `maybe_inject_control_photo` (вероятность 20 %).
**Изменения состояния:**
- `submit_p2p_vote` возвращает `(bool, str, ControlPhoto | None)` — `ControlPhoto` присутствует в третьем элементе, если голосование пришлось на контрольное фото
- При одобрении фейка: вызывается `services/quests.py::apply_control_photo_penalty(session, reviewer)`:
  - `User.xp -= 100`
  - `User.trust_rating = max(0, trust_rating - 10)`
- Хендлер отправляет рецензенту уведомление: штраф (при одобрении фейка) или благодарность (при отклонении фейка)
**Реализует:** `handlers/admin.py::cb_admin_control_photo`, `handlers/admin.py::handle_control_photo`, `services/quests.py::maybe_inject_control_photo`, `services/quests.py::submit_p2p_vote` (возвращает `tuple[bool, str, ControlPhoto | None]`), `services/quests.py::apply_control_photo_penalty`, `handlers/quests.py::cb_p2p_approve` и `handlers/quests.py::cb_p2p_reject` (обрабатывают `ControlPhoto` из третьего элемента кортежа, отправляют фото рецензенту)
**Модели:** `ControlPhoto`, `User`
**Edge cases:**
- EC1: Таблица `ControlPhoto` пустая — `maybe_inject_control_photo` вернёт `None`; инъекции нет; `submit_p2p_vote` вернёт `(result, msg, None)`.
- EC2: Рецензент с низким `trust_rating` продолжает получать контрольные фото — можно повысить вероятность инъекции для недобросовестных рецензентов.
- EC3: `trust_rating` уходит в минус при повторных штрафах — `apply_control_photo_penalty` использует `max(0, trust_rating - 10)`.
- EC4: Рецензент отклоняет фейк — правильное поведение; `apply_control_photo_penalty` не вызывается; хендлер отправляет благодарность; можно добавить небольшой бонус доверия.
- EC5: Рецензент не голосует (timeout по контрольному фото) — нет механизма таймаута для голосования; необходим срок истечения P2P-задания.
- EC6: `User.xp` уходит в минус после штрафа — поведение при `xp < 0` не определено (downgrade уровня?); открытый вопрос (см. п. 8 раздела «Неопределённости»).
**Приоритет:** P1 → **частично реализовано** (`apply_control_photo_penalty` готова; таймаут голосования отсутствует)

---

### FR-026: Аналитический дашборд (DAU/WAU/MAU/LTV/Churn/SC)
**Источник:** PR 9.2
**Описание:** В панели `/admin` доступен экран статистики с метриками: DAU (зарегистрировано за 24 ч), WAU (7 дней), MAU (30 дней), LTV (среднее суммарное `price_paid` на пользователя), Churn (пользователи с `subscription.status=expired` за период), суммарный SC в обращении.
**Входные данные:** Таблицы `User`, `Subscription`, `SCTransaction`.
**Изменения состояния:** Только чтение.
**Реализует:** `handlers/admin.py::cb_admin_stats` (расширить: добавить LTV, Churn, суммарный SC в обращении), новые аналитические функции в `services/`.
**Модели:** `User`, `Subscription`, `SCTransaction`
**Edge cases:**
- EC1: DAU/WAU/MAU считаются по `created_at` (дата регистрации), а не по реальной активности — требуется добавить поле `User.last_active_at` и обновлять его в `middlewares/auth.py`.
- EC2: LTV = 0 для новых пользователей без платежей — деление на ноль при пустой выборке; использовать `COALESCE(..., 0)`.
- EC3: Churn = пользователи, чья подписка истекла и не возобновилась за N дней; точная формула требует согласования с продуктом.
- EC4: Суммарный SC в обращении = `SUM(sc_balance) WHERE is_subscribed=True`; считать из `User.sc_balance`.
**Приоритет:** P1

---

### FR-027: Content Manager — PDF гайды и планирование квизов на неделю вперёд
**Источник:** PR 9.3
**Описание:** Администратор (или выделенный контент-менеджер) может загружать PDF-гайды и создавать вопросы квиза с указанием даты публикации. Интерфейс позволяет планировать контент минимум на 7 дней вперёд.
**Входные данные:**
- Квиз: FSM-диалог в `handlers/admin.py` (4 шага: вопрос, 4 варианта, правильный индекс, дата).
- Гайды: загрузка PDF-документа; сохранение `file_id` в `BattlePassLevel.reward_description` или новую таблицу `Guide`.
**Изменения состояния:** `QuizQuestion(question, _options JSON, correct_index, scheduled_date)`, `BattlePassLevel.reward_description` (ссылка или file_id PDF).
**Реализует:** `handlers/admin.py` (квиз — полностью реализован; гайды — требуется добавить FSM-шаг для загрузки PDF), `services/quests.py::get_todays_quiz`
**Модели:** `QuizQuestion`, `BattlePassLevel`
**Edge cases:**
- EC1: Дата квиза в прошлом — вопрос сразу доступен; добавить предупреждение администратору.
- EC2: Два вопроса на одну дату — `get_todays_quiz` может вернуть неопределённый результат; необходима уникальная constraints на `scheduled_date` или `order_by(id).limit(1)`.
- EC3: PDF-файл > 50 МБ — Telegram Bot API не принимает файлы > 50 МБ; необходима внешняя CDN или ограничение на загрузку.
- EC4: Контент-менеджер не является `ADMIN_IDS` — нужна роль с ограниченным доступом; сейчас все операции проверяют принадлежность к `ADMIN_IDS`; потребуется расширение модели ролей.
- EC5: Квиз заканчивается, когда контент не запланирован — показывается заглушка «Вопрос ещё не добавлен»; добавить алерт администратору за 2 дня до пропуска.
**Приоритет:** P1

---

## Неопределённости и вопросы к продукту

1. **PR 1.1 — механизм рекуррентного списания:** Telegram Bot API не поддерживает автоматическое списание без участия пользователя. Каким образом реализовать авторекуррент: через сторонний эквайринг (ЮKassa, Stripe) с сохранённой картой, через Telegram Stars или иным способом? Необходимо решение до начала разработки FR-001.

2. **PR 1.2 / PR 5.1 / PR 7.2 — TWA-фронтенд:** Технический стек TWA (React, Vue, vanilla JS)? Где размещается TWA (отдельный домен, GitHub Pages)? Нужен ли REST API или достаточно Telegram Mini App `web_app_data`?

3. **PR 2.3 — дедупликация предупреждений об SC:** Нужен ли флаг `sc_burn_warned` в модели `User`, чтобы не спамить пользователю раз в час одним и тем же предупреждением при каждом прогоне планировщика?

4. ~~**PR 4.1 — EXIF отсутствует:**~~ Закрыт 2026-04-13 (H-05): принимать с предупреждением, порог P2P повышен до 4/5.

5. **PR 4.2 — порог одобрения и отклонения P2P:** ~~Сколько одобрений нужно?~~ Уточнено PRD v1.1 (2026-04-15): **порог одобрения — 3/5 с EXIF, 4/5 без EXIF**. Порог **отклонения** (`reject_count >= N → status="rejected"`) по-прежнему не определён. Текущая реализация не устанавливает статус `rejected` при избытке reject-голосов.

6. **PR 6.1 — тип кика из сообщества:** «Мягкий» кик (ban + немедленный unban, пользователь может вернуться по новой ссылке) или перманентный бан? Как доставлять новую invite link при повторной подписке?

7. **PR 8.3 — Ambassador: одноразовый или постоянный статус:** ~~Открыт.~~ Закрыт PRD v1.1 (2026-04-15): бесплатная подписка — **одноразовая**; флаг `ambassador_{user_id}` сбрасывается после активации кнопки `pay_ambassador`. Следующее продление — по стандартной цене, даже если 10+ рефералов остаются активными.

8. **PR 9.1 — штраф XP:** Минусовой XP уменьшает `User.xp`. Может ли `xp` уходить в минус? Может ли это привести к понижению уровня? Текущая логика `add_xp` не предусматривает downgrade.

9. **PR 9.2 — определения метрик DAU/WAU/MAU:** Это новые регистрации или уникальные активные пользователи? Требует добавления `User.last_active_at` и обновления в `middlewares/auth.py`.

10. **PR 6.2 — сброс глобального счётчика завтраков:** Счётчик сбрасывается 1-го числа каждого месяца автоматически (фильтрация по `uploaded_at >= month_start`) или хранится отдельно как нарастающий итог?

11. **PR 3.1 — количество PNG-рамок аватара:** Сколько уникальных рамок планируется: по одной на каждый уровень 1–50, по ветке, по фракции? Нужен ли pipeline для автогенерации рамок?

12. **PR 7.2 — синхронизация TWA с моментом розыгрыша:** Как TWA узнаёт о завершении розыгрыша в реальном времени (WebSocket, webhook, polling)?

---

## Архитектура взаимодействия (Agent/Workflow паттерны)

### Workflow 1: Renewal Retry (рекуррентное продление)
```
[APScheduler, каждые 6 ч]
  → scheduler/tasks.py::_retry_subscriptions(bot)
    → services/subscription.py::check_and_expire_subscriptions(session)
        SELECT User WHERE subscription_end < now AND is_subscribed=True
        → services/subscription.py::expire_subscription(session, user)
            UPDATE Subscription.status = 'expired'
            UPDATE User.is_subscribed = False
    → services/subscription.py::retry_failed_subscriptions(session, bot)
        SELECT Subscription WHERE status='failed' AND attempts<3 AND last_attempt<now-24h
        FOR EACH sub:
          sub.renewal_attempts += 1
          IF attempts >= 3:
            sub.status = 'blocked'
            User.subscription_blocked = True
            bot.send_message(user, "заблокирована")
          ELSE:
            bot.send_message(user, "попытка N/3, оплатите")
```

### Workflow 2: SC Burn (сжигание монет)
```
[APScheduler, каждые 1 ч]
  → scheduler/tasks.py::_burn_expired_coins(bot)
    → services/coins.py::get_users_to_warn_burn(session)
        SELECT User WHERE is_subscribed=False
          AND subscription_end < now-144h AND sc_balance>0
        FOR EACH user:
          → services/notifications.py::notify_sc_burn_warning(bot, user)
              bot.send_message(user, "SC сгорят через 24ч")
    → services/coins.py::burn_expired_coins(session, bot)
        SELECT User WHERE is_subscribed=False
          AND subscription_end < now-168h AND sc_balance>0
        FOR EACH user:
          burned = user.sc_balance
          INSERT SCTransaction(amount=-burned, description="сгорели")
          UPDATE User.sc_balance = 0
          bot.send_message(user, "SC сгорели")
```

### Workflow 3: Breakfast Photo Quest (квест с фото завтрака)
```
User → /quest → handlers/quests.py::cmd_quest
  → [FSM: QuestStates.waiting_photo]
  → User отправляет фото
  → handlers/quests.py::handle_breakfast_photo(message, bot, session, user)
      bot.download_file → bytes
      → services/quests.py::validate_exif(bytes) → datetime | None
      → services/quests.py::submit_breakfast_photo(session, user, file_id, taken_at)
          CHECK DailyPhoto WHERE user_id AND uploaded_at >= today → duplicate check
          IF taken_at is not None AND age > 24h → reject, message "фото старое"
          IF taken_at is not None AND age ≤ 24h → принять, p2p_threshold = P2P_APPROVALS_NEEDED (3)
          IF taken_at is None              → принять с предупреждением, p2p_threshold = P2P_APPROVALS_NEEDED_NO_EXIF (4)
          INSERT DailyPhoto(status='p2p_pending', photo_taken_at=taken_at)
          → services/quests.py::assign_p2p_reviewers(session, photo)
              SELECT User WHERE is_subscribed=True AND id NOT IN already_reviewing
              random.sample(candidates, min(5, len))
              FOR reviewer: bot.send_photo(reviewer, photo, p2p_vote_kb)
          RETURN (True, contextual_message)  ← handler displays msg directly
      message = контекстное сообщение из сервиса (с EXIF или с предупреждением)

Reviewer → p2p_approve:{photo_id} → handlers/quests.py::cb_p2p_approve
  → services/quests.py::submit_p2p_vote(session, reviewer, photo_id, is_approved=True)
      CHECK P2PReview duplicate → UniqueConstraint
      INSERT P2PReview
      UPDATE DailyPhoto.p2p_approve_count += 1
      threshold = P2P_APPROVALS_NEEDED_NO_EXIF (4) if photo.photo_taken_at is None
               else P2P_APPROVALS_NEEDED (3)
      IF approve_count >= threshold AND status='p2p_pending':
        UPDATE DailyPhoto.status = 'approved'
        → services/battle_pass.py::add_xp(session, uploader, XP_BREAKFAST_PHOTO)
            UPDATE User.xp += amount
            CHECK level thresholds → possible level-up
            IF leveled_up: INSERT UserReward(claimed=False)
      → services/quests.py::maybe_inject_control_photo(session, reviewer)
          IF random() <= 0.20: SELECT ControlPhoto ORDER BY random() LIMIT 1
          [показать контрольное фото как отдельное P2P-задание]
```

### Workflow 4: Monthly Lottery Drawing (ежемесячный розыгрыш)
```
[APScheduler, cron: последний день месяца 20:00 UTC]
  → scheduler/tasks.py::_monthly_lottery(bot)
      SELECT AdminSetting WHERE key='lottery_channel_id'
      → services/lottery.py::run_monthly_drawing(session, bot, channel_id)
          SELECT LotteryTicket WHERE lottery_month=current AND is_winner=False
          winners = random.sample(all_tickets, min(3, len))
          prize = get_monthly_fund(session) / len(winners)
          FOR winner_ticket:
            UPDATE LotteryTicket.is_winner = True
            SELECT User → display name
          await session.commit()
          bot.send_message(channel_id, отчёт_с_победителями)
          FOR winner:
            services/notifications.py::notify_winner(bot, user, ticket)
```

### Workflow 5: Payment with SC (частичная оплата SC)
```
User → "Использовать SC" → handlers/subscription.py::cb_pay_with_sc
    price = services/subscription.py::get_subscription_price(session)
    max_sc = int(price * 0.5)
    sc_to_use = min(user.sc_balance, max_sc)
    remaining = price - sc_to_use
    show confirmation screen

User → "Подтвердить" → handlers/subscription.py::cb_confirm_sc
    bot.answer_invoice(remaining_kopecks, payload="subscription:sc:{user_id}:{sc_to_use}")

Telegram → successful_payment → handlers/subscription.py::handle_successful_payment
    sc_used = parse from payload
    → services/subscription.py::create_subscription(session, user, price_paid, sc_used, payment_id)
        INSERT Subscription(status='active', end_date=now+30d, sc_paid=sc_used)
        UPDATE User.is_subscribed=True, subscription_end=now+30d
    [SC deduction происходит здесь — до или после payment_id получения — уточнить порядок]
    message "Подписка активирована"
```

### Workflow 6: Faction Trigger (выбор фракции при 300 пользователях)
```
[APScheduler, каждые 1 ч]
  → scheduler/tasks.py::_check_faction_trigger(bot)
      SELECT AdminSetting WHERE key='faction_trigger_fired' → IF exists: return
      SELECT COUNT(User.id) → total
      IF total >= 300:
        INSERT AdminSetting(key='faction_trigger_fired', value='1')
        SELECT User WHERE is_subscribed=True
        FOR user (с throttle asyncio.sleep(0.05)):
          bot.send_message(user, "Нас 300! Выбери фракцию!")

User → faction_select → handlers/social.py::cb_faction_select
    CHECK user.faction IS NULL
    SELECT Faction ORDER BY id
    show factions inline-keyboard

User → join_faction_{id} → handlers/social.py::cb_join_faction
    SELECT Faction WHERE id=faction_id
    CHECK user.faction IS NULL
    INSERT UserFaction(user_id, faction_id)
    message "Ты в фракции X"
```

### Workflow 7: Referral & Ambassador (реферальная программа)
```
New user → /start refCODE → handlers/start.py::cmd_start
    INSERT User(referral_code=random_8char)
    → services/referral.py::process_referral(session, new_user, referral_code)
        SELECT User WHERE referral_code=code → referrer
        CHECK referrer.id != new_user.id
        CHECK Referral WHERE referred_id=new_user.id → must be None
        INSERT Referral(referrer_id, referred_id)
        → services/coins.py::add_sc(session, referrer, 50, "реферальный бонус")
            UPDATE User.sc_balance += 50
            INSERT SCTransaction(+50)

[По запросу /referral или при каждой подписке реферала]
  → services/referral.py::check_ambassador(session, user)
      → count_active_friends(session, user.id)
          SELECT Referral WHERE referrer_id=user.id
          SELECT User WHERE id IN referred_ids AND is_subscribed=True → count
      IF count >= 10:
        INSERT AdminSetting(key='ambassador_{user_id}', value='1')
        [при следующем renewal: subscription_price = 0 для этого пользователя]
```

### Workflow 8: Control Photo Anti-Fraud (антифрод контрольными фото)
```
Admin → /admin → "Загрузить анти-фрод фото"
  → handlers/admin.py::handle_control_photo(message, session)
      INSERT ControlPhoto(photo_file_id, is_fake=True, added_by_admin=tg_id)

[После каждого P2P-голосования, вероятность 20%]
  → services/quests.py::maybe_inject_control_photo(session, reviewer)
      IF random() > 0.20: return None
      SELECT ControlPhoto ORDER BY random() LIMIT 1 → control_photo
      [caller показывает control_photo рецензенту как P2P-задание]

Reviewer одобряет control_photo (is_fake=True):
  → [TODO в submit_p2p_vote: detect ControlPhoto by id]
      IF photo.status == 'control' AND is_approved:
        UPDATE User.trust_rating = max(0, trust_rating - 10)
        → services/battle_pass.py::add_xp(session, reviewer, -100, "штраф за одобрение фейка")
```

### Workflow 9: Battle Pass Level-Up & Infinite Loop
```
[Любое событие, дающее XP]
  → services/battle_pass.py::add_xp(session, user, xp_amount, description)
      UPDATE User.xp += xp_amount
      thresholds = get_level_thresholds(session)  # из BattlePassLevel или дефолт

      # Уровни 1-50
      FOR lvl in range(old_level+1, 51):
        IF user.xp >= thresholds[lvl]: new_level = lvl
      IF new_level > old_level:
        INSERT UserReward(level=lvl, claimed=False) FOR каждый новый уровень
        UPDATE User.level = new_level
        → services/notifications.py::notify_level_up(bot, user, new_level)

      # После уровня 50: Infinite Loop
      IF user.xp >= thresholds[50]:
        extra_xp = user.xp - thresholds[50]
        n = extra_xp // 1000  # BP_INFINITE_BONUS_XP
        FOR synthetic_level IN range(51, 51+n):
          IF NOT EXISTS UserReward(user_id, synthetic_level):
            INSERT UserReward(level=synthetic_level, claimed=False)

User → /battlepass → handlers/battle_pass.py::cmd_battlepass
    summary = get_progress_summary(session, user)
    claimable = get_claimable_rewards(session, user.id)
    show progress bar + "Забрать" buttons

User → claim_reward_{level} → handlers/battle_pass.py::cb_claim_reward
    → services/battle_pass.py::claim_reward(session, user, level)
        UserReward.claimed = True, claimed_at = now
        IF reward_type='sc': add_sc(...)
        IF reward_type='ticket': issue_ticket(...)
        IF reward_type='guide': return description text
        IF bp_level IS None (infinite): issue_ticket(...)
```
