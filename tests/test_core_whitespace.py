"""Tests for whitespace normalization strategy selection."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from pcli.core import whitespace


def test_normalize_whitespace_matches_split_join_semantics() -> None:
    value = " \n alpha\tbeta   gamma \r\n delta \t "
    assert whitespace.normalize_whitespace(value) == "alpha beta gamma delta"


def test_resolve_normalizer_uses_python_fallback_on_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_import() -> Callable[[str], str]:
        raise ImportError("missing optional extension")

    monkeypatch.setattr(whitespace, "_import_rust_normalizer", failing_import)
    normalizer, impl = whitespace._resolve_normalizer()

    assert impl == "python"
    assert normalizer(" a\t b \n c ") == "a b c"


def test_resolve_normalizer_uses_rust_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_rust(value: str) -> str:
        return f"rust::{value}"

    monkeypatch.setattr(whitespace, "_import_rust_normalizer", lambda: fake_rust)
    normalizer, impl = whitespace._resolve_normalizer()

    assert impl == "rust"
    assert normalizer("abc") == "rust::abc"
