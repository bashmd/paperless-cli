"""Tests for `pcli docs facets` command behavior."""

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
    tags: list[int] | None = None
    document_type: int | None = None
    correspondent: int | None = None
    created: dt.date | None = None


def test_docs_facets_requires_query_and_by() -> None:
    with pytest.raises(UsageValidationError):
        runner.invoke(app, ["docs", "facets", "by=tags"], catch_exceptions=False)
    with pytest.raises(UsageValidationError):
        runner.invoke(app, ["docs", "facets", "query=invoice"], catch_exceptions=False)


def test_docs_facets_aggregates_requested_dimensions(
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
                tags=[1, 2],
                document_type=7,
                correspondent=11,
                created=dt.date(2024, 5, 1),
            ),
            FakeDocument(
                id=2,
                tags=[2],
                document_type=7,
                correspondent=12,
                created=dt.date(2025, 6, 2),
            ),
            FakeDocument(
                id=3,
                tags=None,
                document_type=8,
                correspondent=11,
                created=dt.date(2024, 1, 3),
            ),
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(
        app,
        [
            "docs",
            "facets",
            "query=invoice",
            "by=tags,doc_type,correspondent,year",
            "facet_scope=all",
            "top_values=2",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    facets = payload["data"]["facets"]

    assert facets["tags"] == [{"value": 2, "count": 2}, {"value": 1, "count": 1}]
    assert facets["doc_type"] == [{"value": 7, "count": 2}, {"value": 8, "count": 1}]
    assert facets["correspondent"] == [{"value": 11, "count": 2}, {"value": 12, "count": 1}]
    assert facets["year"] == [{"value": 2024, "count": 2}, {"value": 2025, "count": 1}]
    assert payload["meta"]["facet_scope"] == "all"
    assert payload["meta"]["scanned_docs"] == 3


def test_docs_facets_page_scope_limits_to_single_page_budget(
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
        [
            "docs",
            "facets",
            "query=invoice",
            "by=tags",
            "facet_scope=page",
            "page_size=5",
            "max_docs=100",
        ],
    )
    assert result.exit_code == 0
    assert captured["search"].max_docs == 5


def test_docs_facets_all_scope_uses_full_scan_default(
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
        ["docs", "facets", "query=invoice", "by=tags", "facet_scope=all", "page=3"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert captured["search"].page == 1
    assert captured["search"].max_docs == docs_cli._FACETS_ALL_MAX_DOCS
    assert payload["meta"]["max_docs"] is None


def test_docs_facets_rejects_invalid_scope_and_raw_true() -> None:
    with pytest.raises(UsageValidationError):
        runner.invoke(
            app,
            ["docs", "facets", "query=invoice", "by=tags", "facet_scope=invalid"],
            catch_exceptions=False,
        )
    with pytest.raises(UsageValidationError):
        runner.invoke(
            app,
            ["docs", "facets", "query=invoice", "by=tags", "raw=true"],
            catch_exceptions=False,
        )
