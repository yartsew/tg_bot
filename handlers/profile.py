"""
handlers/profile.py — /profile, branch choice (level 10), mentor code (level 50).
"""
from __future__ import annotations

import io

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from keyboards.profile import branch_kb, profile_kb
from services import avatar as avatar_service
from services import coins as coins_service

router = Router()

# Branch display labels
_BRANCH_LABELS = {
    "butcher": "🥩 Мясник",
    "vegan": "🥗 Веган",
}


# ---------------------------------------------------------------------------
# /profile — show profile card
# ---------------------------------------------------------------------------

@router.message(Command("profile"))
@router.message(F.text == "👤 Профиль")
async def cmd_profile(
    message: Message,
    user: User | None,
    **data,
) -> None:
    """Display the user's profile card."""
    if user is None:
        await message.answer("Сначала введи /start, чтобы зарегистрироваться.")
        return

    branch_label = _BRANCH_LABELS.get(user.branch, "не выбрана") if user.branch else "не выбрана"
    mentor_status = "✅ Наставник" if user.level >= 50 else "🔒 (уровень 50+)"

    text = (
        f"👤 <b>{user.first_name}</b>"
        + (f" (@{user.username})" if user.username else "")
        + f"\n\n"
        f"⭐ Уровень: <b>{user.level}</b>\n"
        f"✨ XP: <b>{user.xp}</b>\n"
        f"🪙 SC: <b>{user.sc_balance}</b>\n"
        f"🏅 Рейтинг доверия: <b>{user.trust_rating}/100</b>\n"
        f"🍴 Ветка: <b>{branch_label}</b>\n"
        f"🎓 Статус наставника: <b>{mentor_status}</b>"
    )

    # Force branch choice modal at level 10
    if user.level >= 10 and user.branch is None:
        text += (
            "\n\n⚠️ <b>Ты достиг уровня 10!</b>\n"
            "Выбери свою ветку Синдиката, чтобы продолжить:"
        )
        await message.answer(text, reply_markup=branch_kb(), parse_mode="HTML")
        return

    await message.answer(text, reply_markup=profile_kb(level=user.level, branch=user.branch), parse_mode="HTML")


# ---------------------------------------------------------------------------
# sc_history — show last 20 SC transactions
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "sc_history")
async def cb_sc_history(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    transactions = await coins_service.get_transactions(session, user.id)

    if not transactions:
        await callback.message.answer(
            "🪙 <b>История SC</b>\n\nТранзакций пока нет.",
            parse_mode="HTML",
        )
        return

    lines = []
    for tx in transactions:
        sign = "+" if tx.amount > 0 else ""
        date_str = tx.created_at.strftime("%d.%m %H:%M") if tx.created_at else "—"
        lines.append(f"{date_str}  {sign}{tx.amount} SC — {tx.description}")

    text = "🪙 <b>История SC</b> (последние 20)\n\n" + "\n".join(lines)
    await callback.message.answer(text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# choose_branch — show branch selection keyboard
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "choose_branch")
async def cb_choose_branch(
    callback: CallbackQuery,
    user: User | None,
    **data,
) -> None:
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    if user.level < 10:
        await callback.message.answer("Ветка открывается на уровне 10.")
        return

    await callback.message.edit_text(
        "🍴 <b>Выбор ветки Синдиката</b>\n\n"
        "🥩 <b>Мясник</b> — мастер белковых завтраков\n"
        "🥗 <b>Веган</b> — мастер растительного меню\n\n"
        "Выбор нельзя изменить. Реши осознанно:",
        reply_markup=branch_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# branch_butcher / branch_vegan — save chosen branch
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "branch_butcher")
async def cb_branch_butcher(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer()
    await _save_branch(callback, session, user, "butcher", "🥩 Мясник")


@router.callback_query(F.data == "branch_vegan")
async def cb_branch_vegan(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer()
    await _save_branch(callback, session, user, "vegan", "🥗 Веган")


async def _save_branch(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    branch: str,
    label: str,
) -> None:
    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    if user.branch is not None:
        await callback.message.edit_text(
            f"Ветка уже выбрана: <b>{_BRANCH_LABELS.get(user.branch, user.branch)}</b>",
            parse_mode="HTML",
        )
        return

    user.branch = branch
    await session.commit()
    await session.refresh(user)

    await callback.message.edit_text(
        f"✅ Ветка выбрана: <b>{label}</b>\n\n"
        f"Добро пожаловать в свою гильдию, {user.first_name}!",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# get_avatar — download Telegram photo, generate avatar, send back
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "get_avatar")
async def cb_get_avatar(
    callback: CallbackQuery,
    bot: Bot,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer("Генерирую аватар…")

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    # Fetch user's Telegram profile photos
    photos = await bot.get_user_profile_photos(user.telegram_id, limit=1)
    if not photos.total_count:
        await callback.message.answer(
            "😕 У тебя нет фото профиля в Telegram. "
            "Установи аватар и попробуй снова."
        )
        return

    # Download the largest size of the first photo
    photo = photos.photos[0][-1]  # last element = largest size
    file = await bot.get_file(photo.file_id)
    photo_bytes_io = io.BytesIO()
    await bot.download_file(file.file_path, destination=photo_bytes_io)
    photo_bytes_io.seek(0)
    photo_bytes = photo_bytes_io.read()

    # Generate branded avatar via service
    avatar_bytes = await avatar_service.generate_avatar(
        session=session,
        user=user,
        photo_bytes=photo_bytes,
    )

    await callback.message.answer_photo(
        BufferedInputFile(avatar_bytes, filename="avatar.png"),
        caption=(
            f"🖼 Твой аватар Синдиката готов, <b>{user.first_name}</b>!\n"
            f"Уровень <b>{user.level}</b> · Ветка: <b>"
            + (_BRANCH_LABELS.get(user.branch, "?") if user.branch else "не выбрана")
            + "</b>"
        ),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# gen_mentor_code — show referral_code as mentor code (level 50+)
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "gen_mentor_code")
async def cb_gen_mentor_code(
    callback: CallbackQuery,
    user: User | None,
    **data,
) -> None:
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    if user.level < 50:
        await callback.message.answer(
            f"🔒 Код наставника доступен с уровня 50.\n"
            f"Твой уровень: <b>{user.level}</b>",
            parse_mode="HTML",
        )
        return

    bot_info = await callback.bot.get_me()
    mentor_link = f"https://t.me/{bot_info.username}?start=ref{user.referral_code}"

    await callback.message.answer(
        f"🎓 <b>Твой код наставника</b>\n\n"
        f"Код: <code>{user.referral_code}</code>\n"
        f"Ссылка: {mentor_link}\n\n"
        f"Делись с учениками — за каждого активного друга получаешь бонусы!",
        parse_mode="HTML",
    )
