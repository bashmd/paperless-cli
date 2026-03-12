"""Tests for metadata/suggestions/next-asn/email document commands."""

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
class FakeModel:
    _data: dict[str, Any] = field(default_factory=dict)


def test_docs_metadata_and_suggestions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_metadata(client: Any, document_id: int) -> FakeModel:
        _ = (client, document_id)
        return FakeModel(_data={"id": 7, "original_size": 1234})

    def fake_suggestions(client: Any, document_id: int) -> FakeModel:
        _ = (client, document_id)
        return FakeModel(_data={"id": 7, "tags": [1, 2], "document_types": [3]})

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_fetch_document_metadata_sync", fake_metadata)
    monkeypatch.setattr(docs_cli, "_fetch_document_suggestions_sync", fake_suggestions)

    meta_result = runner.invoke(app, ["docs", "metadata", "7"])
    suggestions_result = runner.invoke(app, ["docs", "suggestions", "7"])
    assert meta_result.exit_code == 0
    assert suggestions_result.exit_code == 0

    meta_payload = json.loads(meta_result.output)
    suggestions_payload = json.loads(suggestions_result.output)
    assert meta_payload["action"] == "metadata"
    assert meta_payload["data"]["metadata"]["original_size"] == 1234
    assert suggestions_payload["action"] == "suggestions"
    assert suggestions_payload["data"]["suggestions"]["tags"] == [1, 2]


def test_docs_next_asn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_next_asn(client: Any) -> int:
        _ = client
        return 4321

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_fetch_next_asn_sync", fake_next_asn)

    result = runner.invoke(app, ["docs", "next-asn"])
    assert result.exit_code == 0

    payload = json.loads(result.output)
    assert payload["action"] == "next-asn"
    assert payload["data"]["next_asn"] == 4321


def test_docs_email_sends_with_required_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_send(
        client: Any,
        *,
        docs: int | list[int],
        addresses: str,
        subject: str,
        message: str,
        use_archive_version: bool,
    ) -> None:
        _ = client
        captured["docs"] = docs
        captured["addresses"] = addresses
        captured["subject"] = subject
        captured["message"] = message
        captured["use_archive_version"] = use_archive_version

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_send_document_email_sync", fake_send)

    result = runner.invoke(
        app,
        [
            "docs",
            "email",
            "docs=1,2,5",
            "to=a@example.com,b@example.com",
            "subject=Monthly report",
            "message=Attached.",
            "use_archive_version=false",
        ],
    )
    assert result.exit_code == 0
    assert captured["docs"] == [1, 2, 5]
    assert captured["addresses"] == "a@example.com,b@example.com"
    assert captured["subject"] == "Monthly report"
    assert captured["message"] == "Attached."
    assert captured["use_archive_version"] is False

    payload = json.loads(result.output)
    assert payload["action"] == "email"
    assert payload["data"]["sent"] is True
    assert payload["data"]["docs"] == [1, 2, 5]


def test_docs_email_requires_required_fields() -> None:
    with pytest.raises(UsageValidationError) as missing_docs:
        runner.invoke(
            app,
            ["docs", "email", "to=a@example.com", "subject=s", "message=m"],
            catch_exceptions=False,
        )
    assert missing_docs.value.payload.code == "MISSING_EMAIL_DOCS"

    with pytest.raises(UsageValidationError) as missing_to:
        runner.invoke(
            app,
            ["docs", "email", "docs=1", "subject=s", "message=m"],
            catch_exceptions=False,
        )
    assert missing_to.value.payload.code == "MISSING_EMAIL_TO"

    with pytest.raises(UsageValidationError) as missing_subject:
        runner.invoke(
            app,
            ["docs", "email", "docs=1", "to=a@example.com", "message=m"],
            catch_exceptions=False,
        )
    assert missing_subject.value.payload.code == "MISSING_EMAIL_SUBJECT"

    with pytest.raises(UsageValidationError) as missing_message:
        runner.invoke(
            app,
            ["docs", "email", "docs=1", "to=a@example.com", "subject=s"],
            catch_exceptions=False,
        )
    assert missing_message.value.payload.code == "MISSING_EMAIL_MESSAGE"
