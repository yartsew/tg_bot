"""
Quest engine — Кулинарный Синдикат.
Handles breakfast photo submissions, P2P review queue, and daily quiz.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import piexif
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from database.models import (
    ControlPhoto,
    DailyPhoto,
    P2PReview,
    QuizQuestion,
    User,
    UserQuizAttempt,
)

if TYPE_CHECKING:
    pass  # battle_pass_service imported inline to avoid circular imports


# ---------------------------------------------------------------------------
# EXIF helpers
# ---------------------------------------------------------------------------


def validate_exif(photo_bytes: bytes) -> datetime | None:
    """
    Extract DateTimeOriginal from EXIF data.
    Returns a datetime object if found and parseable, otherwise None.
    """
    try:
        exif_dict = piexif.load(photo_bytes)
        exif_data = exif_dict.get("Exif", {})
        raw = exif_data.get(piexif.ExifIFD.DateTimeOriginal)
        if not raw:
            return None
        dt_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        return datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Breakfast photo submission
# ---------------------------------------------------------------------------


async def submit_breakfast_photo(
    session: AsyncSession,
    user: User,
    photo_file_id: str,
    photo_taken_at: datetime | None,
    bot=None,
) -> tuple[bool, str]:
    """
    Submit a breakfast photo for today's quest.

    Validation:
    - One submission per user per calendar day.
    - If EXIF date is provided and older than 24 h → reject.

    On success: saves DailyPhoto, assigns P2P reviewers, notifies them.
    Returns (success, message).
    """
    today = date.today()

    # Check for duplicate submission today
    existing = await session.execute(
        select(DailyPhoto).where(
            DailyPhoto.user_id == user.id,
            DailyPhoto.uploaded_at >= datetime.combine(today, datetime.min.time()),
        )
    )
    if existing.scalar_one_or_none():
        return False, "❌ Ты уже отправлял фото завтрака сегодня. Возвращайся завтра!"

    # Validate EXIF age
    if photo_taken_at is not None:
        age = datetime.utcnow() - photo_taken_at
        if age > timedelta(hours=24):
            return (
                False,
                "❌ Фото слишком старое — оно было сделано более 24 часов назад. "
                "Пожалуйста, отправь свежее фото сегодняшнего завтрака.",
            )

    photo = DailyPhoto(
        user_id=user.id,
        photo_file_id=photo_file_id,
        photo_taken_at=photo_taken_at,
        uploaded_at=datetime.utcnow(),
        status="p2p_pending",
    )
    session.add(photo)
    await session.flush()  # get photo.id before assigning reviewers

    reviewers = await assign_p2p_reviewers(session, photo)
    await session.commit()

    # Notify assigned reviewers
    if bot is not None:
        from keyboards.quests import p2p_vote_kb
        for reviewer in reviewers:
            try:
                await bot.send_photo(
                    chat_id=reviewer.telegram_id,
                    photo=photo_file_id,
                    caption=(
                        "👁 <b>Народный контроль</b>\n\n"
                        "Новое фото завтрака ждёт твоей оценки:"
                    ),
                    reply_markup=p2p_vote_kb(photo.id),
                    parse_mode="HTML",
                )
            except Exception:
                pass

    if photo_taken_at is not None:
        success_message = (
            f"✅ <b>Завтрак принят!</b>\n\n"
            f"Фото отправлено на народный контроль (P2P проверку).\n"
            f"После {config.P2P_APPROVALS_NEEDED} одобрений ты получишь "
            f"<b>+{config.XP_BREAKFAST_PHOTO} XP</b>."
        )
    else:
        success_message = (
            f"✅ <b>Завтрак принят!</b>\n\n"
            f"⚠️ <b>EXIF-данные не найдены</b> — фото пройдёт усиленную проверку "
            f"({config.P2P_APPROVALS_NEEDED_NO_EXIF} одобрения вместо {config.P2P_APPROVALS_NEEDED}).\n"
            f"Это нормально, если ты снимал через браузерный клиент или переслал фото.\n\n"
            f"После одобрения ты получишь <b>+{config.XP_BREAKFAST_PHOTO} XP</b>."
        )
    return True, success_message


# ---------------------------------------------------------------------------
# P2P review queue
# ---------------------------------------------------------------------------


async def assign_p2p_reviewers(
    session: AsyncSession,
    photo: DailyPhoto,
) -> list[User]:
    """
    Pick up to P2P_REVIEWERS_PER_PHOTO random subscribed users who:
    - are not the photo owner
    - have not already reviewed this photo
    Returns the list of selected reviewers (for testing / notification purposes).
    """
    # Users already assigned as reviewers
    reviewed_result = await session.execute(
        select(P2PReview.reviewer_id).where(P2PReview.photo_id == photo.id)
    )
    already_reviewing: set[int] = {row[0] for row in reviewed_result.all()}
    already_reviewing.add(photo.user_id)

    # Eligible subscribed users
    candidates_result = await session.execute(
        select(User).where(
            User.is_subscribed.is_(True),
            User.id.not_in(already_reviewing),
            User.is_active.is_(True),
        )
    )
    candidates = list(candidates_result.scalars().all())

    chosen = random.sample(
        candidates,
        min(config.P2P_REVIEWERS_PER_PHOTO, len(candidates)),
    )

    # Persist reviewer assignments so only designated reviewers can vote
    for reviewer in chosen:
        review = P2PReview(
            photo_id=photo.id,
            reviewer_id=reviewer.id,
            is_approved=None,  # not yet voted
        )
        session.add(review)

    return chosen


async def apply_control_photo_penalty(
    session: AsyncSession,
    user: User,
) -> None:
    """
    Penalise a reviewer who approved a fake control photo:
    -100 XP (floor 0) and -10 trust_rating (floor 0).
    """
    user.xp = max(0, (user.xp or 0) - 100)
    user.trust_rating = max(0, (user.trust_rating or 100) - 10)
    await session.commit()


async def submit_p2p_vote(
    session: AsyncSession,
    reviewer: User,
    photo_id: int,
    is_approved: bool,
) -> tuple[bool, str, "ControlPhoto | None"]:
    """
    Record a P2P vote.

    - Saves P2PReview record.
    - Updates approve/reject counters on DailyPhoto.
    - If approve_count >= P2P_APPROVALS_NEEDED → approve photo, give XP to uploader.
    - With 20% probability, picks a control (fake) photo to send to the reviewer.

    Returns (done, message, control_photo_or_none).
    Caller must send control_photo to the reviewer and later call
    apply_control_photo_penalty if the reviewer approves it.
    """
    # Find the existing assignment record for this reviewer
    existing_result = await session.execute(
        select(P2PReview).where(
            P2PReview.photo_id == photo_id,
            P2PReview.reviewer_id == reviewer.id,
        )
    )
    review = existing_result.scalar_one_or_none()

    if review is not None and review.is_approved is not None:
        return False, "❌ Ты уже голосовал за это фото."

    photo_result = await session.execute(
        select(DailyPhoto).where(DailyPhoto.id == photo_id)
    )
    photo = photo_result.scalar_one_or_none()
    if photo is None:
        return False, "❌ Фото не найдено."

    if review is not None:
        # Update the pre-assigned record with the actual vote
        review.is_approved = is_approved
    else:
        # Reviewer was not pre-assigned (e.g. edge case) — create a new record
        review = P2PReview(
            photo_id=photo_id,
            reviewer_id=reviewer.id,
            is_approved=is_approved,
        )
        session.add(review)

    if is_approved:
        photo.p2p_approve_count = (photo.p2p_approve_count or 0) + 1
    else:
        photo.p2p_reject_count = (photo.p2p_reject_count or 0) + 1

    message = "✅ Голос принят!"

    # Check approval threshold (stricter for photos without EXIF)
    threshold = (
        config.P2P_APPROVALS_NEEDED_NO_EXIF
        if photo.photo_taken_at is None
        else config.P2P_APPROVALS_NEEDED
    )
    if (
        photo.status == "p2p_pending"
        and photo.p2p_approve_count >= threshold
    ):
        photo.status = "approved"
        # Give XP to the uploader
        uploader_result = await session.execute(
            select(User).where(User.id == photo.user_id)
        )
        uploader = uploader_result.scalar_one_or_none()
        if uploader:
            from services import battle_pass as battle_pass_service  # lazy import

            await battle_pass_service.add_xp(
                session,
                uploader,
                config.XP_BREAKFAST_PHOTO,
                description="завтрак одобрен P2P",
            )
        message = "✅ Голос принят! Фото одобрено сообществом."

    await session.flush()
    await session.commit()
    return True, message, await maybe_inject_control_photo(session, reviewer)


async def get_pending_p2p_for_user(
    session: AsyncSession,
    user: User,
) -> DailyPhoto | None:
    """
    Find a photo with status='p2p_pending' that the given user has not yet reviewed
    and is not their own photo.
    """
    reviewed_result = await session.execute(
        select(P2PReview.photo_id).where(P2PReview.reviewer_id == user.id)
    )
    already_reviewed: set[int] = {row[0] for row in reviewed_result.all()}

    query = (
        select(DailyPhoto)
        .where(
            DailyPhoto.status == "p2p_pending",
            DailyPhoto.user_id != user.id,
        )
        .order_by(DailyPhoto.uploaded_at.asc())
    )
    if already_reviewed:
        query = query.where(DailyPhoto.id.not_in(already_reviewed))

    result = await session.execute(query.limit(1))
    return result.scalar_one_or_none()


async def maybe_inject_control_photo(
    session: AsyncSession,
    reviewer: User,
) -> ControlPhoto | None:
    """
    With a 20% probability, select a random ControlPhoto and return it so that
    the caller can present it as a fake review task for anti-fraud checking.
    Returns ControlPhoto or None.
    """
    if random.random() > 0.20:
        return None

    result = await session.execute(
        select(ControlPhoto).order_by(func.random())
    )
    return result.scalars().first()


# ---------------------------------------------------------------------------
# Quiz
# ---------------------------------------------------------------------------


async def get_todays_quiz(session: AsyncSession) -> QuizQuestion | None:
    """Return the QuizQuestion scheduled for today, or None."""
    today = date.today()
    result = await session.execute(
        select(QuizQuestion).where(QuizQuestion.scheduled_date == today)
    )
    return result.scalar_one_or_none()


async def get_quiz_by_id(session: AsyncSession, question_id: int) -> QuizQuestion | None:
    """Return a QuizQuestion by its primary key, or None."""
    result = await session.execute(
        select(QuizQuestion).where(QuizQuestion.id == question_id)
    )
    return result.scalar_one_or_none()


async def submit_quiz_answer(
    session: AsyncSession,
    user: User,
    question_id: int,
    answer_index: int | None,
    paid_retry: bool = False,
) -> dict:
    """
    Record a quiz answer attempt.

    - If already answered correctly today → return already_answered=True.
    - If paid_retry=True and answer_index is None → deduct SC and return retry_granted=True
      so the caller can re-display the question without recording an answer.
    - If paid_retry=True and answer_index is provided → deduct SC and record the answer.
    - Records UserQuizAttempt (or updates existing).
    - If correct → give XP_QUIZ_CORRECT XP.

    Returns dict with keys:
        success, already_answered, is_correct, xp_earned, sc_earned,
        correct_option, retry_cost, retry_granted, message
    """
    today = date.today()
    retry_cost = config.SC_QUIZ_RETRY_COST

    attempt_result = await session.execute(
        select(UserQuizAttempt).where(
            UserQuizAttempt.user_id == user.id,
            UserQuizAttempt.question_id == question_id,
            UserQuizAttempt.date == today,
        )
    )
    existing_attempt = attempt_result.scalar_one_or_none()

    # Already answered correctly
    if existing_attempt and existing_attempt.is_correct:
        return {
            "success": False,
            "already_answered": True,
            "is_correct": True,
            "xp_earned": 0,
            "sc_earned": 0,
            "correct_option": "",
            "retry_cost": retry_cost,
            "retry_granted": False,
            "message": "❌ Ты уже правильно ответил на этот вопрос сегодня.",
        }

    # Handle paid retry charge
    if paid_retry:
        if (user.sc_balance or 0) < retry_cost:
            return {
                "success": False,
                "already_answered": False,
                "is_correct": False,
                "xp_earned": 0,
                "sc_earned": 0,
                "correct_option": "",
                "retry_cost": retry_cost,
                "retry_granted": False,
                "message": f"❌ Недостаточно SC для повторной попытки. Нужно {retry_cost} SC.",
            }
        from services import coins as coins_service  # lazy import

        await coins_service.deduct_sc(
            session,
            user,
            retry_cost,
            description="повторная попытка квиза",
        )

        # answer_index=None means: just charge SC and re-show the question
        if answer_index is None:
            await session.commit()
            return {
                "success": True,
                "already_answered": False,
                "is_correct": False,
                "xp_earned": 0,
                "sc_earned": 0,
                "correct_option": "",
                "retry_cost": retry_cost,
                "retry_granted": True,
                "message": "🔄 SC списаны. Выбери ответ!",
            }

    # Load question
    question_result = await session.execute(
        select(QuizQuestion).where(QuizQuestion.id == question_id)
    )
    question = question_result.scalar_one_or_none()
    if question is None:
        return {
            "success": False,
            "already_answered": False,
            "is_correct": False,
            "xp_earned": 0,
            "sc_earned": 0,
            "correct_option": "",
            "retry_cost": retry_cost,
            "retry_granted": False,
            "message": "❌ Вопрос не найден.",
        }

    is_correct = answer_index == question.correct_index
    correct_option = (
        question.options[question.correct_index]
        if question.options and 0 <= question.correct_index < len(question.options)
        else ""
    )

    if existing_attempt:
        existing_attempt.attempts += 1
        existing_attempt.is_correct = is_correct
        if paid_retry:
            existing_attempt.sc_spent = (existing_attempt.sc_spent or 0) + retry_cost
    else:
        attempt = UserQuizAttempt(
            user_id=user.id,
            question_id=question_id,
            date=today,
            is_correct=is_correct,
            sc_spent=retry_cost if paid_retry else 0,
            attempts=1,
        )
        session.add(attempt)

    xp_earned = 0
    if is_correct:
        from services import battle_pass as battle_pass_service  # lazy import

        await battle_pass_service.add_xp(
            session,
            user,
            config.XP_QUIZ_CORRECT,
            description="правильный ответ на квиз",
        )
        xp_earned = config.XP_QUIZ_CORRECT

    await session.commit()

    return {
        "success": True,
        "already_answered": False,
        "is_correct": is_correct,
        "xp_earned": xp_earned,
        "sc_earned": 0,
        "correct_option": correct_option,
        "retry_cost": retry_cost,
        "retry_granted": False,
        "message": f"✅ Правильно! +{xp_earned} XP" if is_correct else "❌ Неверный ответ.",
    }
