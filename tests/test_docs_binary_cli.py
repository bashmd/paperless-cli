"""Tests for docs binary endpoint commands."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import pcli.cli.docs as docs_cli
from pcli.cli.main import app
from pcli.core.errors import UsageValidationError
from pcli.core.runtime import RuntimeContext

runner = CliRunner()


@dataclass(slots=True)
class FakeBinary:
    content: bytes
    content_type: str | None = None
    disposition_filename: str | None = None


def test_docs_download_returns_json_with_base64_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_fetch(
        client: Any,
        *,
        action: str,
        document_id: int,
        original: bool,
    ) -> FakeBinary:
        _ = (client, document_id, original)
        assert action == "download"
        return FakeBinary(
            content=b"PDFDATA",
            content_type="application/pdf",
            disposition_filename="x.pdf",
        )

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_fetch_binary_document_sync", fake_fetch)

    result = runner.invoke(app, ["docs", "download", "42"])
    assert result.exit_code == 0

    payload = json.loads(result.output)
    assert payload["action"] == "download"
    assert payload["data"]["content_base64"] == base64.b64encode(b"PDFDATA").decode("ascii")
    assert payload["data"]["content_type"] == "application/pdf"
    assert payload["data"]["filename"] == "x.pdf"
    assert payload["data"]["size_bytes"] == 7


def test_docs_download_writes_output_path_when_provided(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_fetch(
        client: Any,
        *,
        action: str,
        document_id: int,
        original: bool,
    ) -> FakeBinary:
        _ = (client, action, document_id, original)
        return FakeBinary(
            content=b"PNGDATA",
            content_type="image/png",
            disposition_filename="x.png",
        )

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_fetch_binary_document_sync", fake_fetch)

    output_path = tmp_path / "preview.bin"
    result = runner.invoke(app, ["docs", "preview", "5", f"output={output_path}"])
    assert result.exit_code == 0
    assert output_path.read_bytes() == b"PNGDATA"

    payload = json.loads(result.output)
    assert payload["action"] == "preview"
    assert payload["data"]["output"] == str(output_path)
    assert payload["data"]["size_bytes"] == 7
    assert "content_base64" not in payload["data"]


def test_docs_thumbnail_raw_true_writes_bytes_to_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_fetch(
        client: Any,
        *,
        action: str,
        document_id: int,
        original: bool,
    ) -> FakeBinary:
        _ = (client, document_id, original)
        assert action == "thumbnail"
        return FakeBinary(content=b"\x00\x01\x02")

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_fetch_binary_document_sync", fake_fetch)

    result = runner.invoke(app, ["docs", "thumbnail", "8", "raw=true"])
    assert result.exit_code == 0
    assert result.stdout_bytes == b"\x00\x01\x02"


def test_docs_binary_raw_true_with_output_writes_file_without_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_fetch(
        client: Any,
        *,
        action: str,
        document_id: int,
        original: bool,
    ) -> FakeBinary:
        _ = (client, action, document_id, original)
        return FakeBinary(content=b"RAW-BYTES")

    monkeypatch.setattr(docs_cli, "create_client", fake_create_client)
    monkeypatch.setattr(docs_cli, "_fetch_binary_document_sync", fake_fetch)

    output_path = tmp_path / "download.bin"
    result = runner.invoke(
        app,
        ["docs", "download", "3", "raw=true", f"output={output_path}"],
    )
    assert result.exit_code == 0
    assert output_path.read_bytes() == b"RAW-BYTES"
    assert result.output == ""


def test_docs_binary_rejects_non_positive_document_id() -> None:
    with pytest.raises(UsageValidationError):
        runner.invoke(app, ["docs", "download", "0"], catch_exceptions=False)
