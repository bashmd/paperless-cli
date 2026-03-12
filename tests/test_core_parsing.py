"""Tests for token parsing and global option conversion."""

from __future__ import annotations

import pytest

from pcli.core.errors import UsageValidationError
from pcli.core.options import FormatMode, GlobalOptions, parse_scalar
from pcli.core.parsing import parse_tokens


def test_last_assignment_wins_across_flag_and_key_value() -> None:
    result = parse_tokens(
        [
            "--timeout",
            "10",
            "timeout=42",
            "--format",
            "json",
            "format=ndjson",
        ],
        known_option_keys={"timeout", "format"},
    )
    options = GlobalOptions.from_updates(result.updates)
    assert options.timeout == 42
    assert options.format_mode is FormatMode.NDJSON


def test_boolean_switch_is_supported() -> None:
    result = parse_tokens(
        ["--raw", "--verbose=false"],
        known_option_keys={"raw", "verbose"},
        boolean_option_keys={"raw", "verbose"},
    )
    options = GlobalOptions.from_updates(result.updates)
    assert options.raw is True
    assert options.verbose is False


def test_boolean_split_form_consumes_explicit_value() -> None:
    result = parse_tokens(
        ["--verbose", "false", "--raw", "true"],
        known_option_keys={"raw", "verbose"},
        boolean_option_keys={"raw", "verbose"},
    )
    options = GlobalOptions.from_updates(result.updates)
    assert options.raw is True
    assert options.verbose is False
    assert result.positional == []


def test_invalid_boolean_split_form_raises_validation_error() -> None:
    with pytest.raises(UsageValidationError):
        parse_tokens(
            ["--verbose", "maybe"],
            known_option_keys={"verbose"},
            boolean_option_keys={"verbose"},
            strict_boolean_values=True,
        )


def test_passthrough_filters_are_collected_for_find_like_commands() -> None:
    result = parse_tokens(
        ["query=invoice", "correspondent__id=2", "page_size=100"],
        known_option_keys={"query"},
        passthrough_filter_mode=True,
    )
    assert result.updates == {"query": "invoice"}
    assert result.passthrough_filters == {"correspondent__id": "2", "page_size": "100"}


def test_boolean_switch_before_positional_token_is_allowed_in_default_mode() -> None:
    result = parse_tokens(
        ["--verbose", "docs", "get"],
        known_option_keys={"verbose"},
        boolean_option_keys={"verbose"},
    )
    options = GlobalOptions.from_updates(result.updates)
    assert options.verbose is True
    assert result.positional == ["docs", "get"]


def test_passthrough_filters_collect_unknown_long_options() -> None:
    result = parse_tokens(
        ["--correspondent__id", "2", "--tag__name=urgent"],
        known_option_keys={"query"},
        passthrough_filter_mode=True,
    )
    assert result.passthrough_filters == {"correspondent__id": "2", "tag__name": "urgent"}


def test_long_option_value_may_contain_equals_character() -> None:
    result = parse_tokens(
        ["--query", "vendor=acme", "--custom_field_query=field=value"],
        known_option_keys={"query"},
        passthrough_filter_mode=True,
    )
    assert result.updates == {"query": "vendor=acme"}
    assert result.passthrough_filters == {"custom_field_query": "field=value"}


def test_parse_scalar_supports_json_and_csv_lists() -> None:
    assert parse_scalar("[1,2,3]") == [1, 2, 3]
    assert parse_scalar("a,b,3") == ["a", "b", 3]
    assert parse_scalar("1") == 1


def test_missing_option_value_raises_validation_error() -> None:
    with pytest.raises(UsageValidationError):
        parse_tokens(["--timeout"], known_option_keys={"timeout"})


def test_invalid_format_raises_validation_error() -> None:
    with pytest.raises(UsageValidationError):
        GlobalOptions.from_updates({"format": "yaml"})
