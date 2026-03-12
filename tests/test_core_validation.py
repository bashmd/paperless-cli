"""Tests for validation helpers."""

from __future__ import annotations

import pytest

from pcli.core.errors import UsageValidationError
from pcli.core.validation import validate_raw_allowed


def test_raw_rejected_for_non_binary_commands() -> None:
    with pytest.raises(UsageValidationError):
        validate_raw_allowed(raw=True, command_path="docs get")


def test_raw_allowed_for_binary_commands() -> None:
    validate_raw_allowed(raw=True, command_path="docs download")
