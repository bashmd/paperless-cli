"""Tests for `pcli docs peek` command behavior."""

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
    title: str
    created: dt.date
    tags: list[int] | None = None
    content: str | None = None
    page_count: int | None = None


def test_docs_peek_requires_selector() -> None:
    with pytest.raises(UsageValidationError):
        runner.invoke(app, ["docs", "peek"], catch_exceptions=False)


def test_docs_peek_supports_ids_and_excerpt_truncation(
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
                title="First",
                created=dt.date(2026, 1, 1),
                content="first document preview content",
            ),
            FakeDocument(
                id=2,
                title="Second",
                created=dt.date(2026, 1, 2),
                content="second document preview content",
            ),
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(
        app,
        ["docs", "peek", "ids=2,1", "fields=id,title,excerpt", "max_chars=10"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    items = payload["data"]["items"]
    assert [item["id"] for item in items] == [2, 1]
    assert items[0]["excerpt"] == "second..."
    assert items[0]["chars"] == 9
    assert items[0]["truncated"] is True
    assert payload["meta"]["per_doc_max_chars"] == 10

    search = captured["search"]
    assert search.filters["id__in"] == "2,1"
    assert search.max_docs == 2


def test_docs_peek_supports_from_stdin_ids(
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

    stdin_payload = "\n".join(
        [
            "0",
            "-1",
            "1",
            '{"type":"item","id":2}',
            '{"type":"item","id":2.5}',
            '{"type":"item","id":"003"}',
            '{"type":"item","id":"bad","doc_id":5}',
            '{"type":"error","error":{"code":"X"}}',
            '{"type":"meta","id":42}',
            '{"type":"summary","meta":{"next_cursor":null}}',
            '{"type":"item","doc_id":3}',
            '{"id":999}',
            "not-json",
        ]
    )
    result = runner.invoke(
        app,
        ["docs", "peek", "from_stdin=true", "fields=id"],
        input=stdin_payload,
    )
    assert result.exit_code == 0
    assert captured["search"].filters["id__in"] == "1,2,3,5,3"
    payload = json.loads(result.output)
    assert payload["meta"]["from_stdin"] is True


def test_docs_peek_from_stdin_empty_source_returns_empty_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        pytest.fail("create_client should not be called for empty stdin-only peek")

    monkeypatch.setattr(docs_cli, "create_client", fail_create_client)
    result = runner.invoke(
        app,
        ["docs", "peek", "from_stdin=true"],
        input='{"type":"summary","meta":{"next_cursor":null}}\n\n',
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["data"]["items"] == []
    assert payload["meta"]["from_stdin"] is True


def test_docs_peek_from_stdin_empty_with_query_returns_empty_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        pytest.fail("create_client should not be called for empty stdin-only peek")

    monkeypatch.setattr(docs_cli, "create_client", fail_create_client)
    result = runner.invoke(
        app,
        ["docs", "peek", "from_stdin=true", "query=invoice"],
        input='{"type":"summary","meta":{"next_cursor":null}}\n',
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["data"]["items"] == []
    assert payload["meta"]["query"] == "invoice"


@pytest.mark.parametrize("max_chars", [1, 2, 3])
def test_docs_peek_small_max_chars_never_exceeds_limit(
    monkeypatch: pytest.MonkeyPatch,
    max_chars: int,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_collect(self: Any, client: Any, search: Any) -> list[FakeDocument]:
        _ = (self, client, search)
        return [
            FakeDocument(
                id=1,
                title="Doc",
                created=dt.date(2026, 1, 1),
                content="abcdef",
            )
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(
        app,
        ["docs", "peek", "ids=1", f"per_doc_max_chars={max_chars}", "fields=excerpt"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    item = payload["data"]["items"][0]
    assert len(item["excerpt"]) <= max_chars
    assert item["chars"] == len(item["excerpt"])
    assert item["truncated"] is True


def test_docs_peek_rejects_mutually_exclusive_selector_and_raw_true() -> None:
    with pytest.raises(UsageValidationError):
        runner.invoke(
            app,
            ["docs", "peek", "ids=1,2", "from_stdin=true"],
            catch_exceptions=False,
        )
    with pytest.raises(UsageValidationError):
        runner.invoke(
            app,
            ["docs", "peek", "query=invoice", "raw=true"],
            catch_exceptions=False,
        )


def test_docs_peek_respects_budget_controls(
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
                title="Doc 1",
                created=dt.date(2026, 1, 1),
                content="abcdefghij",
                page_count=2,
            ),
            FakeDocument(
                id=2,
                title="Doc 2",
                created=dt.date(2026, 1, 2),
                content="abcdefghij",
                page_count=1,
            ),
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    by_stop = runner.invoke(
        app,
        ["docs", "peek", "query=invoice", "stop_after_matches=1", "fields=id,excerpt"],
    )
    assert by_stop.exit_code == 0
    assert len(json.loads(by_stop.output)["data"]["items"]) == 1

    by_chars = runner.invoke(
        app,
        ["docs", "peek", "query=invoice", "max_chars_total=5", "fields=id,excerpt"],
    )
    assert by_chars.exit_code == 0
    assert json.loads(by_chars.output)["data"]["items"] == []

    by_pages = runner.invoke(
        app,
        ["docs", "peek", "query=invoice", "max_pages_total=1", "fields=id,excerpt"],
    )
    assert by_pages.exit_code == 0
    assert json.loads(by_pages.output)["data"]["items"] == []


def test_docs_peek_alias_precedence_prefers_per_doc_max_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_collect(self: Any, client: Any, search: Any) -> list[FakeDocument]:
        _ = (self, client, search)
        return [FakeDocument(id=1, title="Doc", created=dt.date(2026, 1, 1), content="abcdef")]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(
        app,
        [
            "docs",
            "peek",
            "ids=1",
            "per_doc_max_chars=4",
            "max_chars=10",
            "fields=excerpt",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["meta"]["per_doc_max_chars"] == 4
    assert payload["data"]["items"][0]["excerpt"] == "a..."
