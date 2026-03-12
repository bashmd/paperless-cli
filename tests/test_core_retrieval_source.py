"""Tests for retrieval source parsing and fallback logic."""

from __future__ import annotations

import pytest

from pcli.core.errors import UsageValidationError
from pcli.core.retrieval_source import parse_retrieval_source, resolve_source_candidates


def test_parse_retrieval_source_defaults_to_auto() -> None:
    assert parse_retrieval_source(None) == "auto"


@pytest.mark.parametrize("value", ["auto", "ocr", "archive", "original", " AUTO "])
def test_parse_retrieval_source_accepts_supported_values(value: str) -> None:
    assert parse_retrieval_source(value) in {"auto", "ocr", "archive", "original"}


def test_parse_retrieval_source_rejects_invalid_value() -> None:
    with pytest.raises(UsageValidationError):
        parse_retrieval_source("pdf")


def test_resolve_source_candidates_without_pages() -> None:
    assert resolve_source_candidates(source="auto", has_page_filter=False) == ["ocr"]
    assert resolve_source_candidates(source="ocr", has_page_filter=False) == ["ocr"]
    assert resolve_source_candidates(source="archive", has_page_filter=False) == ["archive"]
    assert resolve_source_candidates(source="original", has_page_filter=False) == ["original"]


def test_resolve_source_candidates_with_pages() -> None:
    assert resolve_source_candidates(source="auto", has_page_filter=True) == ["archive", "original"]
    assert resolve_source_candidates(source="archive", has_page_filter=True) == ["archive"]
    assert resolve_source_candidates(source="original", has_page_filter=True) == ["original"]
    assert resolve_source_candidates(source="ocr", has_page_filter=True) == ["ocr"]
