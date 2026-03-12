"""Argument parsing utilities for mixed flag and key=value styles."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from pcli.core.errors import UsageValidationError


@dataclass(slots=True)
class ParseResult:
    """Result of token parsing."""

    updates: dict[str, str] = field(default_factory=dict)
    positional: list[str] = field(default_factory=list)
    passthrough_filters: dict[str, str] = field(default_factory=dict)
    passthrough_tokens: list[str] = field(default_factory=list)


def _split_assignment(token: str) -> tuple[str, str] | None:
    if "=" not in token:
        return None
    key, value = token.split("=", 1)
    if not key:
        return None
    return key, value


def _is_explicit_option_value(token: str, *, boolean_option: bool) -> bool:
    """Return whether token should be treated as value for preceding option."""
    if token.startswith("--"):
        return False
    if not boolean_option:
        return True
    return token.strip().lower() in {"1", "0", "true", "false", "yes", "no", "on", "off"}


def parse_tokens(
    tokens: Iterable[str],
    *,
    known_option_keys: set[str],
    boolean_option_keys: set[str] | None = None,
    passthrough_filter_mode: bool = False,
    strict_boolean_values: bool = False,
) -> ParseResult:
    """Parse option tokens in left-to-right order with last assignment winning.

    Supports:
    - `key=value`
    - `--key value`
    - `--key=value`
    - boolean switches for known keys: `--raw` => `raw=true`

    Boolean behavior:
    - default mode (`strict_boolean_values=False`): a boolean switch may be followed by
      positional tokens without forcing value parsing (`--verbose docs ...`).
    - strict mode (`strict_boolean_values=True`): non-boolean split values raise
      `INVALID_BOOLEAN` (`--verbose maybe`).
    """
    result = ParseResult()
    boolean_keys = boolean_option_keys or set()
    token_list = list(tokens)

    index = 0
    while index < len(token_list):
        token = token_list[index]

        if token.startswith("--"):
            token_no_prefix = token[2:]
            assignment = _split_assignment(token_no_prefix)
            if assignment:
                key, value = assignment
            else:
                key = token_no_prefix
                if key in boolean_keys and index + 1 < len(token_list):
                    next_token = token_list[index + 1]
                    if _is_explicit_option_value(next_token, boolean_option=True):
                        value = next_token
                        index += 1
                    elif next_token.startswith("--") or "=" in next_token:
                        value = "true"
                    else:
                        if strict_boolean_values:
                            raise UsageValidationError(
                                f"Invalid boolean value for --{key}: {next_token!r}.",
                                details={"option": key, "value": next_token},
                                error_code="INVALID_BOOLEAN",
                            )
                        value = "true"
                elif key in boolean_keys:
                    value = "true"
                elif index + 1 < len(token_list):
                    next_token = token_list[index + 1]
                    if not _is_explicit_option_value(next_token, boolean_option=False):
                        raise UsageValidationError(
                            f"Option --{key} requires a value.",
                            details={"option": key},
                            error_code="MISSING_OPTION_VALUE",
                        )
                    value = next_token
                    index += 1
                else:
                    raise UsageValidationError(
                        f"Option --{key} requires a value.",
                        details={"option": key},
                        error_code="MISSING_OPTION_VALUE",
                    )

            if key in known_option_keys:
                result.updates[key] = value
            elif passthrough_filter_mode:
                result.passthrough_filters[key] = value
            else:
                if assignment:
                    result.passthrough_tokens.append(token)
                else:
                    result.passthrough_tokens.append(f"--{key}")
                    if key not in boolean_keys:
                        result.passthrough_tokens.append(value)
                    elif value != "true":
                        result.passthrough_tokens.append(value)
            index += 1
            continue

        assignment = _split_assignment(token)
        if assignment:
            key, value = assignment
            if key in known_option_keys:
                result.updates[key] = value
            elif passthrough_filter_mode:
                result.passthrough_filters[key] = value
            else:
                result.passthrough_tokens.append(token)
            index += 1
            continue

        result.positional.append(token)
        index += 1

    return result
