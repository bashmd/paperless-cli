"""Tests for docs list/search/more-like command behavior."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
    title: str
    content: str
    _data: dict[str, Any] = field(default_factory=dict)


def test_docs_list_passes_query_and_filters(
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
                id=1,
                title="Invoice A",
                content="...",
                _data={"id": 1, "title": "Invoice A", "content": "..."},
            )
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(
        app,
        [
            "docs",
            "list",
            "query=invoice",
            "page=2",
            "page_size=5",
            "document_type=7",
            "sort=title",
        ],
    )
    assert result.exit_code == 0

    search = captured["search"]
    assert search.query == "invoice"
    assert search.page == 2
    assert search.page_size == 5
    assert search.max_docs == 5
    assert search.sort == "title"
    assert search.filters["document_type"] == "7"

    payload = json.loads(result.output)
    assert payload["action"] == "list"
    assert payload["meta"]["count"] == 1
    assert payload["data"]["items"][0]["id"] == 1


def test_docs_search_uses_positional_query(
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
                id=2,
                title="Reminder",
                content="late fee",
                _data={"id": 2, "title": "Reminder", "content": "late fee"},
            )
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(
        app,
        ["docs", "search", "late fee", "page_size=3", "correspondent__id=2"],
    )
    assert result.exit_code == 0

    search = captured["search"]
    assert search.query == "late fee"
    assert search.page_size == 3
    assert search.max_docs == 3
    assert search.filters["correspondent__id"] == "2"

    payload = json.loads(result.output)
    assert payload["action"] == "search"
    assert payload["meta"]["query"] == "late fee"


def test_docs_more_like_adds_more_like_filter(
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
        ["docs", "more-like", "11", "page=3", "page_size=4"],
    )
    assert result.exit_code == 0

    search = captured["search"]
    assert search.page == 3
    assert search.page_size == 4
    assert search.max_docs == 4
    assert search.filters["more_like_id"] == 11

    payload = json.loads(result.output)
    assert payload["action"] == "more-like"
    assert payload["meta"]["document_id"] == 11


def test_docs_more_like_rejects_non_positive_document_id() -> None:
    with pytest.raises(UsageValidationError):
        runner.invoke(app, ["docs", "more-like", "0"], catch_exceptions=False)
