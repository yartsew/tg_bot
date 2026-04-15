"""
handlers/subscription.py — /subscribe, payment flow, SC partial payment.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    LabeledPrice,
    Message,
    SuccessfulPayment,
)
from sqlalchemy.ext.asyncio import AsyncSession

import config
from database.models import User
from keyboards.subscription import sc_amount_kb, subscription_kb
from services import subscription as subscription_service
from services import referral as referral_service

router = Router()


# ---------------------------------------------------------------------------
# /subscribe — show current status and payment options
# ---------------------------------------------------------------------------

@router.message(Command("subscribe"))
@router.message(F.text == "💳 Подписка")
async def cmd_subscribe(
    message: Message,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    """Show subscription status and payment keyboard."""
    if user is None:
        await message.answer("Сначала введи /start, чтобы зарегистрироваться.")
        return

    price = await subscription_service.get_subscription_price(session)
    prize_fund = await subscription_service.get_prize_fund(session)

    status_icon = "✅" if user.is_subscribed else "❌"
    status_label = "Активна" if user.is_subscribed else "Не активна"

    end_text = ""
    if user.subscription_end:
        end_text = f"\n📅 До: <b>{user.subscription_end.strftime('%d.%m.%Y')}</b>"

    text = (
        f"💳 <b>Подписка Кулинарного Синдиката</b>\n\n"
        f"Статус: {status_icon} <b>{status_label}</b>{end_text}\n\n"
        f"💰 Стоимость: <b>{price:.0f}₽</b> / 30 дней\n"
        f"🏆 Призовой фонд этого месяца: <b>{prize_fund:.0f}₽</b>\n\n"
        f"🪙 Твой SC баланс: <b>{user.sc_balance}</b>\n"
        f"(Можно использовать до 50% стоимости подписки)"
    )

    is_ambassador = await referral_service.check_ambassador(session, user)
    has_sc = (user.sc_balance or 0) > 0
    await message.answer(
        text,
        reply_markup=subscription_kb(has_sc=has_sc, price=price, is_ambassador=is_ambassador),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# pay_full — send Telegram invoice
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "pay_full")
async def cb_pay_full(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    price = await subscription_service.get_subscription_price(session)
    price_kopecks = int(price * 100)

    if not config.PAYMENT_PROVIDER_TOKEN:
        # TODO: Set PAYMENT_PROVIDER_TOKEN in .env to enable real payments
        await callback.message.answer(
            "⚠️ <b>Платёжный провайдер не настроен.</b>\n\n"
            "Администратор должен указать PAYMENT_PROVIDER_TOKEN. "
            "Пожалуйста, свяжитесь с поддержкой.",
            parse_mode="HTML",
        )
        return

    await callback.message.answer_invoice(
        title="Подписка Кулинарный Синдикат",
        description=f"Подписка на 30 дней — {price:.0f}₽",
        payload=f"subscription:full:{user.id}",
        provider_token=config.PAYMENT_PROVIDER_TOKEN,
        currency="RUB",
        prices=[LabeledPrice(label="Подписка", amount=price_kopecks)],
    )


# ---------------------------------------------------------------------------
# pay_with_sc — show SC balance + max discount, confirm
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "pay_with_sc")
async def cb_pay_with_sc(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    price = await subscription_service.get_subscription_price(session)
    max_sc_discount = int(price * 0.5)  # max 50% of price
    sc_to_use = min(user.sc_balance or 0, max_sc_discount)
    remaining = price - sc_to_use

    text = (
        f"🪙 <b>Оплата с SC</b>\n\n"
        f"Твой баланс: <b>{user.sc_balance} SC</b>\n"
        f"Максимальная скидка SC: <b>{max_sc_discount} SC</b> (50% от цены)\n\n"
        f"Будет списано: <b>{sc_to_use} SC</b>\n"
        f"К доплате: <b>{remaining:.0f}₽</b>\n\n"
        f"Подтверждаешь?"
    )

    await callback.message.edit_text(text, reply_markup=sc_amount_kb(), parse_mode="HTML")


# ---------------------------------------------------------------------------
# confirm_sc — issue invoice for remaining amount after SC discount
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "confirm_sc")
async def cb_confirm_sc(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    price = await subscription_service.get_subscription_price(session)
    max_sc_discount = int(price * 0.5)
    sc_to_use = min(user.sc_balance or 0, max_sc_discount)
    remaining = price - sc_to_use
    remaining_kopecks = int(remaining * 100)

    if not config.PAYMENT_PROVIDER_TOKEN:
        # TODO: Set PAYMENT_PROVIDER_TOKEN in .env to enable real payments
        await callback.message.answer(
            "⚠️ <b>Платёжный провайдер не настроен.</b>\n\n"
            "Администратор должен указать PAYMENT_PROVIDER_TOKEN.",
            parse_mode="HTML",
        )
        return

    await callback.message.answer_invoice(
        title="Подписка Кулинарный Синдикат (со SC)",
        description=f"Подписка 30 дней — {sc_to_use} SC + {remaining:.0f}₽",
        payload=f"subscription:sc:{user.id}:{sc_to_use}",
        provider_token=config.PAYMENT_PROVIDER_TOKEN,
        currency="RUB",
        prices=[LabeledPrice(label=f"Оплата ({sc_to_use} SC учтены)", amount=remaining_kopecks)],
    )


# ---------------------------------------------------------------------------
# pay_ambassador — activate free subscription for ambassador
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "pay_ambassador")
async def cb_pay_ambassador(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer()

    if user is None:
        await callback.message.answer("Сначала введи /start.")
        return

    # Re-verify ambassador status
    is_ambassador = await referral_service.check_ambassador(session, user)
    if not is_ambassador:
        await callback.message.edit_text(
            "❌ Статус амбассадора не подтверждён. "
            "Нужно 10 активных оплативших друзей.",
            parse_mode="HTML",
        )
        return

    # Consume the ambassador perk — remove the flag so it can't be reused
    from sqlalchemy import delete
    from database.models import AdminSetting
    await session.execute(
        delete(AdminSetting).where(AdminSetting.key == f"ambassador_{user.id}")
    )

    subscription = await subscription_service.create_subscription(
        session=session,
        user=user,
        price=0.0,
        sc_used=0,
        payment_id="ambassador_free",
    )

    await callback.message.edit_text(
        f"🦅 <b>Бесплатная подписка активирована!</b>\n\n"
        f"Действует до: <b>{subscription.end_date.strftime('%d.%m.%Y')}</b>\n\n"
        f"Спасибо, что приводишь друзей в Синдикат!",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# skip_sc — redirect to full payment
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "skip_sc")
async def cb_skip_sc(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    await callback.answer()
    # Reuse pay_full logic by delegating
    await cb_pay_full(callback, session=session, user=user)


# ---------------------------------------------------------------------------
# successful_payment — Telegram sends this after user completes payment
# ---------------------------------------------------------------------------

@router.message(F.successful_payment)
async def handle_successful_payment(
    message: Message,
    session: AsyncSession,
    user: User | None,
    **data,
) -> None:
    """Handle confirmed Telegram payment — create subscription record."""
    if user is None:
        return

    payment: SuccessfulPayment = message.successful_payment
    payload = payment.invoice_payload  # e.g. "subscription:full:42" or "subscription:sc:42:100"

    sc_used = 0
    if payload.startswith("subscription:sc:"):
        parts = payload.split(":")
        if len(parts) == 4:
            sc_used = int(parts[3])

    price_paid = payment.total_amount / 100.0  # convert kopecks → rubles

    subscription = await subscription_service.create_subscription(
        session=session,
        user=user,
        price=price_paid,
        sc_used=sc_used,
        payment_id=payment.telegram_payment_charge_id,
    )

    await message.answer(
        f"✅ <b>Подписка активирована!</b>\n\n"
        f"Действует до: <b>{subscription.end_date.strftime('%d.%m.%Y')}</b>\n"
        f"Оплачено: <b>{price_paid:.0f}₽</b>"
        + (f" + <b>{sc_used} SC</b>" if sc_used else ""),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# cancel — dismiss payment flow
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "cancel")
async def cb_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    **data,
) -> None:
    await callback.answer("Отменено.")
    await state.clear()
    await callback.message.edit_text("❌ Оплата отменена.")
