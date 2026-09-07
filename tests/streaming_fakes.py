"""Adapt small list fixtures to the discovery adapter's async iterator interface."""

from collections.abc import AsyncGenerator, Callable
from typing import Any


def streaming_fake[T](
    collect: Callable[..., list[T]],
) -> Callable[..., AsyncGenerator[T]]:
    async def iterate(*args: Any, **kwargs: Any) -> AsyncGenerator[T]:
        for item in collect(*args, **kwargs):
            yield item

    return iterate
