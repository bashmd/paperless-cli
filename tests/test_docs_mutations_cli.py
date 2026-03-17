"""Tests for docs create/update/delete mutation commands."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import pcli.cli.docs as docs_cli
from pcli.cli.main import app
from pcli.core.errors import PcliError, UsageValidationError
from pcli.core.runtime import RuntimeContext

runner = CliRunner()


class DummyDocument:
    def __init__(self) -> None:
        self.title: str | None = None
        self.tags: list[int] | None = None


class _LoopBoundDocument:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self.title: str | None = None

    async def update(self, *, only_changed: bool) -> bool:
        _ = only_changed
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("Document update called on a different event loop")
        return True


def test_docs_create_reads_file_and_passes_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_create_document(
        client: Any,
        *,
        document_bytes: bytes,
        filename: str,
        fields: dict[str, Any],
    ) -> int | str | tuple[int, int]:
        _ = client
        captured["document_bytes"] = document_bytes
        captured["filename"] = filename
        captured["fields"] = fields
        return "task-123"

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_create_document_sync", fake_create_document)

    input_file = tmp_path / "input.pdf"
    input_file.write_bytes(b"PDFDATA")

    result = runner.invoke(
        app,
        [
            "docs",
            "create",
            f"document={input_file}",
            "title=Invoice A",
            "tags=1,2",
        ],
    )
    assert result.exit_code == 0
    assert captured["document_bytes"] == b"PDFDATA"
    assert captured["filename"] == "input.pdf"
    assert captured["fields"]["title"] == "Invoice A"
    assert captured["fields"]["tags"] == [1, 2]

    payload = json.loads(result.output)
    assert payload["action"] == "create"
    assert payload["data"]["result"] == "task-123"


def test_docs_update_defaults_only_changed_and_allows_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_update_document_fields(
        client: Any,
        *,
        document_id: int,
        fields: dict[str, Any],
        only_changed: bool,
    ) -> bool:
        _ = (client, document_id)
        doc = DummyDocument()
        for key, value in fields.items():
            setattr(doc, key, value)
        captured["document"] = doc
        captured["only_changed"] = only_changed
        return True

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_update_document_fields_sync", fake_update_document_fields)

    first = runner.invoke(app, ["docs", "update", "4", "title=New Title"])
    assert first.exit_code == 0
    assert captured["only_changed"] is True
    assert captured["document"].title == "New Title"

    second = runner.invoke(
        app,
        ["docs", "update", "4", "title=Replaced", "only_changed=false"],
    )
    assert second.exit_code == 0
    assert captured["only_changed"] is False
    assert captured["document"].title == "Replaced"


def test_docs_delete_requires_yes_and_deletes_when_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_delete_document_by_id(client: Any, *, document_id: int) -> bool:
        _ = (client, document_id)
        return True

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_delete_document_by_id_sync", fake_delete_document_by_id)

    with pytest.raises(UsageValidationError) as missing_yes:
        runner.invoke(app, ["docs", "delete", "4"], catch_exceptions=False)
    assert missing_yes.value.payload.code == "CONFIRMATION_REQUIRED"

    result = runner.invoke(app, ["docs", "delete", "4", "yes=true"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["action"] == "delete"
    assert payload["data"]["deleted"] is True


def test_docs_create_update_failures_preserve_server_payload_in_error_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def create_failure(
        client: Any,
        *,
        document_bytes: bytes,
        filename: str,
        fields: dict[str, Any],
    ) -> int | str | tuple[int, int]:
        _ = (client, document_bytes, filename, fields)
        raise RuntimeError({"detail": "create rejected"})

    def update_failure(
        client: Any,
        *,
        document_id: int,
        fields: dict[str, Any],
        only_changed: bool,
    ) -> bool:
        _ = (client, document_id, fields, only_changed)
        raise RuntimeError({"detail": "update rejected"})

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_create_document_sync", create_failure)
    monkeypatch.setattr(docs_cli, "_update_document_fields_sync", update_failure)

    input_file = tmp_path / "input.pdf"
    input_file.write_bytes(b"X")

    with pytest.raises(PcliError) as create_exc:
        runner.invoke(
            app,
            ["docs", "create", f"document={input_file}", "title=Fail"],
            catch_exceptions=False,
        )
    assert create_exc.value.payload.code == "DOC_CREATE_FAILED"
    assert create_exc.value.payload.details["server_payload"] == {"detail": "create rejected"}

    with pytest.raises(PcliError) as update_exc:
        runner.invoke(
            app,
            ["docs", "update", "4", "title=Fail"],
            catch_exceptions=False,
        )
    assert update_exc.value.payload.code == "DOC_UPDATE_FAILED"
    assert update_exc.value.payload.details["server_payload"] == {"detail": "update rejected"}


def test_update_document_fields_runs_fetch_and_update_in_same_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_document(client: Any, document_id: int) -> _LoopBoundDocument:
        _ = (client, document_id)
        return _LoopBoundDocument(asyncio.get_running_loop())

    monkeypatch.setattr(docs_cli, "_fetch_document", fake_fetch_document)

    updated = docs_cli._update_document_fields_sync(
        object(),
        document_id=4,
        fields={"title": "Loop Safe"},
        only_changed=True,
    )

    assert updated is True
