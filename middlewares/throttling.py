import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message


class ThrottlingMiddleware(BaseMiddleware):
    """Rate-limit messages to one per `rate_limit` seconds per user."""

    def __init__(self, rate_limit: float = 0.5) -> None:
        self.rate_limit = rate_limit
        self._last_seen: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        user_id: int = event.from_user.id if event.from_user else 0
        now = time.monotonic()
        last = self._last_seen.get(user_id, 0.0)

        if now - last < self.rate_limit:
            await event.answer("⏳ Не так быстро!")
            return  # drop the update, do not call the handler

        self._last_seen[user_id] = now
        return await handler(event, data)
