"""Tests for CLI boundary error/exit handling."""

from __future__ import annotations

import json

import pytest

import pcli.cli.main as cli_main
from pcli.core.errors import UsageValidationError


def test_main_maps_pcli_error_to_structured_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() should map PcliError to stable JSON and exit code."""

    def fake_app(*, standalone_mode: bool = False) -> None:  # noqa: ARG001
        raise UsageValidationError(
            "Invalid input.",
            details={"field": "timeout"},
            error_code="BAD_INPUT",
        )

    monkeypatch.setattr(cli_main, "app", fake_app)

    with pytest.raises(SystemExit) as exc:
        cli_main.main()

    assert exc.value.code == 2
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "BAD_INPUT"
