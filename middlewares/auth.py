from typing import Any, Awaitable, Callable, Dict, Union

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import ADMIN_IDS
from database.models import User

# Callbacks that are always allowed regardless of branch-choice gate
_BRANCH_EXEMPT_CALLBACKS = {"branch_butcher", "branch_vegan"}


class AuthMiddleware(BaseMiddleware):
    """
    Load the User ORM object from the database and inject it into
    handler data as data['user'] (None if not registered).
    Also sets data['is_admin'] based on ADMIN_IDS from config.
    Works for both Message and CallbackQuery update types.

    Branch-choice gate: if the user has reached level 10 but has not chosen a
    branch yet, every update is intercepted and the branch-selection prompt is
    shown instead. The branch callbacks themselves are exempt so the user can
    actually make a choice.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: Union[Message, CallbackQuery],
        data: Dict[str, Any],
    ) -> Any:
        from_user = event.from_user
        if from_user is None:
            data["user"] = None
            data["is_admin"] = False
            return await handler(event, data)

        telegram_id: int = from_user.id
        session: AsyncSession = data["session"]

        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user: User | None = result.scalar_one_or_none()

        data["user"] = user
        data["is_admin"] = telegram_id in ADMIN_IDS

        # Branch-choice gate — intercept all updates until branch is chosen
        if user is not None and user.level >= 10 and user.branch is None:
            # Let branch callbacks through so the user can respond
            if isinstance(event, CallbackQuery) and event.data in _BRANCH_EXEMPT_CALLBACKS:
                return await handler(event, data)

            from keyboards.profile import branch_kb
            prompt = (
                "⚠️ <b>Ты достиг уровня 10!</b>\n\n"
                "Чтобы продолжить пользоваться Синдикатом, выбери свою ветку:"
            )
            if isinstance(event, CallbackQuery):
                await event.answer()
                await event.message.answer(prompt, reply_markup=branch_kb(), parse_mode="HTML")
            else:
                await event.answer(prompt, reply_markup=branch_kb(), parse_mode="HTML")
            return  # drop the original update

        return await handler(event, data)
