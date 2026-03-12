"""Tests for `pcli docs find` command behavior."""

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
class FakeSearchHit:
    score: float | None = None
    highlights: str | None = None
    note_highlights: str | None = None


@dataclass(slots=True)
class FakeDocument:
    id: int
    title: str
    created: dt.date
    content: str | None = None
    search_hit: FakeSearchHit | None = None


def test_docs_find_requires_query() -> None:
    with pytest.raises(UsageValidationError):
        runner.invoke(app, ["docs", "find"], catch_exceptions=False)


def test_docs_find_returns_sorted_projected_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        captured["options"] = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_collect(self: Any, client: Any, search: Any) -> list[FakeDocument]:
        _ = (self, client)
        captured["search"] = search
        return [
            FakeDocument(
                id=2,
                title="Second",
                created=dt.date(2026, 1, 2),
                search_hit=FakeSearchHit(score=0.9, highlights="Highlighted second"),
                content="unused",
            ),
            FakeDocument(
                id=1,
                title="First",
                created=dt.date(2026, 1, 1),
                search_hit=FakeSearchHit(score=0.9, highlights=None),
                content="Fallback snippet content for first document.",
            ),
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(
        app,
        [
            "docs",
            "find",
            "query=invoice",
            "top=2",
            "fields=id,title,created,score,snippet",
            "doc_type=7",
            "--correspondent__id",
            "2",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["resource"] == "docs"
    assert payload["action"] == "find"
    assert payload["meta"]["count"] == 2

    items = payload["data"]["items"]
    assert [item["id"] for item in items] == [1, 2]
    assert items[0]["created"] == "2026-01-01"
    assert items[0]["snippet"] == "Fallback snippet content for first document."
    assert items[1]["snippet"] == "Highlighted second"

    search = captured["search"]
    assert search.max_docs == 2
    assert search.filters["document_type"] == "7"
    assert search.filters["correspondent__id"] == "2"
    assert search.sort == "-score,id"


def test_docs_find_supports_long_option_style(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        captured["options"] = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_collect(self: Any, client: Any, search: Any) -> list[FakeDocument]:
        _ = (self, client)
        captured["search"] = search
        return []

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(
        app,
        ["docs", "find", "--query", "invoice", "--max_docs", "1", "--fields", "id"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["meta"]["max_docs"] == 1
    assert captured["search"].query == "invoice"
    assert captured["search"].max_docs == 1


def test_docs_find_honors_explicit_sort_without_local_resort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_collect(self: Any, client: Any, search: Any) -> list[FakeDocument]:
        _ = (self, client, search)
        return [
            FakeDocument(
                id=2,
                title="Second",
                created=dt.date(2026, 1, 2),
                search_hit=FakeSearchHit(score=0.9, highlights="Second"),
                content="",
            ),
            FakeDocument(
                id=1,
                title="First",
                created=dt.date(2026, 1, 1),
                search_hit=FakeSearchHit(score=0.9, highlights="First"),
                content="",
            ),
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(
        app,
        ["docs", "find", "query=invoice", "sort=created", "fields=id,score"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [item["id"] for item in payload["data"]["items"]] == [2, 1]


def test_docs_find_rejects_raw_true_for_non_binary_command() -> None:
    with pytest.raises(UsageValidationError):
        runner.invoke(
            app,
            ["docs", "find", "query=invoice", "raw=true"],
            catch_exceptions=False,
        )


def test_docs_find_ids_only_mode_emits_id_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_collect(self: Any, client: Any, search: Any) -> list[FakeDocument]:
        _ = (self, client, search)
        return [
            FakeDocument(
                id=10,
                title="Ten",
                created=dt.date(2026, 1, 10),
                search_hit=FakeSearchHit(score=0.9, highlights="Ten"),
                content="",
            ),
            FakeDocument(
                id=11,
                title="Eleven",
                created=dt.date(2026, 1, 11),
                search_hit=FakeSearchHit(score=0.8, highlights="Eleven"),
                content="",
            ),
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(
        app,
        ["docs", "find", "query=invoice", "ids_only=true", "fields=title,created"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["meta"]["ids_only"] is True
    assert payload["data"]["items"] == [{"id": 10}, {"id": 11}]


def test_docs_find_ids_only_mode_emits_chainable_ndjson(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_collect(self: Any, client: Any, search: Any) -> list[FakeDocument]:
        _ = (self, client, search)
        return [
            FakeDocument(
                id=22,
                title="Twenty Two",
                created=dt.date(2026, 1, 22),
                search_hit=FakeSearchHit(score=0.9, highlights="Twenty Two"),
                content="",
            ),
            FakeDocument(
                id=21,
                title="Twenty One",
                created=dt.date(2026, 1, 21),
                search_hit=FakeSearchHit(score=0.8, highlights="Twenty One"),
                content="",
            ),
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(
        app,
        ["docs", "find", "query=invoice", "ids_only=true", "format=ndjson"],
    )
    assert result.exit_code == 0

    lines = [json.loads(line) for line in result.output.splitlines() if line.strip()]
    assert lines[0] == {"type": "item", "id": 22}
    assert lines[1] == {"type": "item", "id": 21}
    assert lines[-1] == {"type": "summary", "meta": {"next_cursor": None}}


def test_docs_find_rejects_unexpected_positional_token() -> None:
    with pytest.raises(UsageValidationError):
        runner.invoke(
            app,
            ["docs", "find", "query=invoice", "unexpected"],
            catch_exceptions=False,
        )
