"""Tests for docs get and root get alias behavior."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from pdf_fixtures import make_pdf
from streaming_fakes import async_result
from typer.testing import CliRunner

from pcli.cli import docs as docs_cli
from pcli.cli.main import app
from pcli.core.errors import UsageValidationError
from pcli.core.runtime import RuntimeContext

runner = CliRunner()


@dataclass(slots=True)
class FakeDocument:
    id: int
    title: str
    content: str
    page_count: int | None = None
    archived_file_name: str | None = None
    original_file_name: str | None = None
    _data: dict[str, Any] = field(default_factory=dict)


def test_docs_get_returns_default_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_fetch(client: Any, document_id: int) -> FakeDocument:
        _ = client
        return FakeDocument(
            id=document_id,
            title="Invoice 42",
            content="line item total 120.00",
            page_count=3,
            _data={
                "id": document_id,
                "title": "Invoice 42",
                "content": "line item total 120.00",
                "page_count": 3,
            },
        )

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_fetch_document", async_result(fake_fetch))

    result = runner.invoke(app, ["docs", "get", "42"])
    assert result.exit_code == 0

    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["resource"] == "docs"
    assert payload["action"] == "get"
    assert payload["data"] == {
        "document": {
            "id": 42,
            "title": "Invoice 42",
            "page_count": 3,
        },
        "text": "line item total 120.00",
        "pages": None,
        "source": "ocr",
        "truncated": False,
    }
    assert payload["meta"]["id"] == 42
    assert payload["meta"]["page_count"] == 3


def test_get_chunks_are_bounded_nonduplicated_and_lossless(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "Value < 5 and > 2\n" + "\u00fc\t" * 11_000
    document = FakeDocument(
        id=1, title="Fixture", content=text, page_count=20, _data={"id": 1, "content": text}
    )
    monkeypatch.setattr(
        docs_cli,
        "create_client",
        lambda options: (object(), RuntimeContext(profile="test", url="unused", token="unused")),
    )
    monkeypatch.setattr(
        docs_cli, "_fetch_document", async_result(lambda client, document_id: document)
    )
    first = runner.invoke(app, ["get", "1"])
    payload = json.loads(first.stdout)
    assert len(payload["data"]["text"]) == 20_000
    assert "content" not in payload["data"]["document"]
    assert payload["data"]["truncated"] is True
    assert payload["meta"]["chars_total"] == len(text)
    second = runner.invoke(app, ["get", "1", f"start_char={payload['meta']['next_start']}"])
    tail = json.loads(second.stdout)
    assert payload["data"]["text"] + tail["data"]["text"] == text
    assert tail["meta"]["next_start"] is None
    assert tail["data"]["truncated"] is False
    assert document._data["content"] == text

    plain = runner.invoke(app, ["get", "1", "max_chars=8", "format=text"])
    assert plain.stdout == text[:8]
    assert "start_char=8" in plain.stderr
    full = runner.invoke(app, ["get", "1", f"max_chars={len(text)}", "format=text"])
    assert full.stdout == text
    assert full.stderr == ""


@pytest.mark.parametrize("option", ["max_chars=0", "start_char=-1", "format=ndjson", "format=rg"])
def test_get_rejects_unhonorable_bounds_or_formats(option: str) -> None:
    with pytest.raises(UsageValidationError):
        runner.invoke(app, ["get", "1", option], catch_exceptions=False)


def test_root_get_alias_matches_docs_get(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_profiles: list[str] = []

    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        profile_name = options.profile or "default"
        seen_profiles.append(profile_name)
        return object(), RuntimeContext(profile=profile_name, url="https://example", token="token")

    def fake_fetch(client: Any, document_id: int) -> FakeDocument:
        _ = client
        return FakeDocument(
            id=document_id,
            title="Receipt 9",
            content="paid in full",
            page_count=1,
            _data={
                "id": document_id,
                "title": "Receipt 9",
                "content": "paid in full",
                "page_count": 1,
            },
        )

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_fetch_document", async_result(fake_fetch))

    docs_result = runner.invoke(app, ["docs", "get", "9", "profile=docs-prof"])
    alias_result = runner.invoke(app, ["get", "9", "profile=alias-prof"])

    assert docs_result.exit_code == 0
    assert alias_result.exit_code == 0
    assert json.loads(docs_result.output)["meta"]["profile"] == "docs-prof"
    assert json.loads(alias_result.output)["meta"]["profile"] == "alias-prof"
    assert seen_profiles == ["docs-prof", "alias-prof"]


def test_docs_get_rejects_non_positive_document_id() -> None:
    with pytest.raises(UsageValidationError):
        runner.invoke(app, ["docs", "get", "0"], catch_exceptions=False)


def test_docs_get_rejects_source_ocr_with_pages() -> None:
    with pytest.raises(UsageValidationError) as exc:
        runner.invoke(
            app,
            ["docs", "get", "7", "source=ocr", "pages=1-2"],
            catch_exceptions=False,
        )
    assert exc.value.payload.code == "INVALID_SOURCE_WITH_PAGES"


def test_docs_get_auto_with_pages_falls_back_to_archive_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_fetch(client: Any, document_id: int) -> FakeDocument:
        _ = client
        return FakeDocument(
            id=document_id,
            title="Contract",
            content="ocr text",
            page_count=9,
            archived_file_name="archive.pdf",
            original_file_name="original.pdf",
            _data={"id": document_id, "title": "Contract", "content": "ocr text", "page_count": 9},
        )

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_fetch_document", async_result(fake_fetch))

    calls: list[bool] = []

    async def download(client: Any, **kwargs: Any) -> Any:
        calls.append(kwargs["original"])
        return SimpleNamespace(content=make_pdf(["First", "Second", "Third"]))

    monkeypatch.setattr(docs_cli, "_fetch_binary_document", download)
    result = runner.invoke(app, ["docs", "get", "7", "pages=1-3", "max_pages=2", "source=auto"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"]["source"] == "archive"
    assert payload["data"]["pages"] == [1, 2]
    assert payload["data"]["text"] == "First\n\f\nSecond"
    assert payload["meta"]["pages_truncated"] is True
    assert payload["meta"]["next_page"] == 3
    assert calls == [False]


def test_docs_get_auto_with_pages_falls_back_to_original_when_archive_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_fetch(client: Any, document_id: int) -> FakeDocument:
        _ = client
        return FakeDocument(
            id=document_id,
            title="Photo",
            content="ocr text",
            page_count=2,
            archived_file_name=None,
            original_file_name="scan.jpg",
            _data={"id": document_id, "title": "Photo", "content": "ocr text", "page_count": 2},
        )

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_fetch_document", async_result(fake_fetch))

    async def download(client: Any, **kwargs: Any) -> Any:
        assert kwargs["original"] is True
        return SimpleNamespace(content=b"jpeg data")

    monkeypatch.setattr(docs_cli, "_fetch_binary_document", download)
    with pytest.raises(UsageValidationError) as exc:
        runner.invoke(
            app,
            ["docs", "get", "12", "pages=2", "source=auto"],
            catch_exceptions=False,
        )
    assert exc.value.payload.code == "UNSUPPORTED_DOCUMENT_FORMAT"


def test_docs_get_returns_clear_error_when_requested_source_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_fetch(client: Any, document_id: int) -> FakeDocument:
        _ = client
        return FakeDocument(
            id=document_id,
            title="Doc",
            content="ocr text",
            page_count=1,
            archived_file_name=None,
            original_file_name=None,
            _data={"id": document_id, "title": "Doc", "content": "ocr text", "page_count": 1},
        )

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_fetch_document", async_result(fake_fetch))

    with pytest.raises(UsageValidationError) as exc:
        runner.invoke(
            app,
            ["docs", "get", "19", "pages=1", "source=auto"],
            catch_exceptions=False,
        )
    assert exc.value.payload.code == "SOURCE_UNAVAILABLE"
