"""Adapt small list fixtures to the discovery adapter's async iterator interface."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any


def streaming_fake[T](
    collect: Callable[..., list[T]],
) -> Callable[..., AsyncGenerator[T]]:
    async def iterate(*args: Any, **kwargs: Any) -> AsyncGenerator[T]:
        for item in collect(*args, **kwargs):
            yield item

    return iterate


def async_result[T](call: Callable[..., T]) -> Callable[..., Awaitable[T]]:
    async def run(*args: Any, **kwargs: Any) -> T:
        return call(*args, **kwargs)

    return run
