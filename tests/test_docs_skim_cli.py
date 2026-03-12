"""Tests for `pcli docs skim` command behavior."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any

import pytest
from typer.testing import CliRunner

import pcli.cli.docs as docs_cli
from pcli.adapters.document_search import DocumentSearchAdapter
from pcli.cli.main import app
from pcli.core.errors import UsageValidationError
from pcli.core.runtime import RuntimeContext

runner = CliRunner()


@dataclass(slots=True)
class FakeDocument:
    id: int
    content: str
    created: dt.date


def test_docs_skim_requires_query() -> None:
    with pytest.raises(UsageValidationError):
        runner.invoke(app, ["docs", "skim"], catch_exceptions=False)


def test_docs_skim_extracts_hits_with_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_collect(self: Any, client: Any, search: Any) -> list[FakeDocument]:
        _ = (self, client, search)
        return [
            FakeDocument(
                id=1,
                content="alpha invoice beta invoice gamma",
                created=dt.date(2026, 1, 1),
            )
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(
        app,
        [
            "docs",
            "skim",
            "query=invoice",
            "context_before=2",
            "context_after=3",
            "max_hits_per_doc=2",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    items = payload["data"]["items"]
    assert len(items) == 2
    assert items[0]["doc_id"] == 1
    assert items[0]["page"] is None
    assert items[0]["hit"].lower() == "invoice"
    assert "invoice" in items[0]["text"].lower()
    assert payload["meta"]["docs_with_hits"] == 1
    assert payload["meta"]["count"] == 2


def test_docs_skim_limits_hits_per_doc_and_applies_ids_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_collect(self: Any, client: Any, search: Any) -> list[FakeDocument]:
        _ = (self, client)
        captured["search"] = search
        return [
            FakeDocument(
                id=9,
                content="invoice one invoice two",
                created=dt.date(2026, 1, 1),
            )
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(
        app,
        ["docs", "skim", "query=invoice", "ids=9", "max_hits_per_doc=1"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload["data"]["items"]) == 1
    assert captured["search"].filters["id__in"] == "9"
    assert captured["search"].max_docs == 1


def test_docs_skim_supports_from_stdin_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_collect(self: Any, client: Any, search: Any) -> list[FakeDocument]:
        _ = (self, client)
        captured["search"] = search
        return []

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(
        app,
        ["docs", "skim", "query=invoice", "from_stdin=true"],
        input='1\n{"id":2}\n',
    )
    assert result.exit_code == 0
    assert captured["search"].filters["id__in"] == "1,2"


def test_docs_skim_from_stdin_empty_returns_empty_without_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        pytest.fail("create_client should not be called for empty stdin-only skim")

    monkeypatch.setattr(docs_cli, "create_client", fail_create_client)
    result = runner.invoke(
        app,
        ["docs", "skim", "query=invoice", "from_stdin=true"],
        input='{"type":"summary","meta":{"next_cursor":null}}\n\n',
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["data"]["items"] == []
    assert payload["meta"]["docs_scanned"] == 0


def test_docs_skim_uses_trimmed_query_for_local_hit_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_collect(self: Any, client: Any, search: Any) -> list[FakeDocument]:
        _ = (self, client, search)
        return [FakeDocument(id=1, content="invoice", created=dt.date(2026, 1, 1))]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(app, ["docs", "skim", "query=  invoice  "])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["meta"]["query"] == "invoice"
    assert payload["data"]["items"][0]["hit"].lower() == "invoice"


def test_docs_skim_rejects_selector_conflicts_and_raw_true() -> None:
    with pytest.raises(UsageValidationError):
        runner.invoke(
            app,
            ["docs", "skim", "query=invoice", "ids=1", "from_stdin=true"],
            catch_exceptions=False,
        )
    with pytest.raises(UsageValidationError):
        runner.invoke(
            app,
            ["docs", "skim", "query=invoice", "raw=true"],
            catch_exceptions=False,
        )
