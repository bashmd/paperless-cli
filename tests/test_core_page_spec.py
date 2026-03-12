"""Tests for page specification parser helpers."""

from __future__ import annotations

import pytest

from pcli.core.errors import UsageValidationError
from pcli.core.page_spec import normalize_page_selection, parse_max_pages, parse_pages_spec


def test_parse_pages_spec_single_range_and_mixed() -> None:
    assert parse_pages_spec("2") == [2]
    assert parse_pages_spec("1-3") == [1, 2, 3]
    assert parse_pages_spec("1,3,5-7") == [1, 3, 5, 6, 7]


def test_parse_pages_spec_deduplicates_and_sorts() -> None:
    assert parse_pages_spec("5,1,3-5,1,4") == [1, 3, 4, 5]
    assert parse_pages_spec(" 3 - 4 , 2 , 4 ") == [2, 3, 4]


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        ",",
        "1,,2",
        "1-",
        "-2",
        "3-1",
        "0",
        "2-0",
        "a",
        "1-a",
        "1-2-3",
    ],
)
def test_parse_pages_spec_rejects_invalid_values(value: str) -> None:
    with pytest.raises(UsageValidationError):
        parse_pages_spec(value)


def test_parse_max_pages_accepts_positive_int() -> None:
    assert parse_max_pages(None) is None
    assert parse_max_pages("1") == 1
    assert parse_max_pages("7") == 7


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "true", "abc"])
def test_parse_max_pages_rejects_invalid_values(value: str) -> None:
    with pytest.raises(UsageValidationError):
        parse_max_pages(value)


def test_normalize_page_selection_applies_cap() -> None:
    assert normalize_page_selection(pages=None, max_pages=None) is None
    assert normalize_page_selection(pages="5,1,3-5", max_pages=None) == [1, 3, 4, 5]
    assert normalize_page_selection(pages="5,1,3-5", max_pages="2") == [1, 3]
