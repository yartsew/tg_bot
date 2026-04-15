"""
handlers/quests.py — /quest, breakfast photo upload, EXIF validation,
                     P2P review, daily quiz.
"""
from __future__ import annotations

import io

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from keyboards.quests import (
    control_photo_kb,
    p2p_vote_kb,
    quest_menu_kb,
    quiz_options_kb,
    quiz_retry_kb,
)
from services import quests as quest_service
from states.forms import QuestStates

router = Router()


# ---------------------------------------------------------------------------
# /quest — show quest menu
# ---------------------------------------------------------------------------

@router.message(Command("quest"))
@router.message(F.text == "🍳 Квест дня")
async def cmd_quest(
    message: Message,
    user: User | None,
    state: FSMContext,
    **data,
) -> None:
    await state.clear()

    if user is None:
        await message.answer("Сначала введи /start, чтобы зарегистрироваться.")
        return

    await message.answer(
        "🍳 <b>Квесты Синдиката</b>\n\n"
        "Выполняй задания, чтобы зарабатывать XP и SC:",
        reply_markup=quest_menu_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# submit_photo — ask user to send breakfast photo
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "submit_photo")
async def cb_submit_photo(
    callback: CallbackQuery,
    user: User | None,
    state: FSMContext,
    **data,
) -> None:
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    await state.set_state(QuestStates.waiting_photo)
    await callback.message.edit_text(
        "📸 <b>Отправь фото завтрака</b>\n\n"
        "Важно: фото должно быть сделано сегодня (проверяем EXIF дату).\n"
        "Отправь фото прямо сейчас:",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Photo received — validate EXIF, submit, show result
# ---------------------------------------------------------------------------

@router.message(QuestStates.waiting_photo, F.photo)
async def handle_breakfast_photo(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    user: User | None,
    state: FSMContext,
    **data,
) -> None:
    await state.clear()

    if user is None:
        await message.answer("Сначала введи /start.")
        return

    # Download the highest-resolution version of the photo
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    photo_bytes_io = io.BytesIO()
    await bot.download_file(file.file_path, destination=photo_bytes_io)
    photo_bytes_io.seek(0)
    photo_bytes = photo_bytes_io.read()

    # Extract EXIF timestamp (sync call, returns datetime | None)
    photo_taken_at = quest_service.validate_exif(photo_bytes)

    # Submit to quest service (EXIF age validation happens inside)
    ok, msg = await quest_service.submit_breakfast_photo(
        session=session,
        user=user,
        photo_file_id=photo.file_id,
        photo_taken_at=photo_taken_at,
        bot=bot,  # passed so service can notify P2P reviewers
    )

    if not ok:
        await message.answer(
            f"❌ <b>Фото не принято</b>\n\n{msg}\n\n"
            f"Убедись, что фото сделано сегодня, и попробуй снова.",
            parse_mode="HTML",
        )
        return

    await message.answer(msg, parse_mode="HTML")


@router.message(QuestStates.waiting_photo)
async def handle_non_photo_in_quest(message: Message, state: FSMContext, **data) -> None:
    """Prompt user to send a photo, not text."""
    await message.answer("📸 Пожалуйста, отправь именно <b>фото</b> завтрака.", parse_mode="HTML")


# ---------------------------------------------------------------------------
# daily_quiz — fetch today's quiz and display question
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "daily_quiz")
async def cb_daily_quiz(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    quiz = await quest_service.get_todays_quiz(session)
    if quiz is None:
        await callback.message.edit_text(
            "🌶 <b>Специя дня</b>\n\n"
            "На сегодня вопрос ещё не добавлен. Загляни позже!",
            parse_mode="HTML",
        )
        return

    await callback.message.edit_text(
        f"🌶 <b>Специя дня</b>\n\n"
        f"{quiz.question}",
        reply_markup=quiz_options_kb(quiz.options, quiz.id),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# quiz_answer:{question_id}:{index} — submit quiz answer
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("quiz_answer:"))
async def cb_quiz_answer(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    # Parse callback data: quiz_answer:{question_id}:{index}
    _, question_id_str, index_str = callback.data.split(":", 2)
    question_id = int(question_id_str)
    selected_index = int(index_str)

    result = await quest_service.submit_quiz_answer(
        session=session,
        user=user,
        question_id=question_id,
        answer_index=selected_index,
        paid_retry=False,
    )

    if result["already_answered"]:
        await callback.message.edit_text(
            "ℹ️ Ты уже отвечал на этот вопрос сегодня.",
            parse_mode="HTML",
        )
        return

    if result["is_correct"]:
        await callback.message.edit_text(
            f"✅ <b>Верно!</b>\n\n"
            f"+ <b>{result.get('xp_earned', 30)} XP</b> · + <b>{result.get('sc_earned', 0)} SC</b>",
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            f"❌ <b>Неверно.</b>\n\n"
            f"Правильный ответ: <b>{result.get('correct_option', '')}</b>\n\n"
            f"Хочешь попробовать ещё раз за <b>{result.get('retry_cost', 10)} SC</b>?",
            reply_markup=quiz_retry_kb(question_id),
            parse_mode="HTML",
        )


# ---------------------------------------------------------------------------
# quiz_retry:{question_id} — paid retry
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("quiz_retry:"))
async def cb_quiz_retry(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    _, question_id_str = callback.data.split(":", 1)
    question_id = int(question_id_str)

    # Fetch the question to show options again
    quiz = await quest_service.get_quiz_by_id(session, question_id)
    if quiz is None:
        await callback.message.edit_text("Вопрос не найден.")
        return

    result = await quest_service.submit_quiz_answer(
        session=session,
        user=user,
        question_id=question_id,
        answer_index=None,   # None = charge SC and re-show the question
        paid_retry=True,
    )

    if not result.get("retry_granted"):
        await callback.message.edit_text(
            f"❌ Недостаточно SC для повторной попытки.\n"
            f"Нужно: <b>{result.get('retry_cost', 10)} SC</b>, у тебя: <b>{user.sc_balance} SC</b>.",
            parse_mode="HTML",
        )
        return

    await callback.message.edit_text(
        f"🔄 <b>Повторная попытка</b>\n\n"
        f"{quiz.question}",
        reply_markup=quiz_options_kb(quiz.options, quiz.id),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# p2p_review — get a pending photo and show it for review
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "p2p_review")
async def cb_p2p_review(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    photo_entry = await quest_service.get_pending_p2p_for_user(session, user)
    if photo_entry is None:
        await callback.message.edit_text(
            "👁 <b>Народный контроль</b>\n\n"
            "На данный момент нет фотографий для проверки. Загляни позже!",
            parse_mode="HTML",
        )
        return

    await callback.message.answer_photo(
        photo=photo_entry.photo_file_id,
        caption=(
            f"👁 <b>Народный контроль</b>\n\n"
            f"Это завтрак? Оцени фото:"
        ),
        reply_markup=p2p_vote_kb(photo_entry.id),
        parse_mode="HTML",
    )
    await callback.message.delete()


# ---------------------------------------------------------------------------
# p2p_approve:{photo_id} and p2p_reject:{photo_id}
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("p2p_approve:"))
async def cb_p2p_approve(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer("Одобрено!")

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    _, photo_id_str = callback.data.split(":", 1)
    photo_id = int(photo_id_str)

    _, __, control_photo = await quest_service.submit_p2p_vote(
        session=session,
        reviewer=user,
        photo_id=photo_id,
        is_approved=True,
    )

    await callback.message.edit_caption(
        "✅ Ты одобрил фото. Спасибо за участие в контроле!",
        parse_mode="HTML",
    )

    if control_photo is not None:
        await callback.message.answer_photo(
            photo=control_photo.photo_file_id,
            caption=(
                "👁 <b>Контрольная проверка</b>\n\n"
                "Это завтрак? Оцени фото честно:"
            ),
            reply_markup=control_photo_kb(control_photo.id),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("p2p_reject:"))
async def cb_p2p_reject(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer("Отклонено!")

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    _, photo_id_str = callback.data.split(":", 1)
    photo_id = int(photo_id_str)

    _, __, control_photo = await quest_service.submit_p2p_vote(
        session=session,
        reviewer=user,
        photo_id=photo_id,
        is_approved=False,
    )

    await callback.message.edit_caption(
        "❌ Ты отклонил фото. Спасибо за участие в контроле!",
        parse_mode="HTML",
    )

    if control_photo is not None:
        await callback.message.answer_photo(
            photo=control_photo.photo_file_id,
            caption=(
                "👁 <b>Контрольная проверка</b>\n\n"
                "Это завтрак? Оцени фото честно:"
            ),
            reply_markup=control_photo_kb(control_photo.id),
            parse_mode="HTML",
        )


# ---------------------------------------------------------------------------
# control_approve / control_reject — anti-fraud control photo response
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("control_approve:"))
async def cb_control_approve(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    """User approved a fake control photo — apply penalty."""
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    # Penalty: approved a fake photo
    await quest_service.apply_control_photo_penalty(session, user)

    await callback.message.edit_caption(
        "⚠️ <b>Это было контрольное фото!</b>\n\n"
        "Ты одобрил заведомо поддельный снимок.\n"
        "Рейтинг доверия снижен. Будь внимательнее!",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("control_reject:"))
async def cb_control_reject(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    """User correctly rejected a fake control photo."""
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    await callback.message.edit_caption(
        "✅ <b>Верно!</b> Это было контрольное фото — ты прошёл проверку.",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# back_main — return to quest menu from any inline sub-screen
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "back_main")
async def cb_back_main(
    callback: CallbackQuery,
    state: FSMContext,
    **data,
) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        "🍳 <b>Квесты Синдиката</b>\n\n"
        "Выполняй задания, чтобы зарабатывать XP и SC:",
        reply_markup=quest_menu_kb(),
        parse_mode="HTML",
    )
