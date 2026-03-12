"""Tests for docs notes subcommands."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from typer.testing import CliRunner

import pcli.cli.docs as docs_cli
from pcli.cli.main import app
from pcli.core.errors import UsageValidationError
from pcli.core.runtime import RuntimeContext

runner = CliRunner()


@dataclass(slots=True)
class FakeNote:
    _data: dict[str, Any] = field(default_factory=dict)


def test_docs_notes_list_returns_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_fetch_notes(client: Any, document_id: int) -> list[FakeNote]:
        _ = (client, document_id)
        return [FakeNote(_data={"id": 10, "note": "hello", "document": 7})]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_fetch_document_notes_sync", fake_fetch_notes)

    result = runner.invoke(app, ["docs", "notes", "list", "7"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["action"] == "notes-list"
    assert payload["meta"]["document_id"] == 7
    assert payload["meta"]["count"] == 1
    assert payload["data"]["items"][0]["id"] == 10


def test_docs_notes_add_requires_note_and_returns_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_add_note(client: Any, document_id: int, note: str) -> tuple[int, int]:
        _ = client
        assert document_id == 7
        assert note == "new note"
        return 55, 7

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_add_document_note_sync", fake_add_note)

    result = runner.invoke(app, ["docs", "notes", "add", "7", "note=new note"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["action"] == "notes-add"
    assert payload["data"] == {"note_id": 55, "document_id": 7}

    with pytest.raises(UsageValidationError) as missing_note:
        runner.invoke(app, ["docs", "notes", "add", "7"], catch_exceptions=False)
    assert missing_note.value.payload.code == "MISSING_NOTE_TEXT"


def test_docs_notes_delete_requires_confirmation_and_handles_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_delete_note(client: Any, document_id: int, note_id: int) -> bool:
        _ = client
        return document_id == 7 and note_id == 10

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_delete_document_note_sync", fake_delete_note)

    with pytest.raises(UsageValidationError) as missing_yes:
        runner.invoke(
            app,
            ["docs", "notes", "delete", "7", "10"],
            catch_exceptions=False,
        )
    assert missing_yes.value.payload.code == "CONFIRMATION_REQUIRED"

    result = runner.invoke(app, ["docs", "notes", "delete", "7", "10", "yes=true"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["action"] == "notes-delete"
    assert payload["data"]["deleted"] is True

    with pytest.raises(UsageValidationError) as not_found:
        runner.invoke(
            app,
            ["docs", "notes", "delete", "7", "9", "yes=true"],
            catch_exceptions=False,
        )
    assert not_found.value.payload.code == "NOTE_NOT_FOUND"
