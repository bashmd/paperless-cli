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
    page_count: int | None = None


def test_docs_skim_requires_query() -> None:
    with pytest.raises(UsageValidationError):
        runner.invoke(app, ["docs", "skim"], catch_exceptions=False)


def test_docs_skim_defaults_to_ripgrep_style_output(
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
                content="alpha invoice beta",
                created=dt.date(2026, 1, 1),
            )
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(app, ["docs", "skim", "query=invoice", "max_docs=1"])
    assert result.exit_code == 0
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert lines[0].startswith("1:-:")
    assert "invoice" in lines[0].lower()
    assert lines[-1].startswith("# summary ")


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
            "format=json",
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
        ["docs", "skim", "format=json", "query=invoice", "ids=9", "max_hits_per_doc=1"],
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
        ["docs", "skim", "format=json", "query=invoice", "from_stdin=true"],
        input=(
            '0\n-2\n1\n{"type":"item","id":2}\n'
            '{"type":"item","id":2.2}\n{"type":"item","id":"bad","doc_id":5}\n'
            '{"id":7}\n{"type":"error","id":99}\n{"type":"summary"}\n'
        ),
    )
    assert result.exit_code == 0
    assert captured["search"].filters["id__in"] == "1,2,5"


def test_docs_skim_from_stdin_empty_returns_empty_without_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        pytest.fail("create_client should not be called for empty stdin-only skim")

    monkeypatch.setattr(docs_cli, "create_client", fail_create_client)
    result = runner.invoke(
        app,
        ["docs", "skim", "format=json", "query=invoice", "from_stdin=true"],
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

    result = runner.invoke(app, ["docs", "skim", "format=json", "query=  invoice  "])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["meta"]["query"] == "invoice"
    assert payload["data"]["items"][0]["hit"].lower() == "invoice"


def test_docs_skim_rejects_selector_conflicts_and_raw_true() -> None:
    with pytest.raises(UsageValidationError):
        runner.invoke(
            app,
            ["docs", "skim", "format=json", "query=invoice", "ids=1", "from_stdin=true"],
            catch_exceptions=False,
        )
    with pytest.raises(UsageValidationError):
        runner.invoke(
            app,
            ["docs", "skim", "format=json", "query=invoice", "raw=true"],
            catch_exceptions=False,
        )
    with pytest.raises(UsageValidationError):
        runner.invoke(
            app,
            ["docs", "skim", "format=json", "query=invoice", "from_stdin=true", "cursor=abc"],
            input='{"type":"item","id":1}\n',
            catch_exceptions=False,
        )


def test_docs_skim_respects_budget_controls(
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
                content="invoice one invoice two",
                created=dt.date(2026, 1, 1),
                page_count=2,
            )
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    by_stop = runner.invoke(
        app,
        [
            "docs",
            "skim",
            "format=json",
            "query=invoice",
            "stop_after_matches=1",
            "max_hits_per_doc=3",
        ],
    )
    assert by_stop.exit_code == 0
    assert len(json.loads(by_stop.output)["data"]["items"]) == 1

    by_chars = runner.invoke(
        app,
        ["docs", "skim", "format=json", "query=invoice", "max_chars_total=5", "max_hits_per_doc=3"],
    )
    assert by_chars.exit_code == 0
    assert json.loads(by_chars.output)["data"]["items"] == []

    by_pages = runner.invoke(
        app,
        ["docs", "skim", "format=json", "query=invoice", "max_pages_total=1", "max_hits_per_doc=3"],
    )
    assert by_pages.exit_code == 0
    assert json.loads(by_pages.output)["data"]["items"] == []


def test_docs_skim_cursor_resume_returns_remaining_items(
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
                content="invoice one invoice two",
                created=dt.date(2026, 1, 1),
            ),
            FakeDocument(
                id=2,
                content="invoice three invoice four",
                created=dt.date(2026, 1, 2),
            ),
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    first = runner.invoke(
        app,
        ["docs", "skim", "format=json", "query=invoice", "max_hits_per_doc=2", "page_size=2"],
    )
    assert first.exit_code == 0
    first_payload = json.loads(first.output)
    assert len(first_payload["data"]["items"]) == 2
    cursor = first_payload["meta"]["next_cursor"]
    assert isinstance(cursor, str)

    second = runner.invoke(
        app,
        [
            "docs",
            "skim",
            "format=json",
            "query=invoice",
            "max_hits_per_doc=2",
            "page_size=2",
            f"cursor={cursor}",
        ],
    )
    assert second.exit_code == 0
    second_payload = json.loads(second.output)
    assert len(second_payload["data"]["items"]) == 2
    assert second_payload["meta"]["next_cursor"] is None


def test_docs_skim_cursor_mismatch_and_page_conflict_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_collect(self: Any, client: Any, search: Any) -> list[FakeDocument]:
        _ = (self, client, search)
        return [FakeDocument(id=1, content="invoice one invoice two", created=dt.date(2026, 1, 1))]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    first = runner.invoke(
        app,
        ["docs", "skim", "format=json", "query=invoice", "max_hits_per_doc=2", "page_size=1"],
    )
    cursor = json.loads(first.output)["meta"]["next_cursor"]
    assert isinstance(cursor, str)

    with pytest.raises(UsageValidationError) as mismatch:
        runner.invoke(
            app,
            [
                "docs",
                "skim",
                "query=contracts",
                "max_hits_per_doc=2",
                "page_size=1",
                f"cursor={cursor}",
            ],
            catch_exceptions=False,
        )
    assert mismatch.value.payload.code == "CURSOR_MISMATCH"

    with pytest.raises(UsageValidationError) as conflict:
        runner.invoke(
            app,
            ["docs", "skim", "format=json", "query=invoice", "cursor=abc", "page=2"],
            catch_exceptions=False,
        )
    assert conflict.value.payload.code == "CURSOR_WITH_PAGE"


def test_docs_skim_with_explicit_page_does_not_emit_resumable_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_collect(self: Any, client: Any, search: Any) -> list[FakeDocument]:
        _ = (self, client, search)
        return [
            FakeDocument(id=10, content="invoice one", created=dt.date(2026, 1, 10)),
            FakeDocument(id=11, content="invoice two", created=dt.date(2026, 1, 11)),
        ]

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(DocumentSearchAdapter, "collect_documents_sync", fake_collect)

    result = runner.invoke(
        app,
        ["docs", "skim", "format=json", "query=invoice", "page=2", "page_size=1"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["meta"]["next_cursor"] is None
