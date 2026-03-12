"""Tests for cursor encoding/decoding helpers."""

from __future__ import annotations

import base64
import json

import pytest

from pcli.core.cursor import decode_cursor, encode_cursor
from pcli.core.errors import UsageValidationError


def test_cursor_roundtrip() -> None:
    token = encode_cursor(command="docs.find", signature={"query": "invoice"}, offset=5)
    state = decode_cursor(token)
    assert state.command == "docs.find"
    assert state.signature == {"query": "invoice"}
    assert state.offset == 5


def test_cursor_decode_rejects_invalid_payload() -> None:
    with pytest.raises(UsageValidationError):
        decode_cursor("not-a-valid-token")

    bad_payload = {"v": 999, "cmd": "docs.find", "sig": {}, "offset": 0}
    bad_token = base64.urlsafe_b64encode(json.dumps(bad_payload).encode("utf-8")).decode("ascii")
    with pytest.raises(UsageValidationError):
        decode_cursor(bad_token)

    bool_offset_payload = {"v": 1, "cmd": "docs.find", "sig": {}, "offset": True}
    bool_offset_token = base64.urlsafe_b64encode(
        json.dumps(bool_offset_payload).encode("utf-8")
    ).decode("ascii")
    with pytest.raises(UsageValidationError):
        decode_cursor(bool_offset_token)
