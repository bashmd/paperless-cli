"""Whitespace normalization with optional Rust acceleration."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast


def _python_normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _import_rust_normalizer() -> Callable[[str], str]:
    from pcli_rust_norm import (  # type: ignore[import-untyped]
        normalize_whitespace as rust_normalize_whitespace,
    )

    return cast(Callable[[str], str], rust_normalize_whitespace)


def _resolve_normalizer() -> tuple[Callable[[str], str], str]:
    try:
        return _import_rust_normalizer(), "rust"
    except Exception:
        # Optional accelerator: keep CLI behavior identical when missing/broken.
        return _python_normalize_whitespace, "python"


_NORMALIZE_WHITESPACE, _NORMALIZE_IMPL = _resolve_normalizer()


def normalize_whitespace(value: str) -> str:
    return _NORMALIZE_WHITESPACE(value)


def normalizer_impl() -> str:
    return _NORMALIZE_IMPL
