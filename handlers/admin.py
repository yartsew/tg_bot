"""
handlers/admin.py — /admin panel (restricted to ADMIN_IDS).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, PhotoSize
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from database.models import AdminSetting, ControlPhoto, QuizQuestion, Subscription, User
from keyboards.admin import admin_menu_kb, confirm_kb, settings_kb
from states.forms import AdminStates

router = Router()


# ---------------------------------------------------------------------------
# Helper — access-control guard
# ---------------------------------------------------------------------------

def _is_admin(telegram_id: int) -> bool:
    return telegram_id in config.ADMIN_IDS


# ---------------------------------------------------------------------------
# /admin — show admin panel
# ---------------------------------------------------------------------------

@router.message(Command("admin"))
async def cmd_admin(
    message: Message,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    await state.clear()

    if not is_admin:
        await message.answer("⛔ Доступ запрещён.")
        return

    await message.answer(
        "🛠 <b>Панель администратора</b>\n\n"
        "Кулинарный Синдикат — управление:",
        reply_markup=admin_menu_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# admin_stats — DAU / WAU / MAU + subscription count
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(
    callback: CallbackQuery,
    session: AsyncSession,
    is_admin: bool,
    **data,
) -> None:
    await callback.answer()

    if not is_admin:
        await callback.message.answer("⛔ Доступ запрещён.")
        return

    now = datetime.utcnow()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # DAU / WAU / MAU by created_at (users who registered in period)
    dau_result = await session.execute(
        select(func.count(User.id)).where(User.created_at >= day_ago)
    )
    dau = dau_result.scalar_one()

    wau_result = await session.execute(
        select(func.count(User.id)).where(User.created_at >= week_ago)
    )
    wau = wau_result.scalar_one()

    mau_result = await session.execute(
        select(func.count(User.id)).where(User.created_at >= month_ago)
    )
    mau = mau_result.scalar_one()

    total_users_result = await session.execute(select(func.count(User.id)))
    total_users = total_users_result.scalar_one()

    # Active subscriptions
    active_subs_result = await session.execute(
        select(func.count(Subscription.id)).where(
            Subscription.status == "active",
            Subscription.end_date >= now,
        )
    )
    active_subs = active_subs_result.scalar_one()

    text = (
        f"📊 <b>Статистика Синдиката</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users}</b>\n\n"
        f"📈 Новые за 24ч (DAU): <b>{dau}</b>\n"
        f"📈 Новые за 7 дней (WAU): <b>{wau}</b>\n"
        f"📈 Новые за 30 дней (MAU): <b>{mau}</b>\n\n"
        f"💳 Активных подписок: <b>{active_subs}</b>"
    )

    await callback.message.edit_text(text, reply_markup=admin_menu_kb(), parse_mode="HTML")


# ---------------------------------------------------------------------------
# admin_settings — show settings sub-menu
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin_settings")
async def cb_admin_settings(
    callback: CallbackQuery,
    is_admin: bool,
    **data,
) -> None:
    await callback.answer()

    if not is_admin:
        await callback.message.answer("⛔ Доступ запрещён.")
        return

    await callback.message.edit_text(
        "⚙️ <b>Настройки</b>",
        reply_markup=settings_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# set_price — ask for new subscription price
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "set_price")
async def cb_set_price(
    callback: CallbackQuery,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    await callback.answer()

    if not is_admin:
        await callback.message.answer("⛔ Доступ запрещён.")
        return

    await state.set_state(AdminStates.waiting_subscription_price)
    await callback.message.edit_text(
        "💰 Введи новую цену подписки (в рублях, число):\n"
        "Например: <code>399</code>",
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_subscription_price)
async def handle_new_price(
    message: Message,
    session: AsyncSession,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    if not is_admin:
        await state.clear()
        return

    try:
        new_price = float(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("❌ Неверный формат. Введи число, например: <code>399</code>", parse_mode="HTML")
        return

    # Upsert AdminSetting
    result = await session.execute(
        select(AdminSetting).where(AdminSetting.key == "subscription_price")
    )
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = str(new_price)
    else:
        session.add(AdminSetting(key="subscription_price", value=str(new_price)))

    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ Цена подписки обновлена: <b>{new_price:.0f}₽</b>",
        reply_markup=admin_menu_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# set_fund_percent — ask for new prize fund percent
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "set_fund_percent")
async def cb_set_fund_percent(
    callback: CallbackQuery,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    await callback.answer()

    if not is_admin:
        await callback.message.answer("⛔ Доступ запрещён.")
        return

    await state.set_state(AdminStates.waiting_setting_value)
    await state.update_data(setting_key="prize_fund_percent")
    await callback.message.edit_text(
        "🏆 Введи процент в призовой фонд (0–100):\n"
        "Например: <code>30</code>",
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_setting_value)
async def handle_setting_value(
    message: Message,
    session: AsyncSession,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    if not is_admin:
        await state.clear()
        return

    fsm_data = await state.get_data()
    setting_key = fsm_data.get("setting_key", "unknown")

    try:
        new_value = float(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("❌ Неверный формат. Введи число.", parse_mode="HTML")
        return

    # Normalise fund percent to 0–1 range for storage
    if setting_key == "prize_fund_percent":
        stored_value = str(new_value / 100.0)
        display = f"{new_value:.0f}%"
    else:
        stored_value = str(new_value)
        display = str(new_value)

    result = await session.execute(select(AdminSetting).where(AdminSetting.key == setting_key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = stored_value
    else:
        session.add(AdminSetting(key=setting_key, value=stored_value))

    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ Настройка <b>{setting_key}</b> обновлена: <b>{display}</b>",
        reply_markup=admin_menu_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# admin_control_photo — ask admin to send a control photo
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin_control_photo")
async def cb_admin_control_photo(
    callback: CallbackQuery,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    await callback.answer()

    if not is_admin:
        await callback.message.answer("⛔ Доступ запрещён.")
        return

    await state.set_state(AdminStates.waiting_control_photo)
    await callback.message.edit_text(
        "🖼 <b>Загрузка анти-фрод фото</b>\n\n"
        "Отправь фото, которое НЕ является завтраком.\n"
        "Если пользователь одобрит его в P2P — получит штраф (-100 XP, -рейтинг доверия).",
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_control_photo, F.photo)
async def handle_control_photo(
    message: Message,
    session: AsyncSession,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    if not is_admin:
        await state.clear()
        return

    photo: PhotoSize = message.photo[-1]
    control = ControlPhoto(
        photo_file_id=photo.file_id,
        is_fake=True,
        added_by_admin=message.from_user.id,
    )
    session.add(control)
    await session.commit()
    await state.clear()

    await message.answer(
        "✅ Анти-фрод фото сохранено и будет случайно вставляться в P2P очереди.",
        reply_markup=admin_menu_kb(),
    )


@router.message(AdminStates.waiting_control_photo)
async def handle_non_photo_control(message: Message, state: FSMContext, **data) -> None:
    await message.answer("📸 Пожалуйста, отправь именно фото.")


# ---------------------------------------------------------------------------
# admin_broadcast — ask for broadcast text, send to all subscribed users
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(
    callback: CallbackQuery,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    await callback.answer()

    if not is_admin:
        await callback.message.answer("⛔ Доступ запрещён.")
        return

    await state.set_state(AdminStates.waiting_broadcast_text)
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\n"
        "Введи текст сообщения (поддерживается HTML).\n"
        "Будет отправлено всем пользователям с активной подпиской:",
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_broadcast_text)
async def handle_broadcast_text(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    if not is_admin:
        await state.clear()
        return

    broadcast_text = message.text or message.caption or ""
    if not broadcast_text:
        await message.answer("❌ Пустой текст. Введи сообщение для рассылки.")
        return

    await state.clear()

    # Fetch all subscribed, active users
    now = datetime.utcnow()
    result = await session.execute(
        select(User).where(
            User.is_subscribed.is_(True),
            User.is_active.is_(True),
            User.subscription_end >= now,
        )
    )
    users: list[User] = list(result.scalars().all())

    await message.answer(f"📤 Начинаю рассылку для <b>{len(users)}</b> пользователей…", parse_mode="HTML")

    sent_count = 0
    failed_count = 0
    for user in users:
        try:
            await bot.send_message(
                chat_id=user.telegram_id,
                text=broadcast_text,
                parse_mode="HTML",
            )
            sent_count += 1
        except Exception:
            failed_count += 1

    await message.answer(
        f"✅ Рассылка завершена.\n"
        f"Доставлено: <b>{sent_count}</b> | Ошибок: <b>{failed_count}</b>",
        reply_markup=admin_menu_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# admin_quiz — create a quiz question (multi-step FSM)
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin_quiz")
async def cb_admin_quiz(
    callback: CallbackQuery,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    await callback.answer()

    if not is_admin:
        await callback.message.answer("⛔ Доступ запрещён.")
        return

    await state.set_state(AdminStates.waiting_quiz_question)
    await state.update_data(quiz_correct_index=0)
    await callback.message.edit_text(
        "📝 <b>Создание квиза — Шаг 1/4</b>\n\n"
        "Введи текст вопроса:",
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_quiz_question)
async def handle_quiz_question(
    message: Message,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    if not is_admin:
        await state.clear()
        return

    await state.update_data(quiz_question=message.text)
    await state.set_state(AdminStates.waiting_quiz_options)
    await message.answer(
        "📝 <b>Создание квиза — Шаг 2/4</b>\n\n"
        "Введи варианты ответов через запятую (ровно 4):\n"
        "Например: <code>Овсянка, Яичница, Блины, Тост</code>",
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_quiz_options)
async def handle_quiz_options(
    message: Message,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    if not is_admin:
        await state.clear()
        return

    raw = message.text or ""
    options = [o.strip() for o in raw.split(",")]
    if len(options) != 4:
        await message.answer(
            "❌ Нужно ровно 4 варианта, разделённых запятой. Попробуй снова:"
        )
        return

    await state.update_data(quiz_options=options)
    await state.set_state(AdminStates.waiting_setting_key)  # reuse state for correct index
    await state.update_data(admin_step="quiz_correct_index")
    await message.answer(
        "📝 <b>Создание квиза — Шаг 3/4</b>\n\n"
        f"Варианты: {', '.join(f'{i+1}. {o}' for i, o in enumerate(options))}\n\n"
        "Введи номер правильного ответа (1–4):",
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_setting_key)
async def handle_quiz_correct_index(
    message: Message,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    if not is_admin:
        await state.clear()
        return

    fsm_data = await state.get_data()
    # If we're in the quiz correct-index step
    if fsm_data.get("admin_step") == "quiz_correct_index":
        try:
            index_1based = int(message.text.strip())
            if not (1 <= index_1based <= 4):
                raise ValueError
        except (ValueError, AttributeError):
            await message.answer("❌ Введи число от 1 до 4.")
            return

        await state.update_data(quiz_correct_index=index_1based - 1)
        await state.set_state(AdminStates.waiting_quiz_date)
        await state.update_data(admin_step=None)
        await message.answer(
            "📝 <b>Создание квиза — Шаг 4/4</b>\n\n"
            "Введи дату в формате YYYY-MM-DD (или <code>сегодня</code>):",
            parse_mode="HTML",
        )
    else:
        await message.answer("Неожиданное состояние. Начни заново через /admin.")
        await state.clear()


@router.message(AdminStates.waiting_quiz_date)
async def handle_quiz_date(
    message: Message,
    session: AsyncSession,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    if not is_admin:
        await state.clear()
        return

    raw_date = (message.text or "").strip()

    from datetime import date as date_type
    import re

    if raw_date.lower() in ("сегодня", "today"):
        scheduled_date = date_type.today()
    elif re.match(r"^\d{4}-\d{2}-\d{2}$", raw_date):
        try:
            scheduled_date = date_type.fromisoformat(raw_date)
        except ValueError:
            await message.answer("❌ Неверная дата. Формат: YYYY-MM-DD")
            return
    else:
        await message.answer("❌ Неверная дата. Формат: YYYY-MM-DD")
        return

    fsm_data = await state.get_data()
    question_text: str = fsm_data.get("quiz_question", "")
    options: list[str] = fsm_data.get("quiz_options", [])
    correct_index: int = fsm_data.get("quiz_correct_index", 0)

    quiz = QuizQuestion(
        question=question_text,
        correct_index=correct_index,
        scheduled_date=scheduled_date,
    )
    quiz.options = options  # uses the property setter → JSON
    session.add(quiz)
    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ <b>Квиз создан!</b>\n\n"
        f"Вопрос: {question_text}\n"
        f"Варианты: {', '.join(options)}\n"
        f"Правильный: <b>{options[correct_index]}</b>\n"
        f"Дата: <b>{scheduled_date}</b>",
        reply_markup=admin_menu_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# admin_back — return to admin menu from settings
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin_back")
async def cb_admin_back(
    callback: CallbackQuery,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    await callback.answer()
    await state.clear()

    if not is_admin:
        await callback.message.answer("⛔ Доступ запрещён.")
        return

    await callback.message.edit_text(
        "🛠 <b>Панель администратора</b>",
        reply_markup=admin_menu_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# admin_exit — dismiss admin panel
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin_exit")
async def cb_admin_exit(
    callback: CallbackQuery,
    is_admin: bool,
    state: FSMContext,
    **data,
) -> None:
    await callback.answer("Выход из панели.")
    await state.clear()
    await callback.message.edit_text("🛠 Панель администратора закрыта.")
