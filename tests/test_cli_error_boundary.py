"""Tests for CLI boundary error/exit handling."""

from __future__ import annotations

import json

import pytest

import pcli.cli.main as cli_main
from pcli.core.errors import AuthFailureError, NetworkTimeoutError, UsageValidationError


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


def test_main_maps_auth_error_to_exit_code_3(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_app(*, standalone_mode: bool = False) -> None:  # noqa: ARG001
        raise AuthFailureError(
            "Authentication failed.",
            details={"reason": "invalid credentials"},
            error_code="AUTH_INVALID_CREDENTIALS",
        )

    monkeypatch.setattr(cli_main, "app", fake_app)

    with pytest.raises(SystemExit) as exc:
        cli_main.main()

    assert exc.value.code == 3
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "AUTH_INVALID_CREDENTIALS"


def test_main_maps_network_error_to_exit_code_7(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_app(*, standalone_mode: bool = False) -> None:  # noqa: ARG001
        raise NetworkTimeoutError(
            "Network timeout.",
            details={"reason": "timed out"},
            error_code="AUTH_NETWORK_TIMEOUT",
        )

    monkeypatch.setattr(cli_main, "app", fake_app)

    with pytest.raises(SystemExit) as exc:
        cli_main.main()

    assert exc.value.code == 7
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "AUTH_NETWORK_TIMEOUT"


def test_main_always_runs_client_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_app(*, standalone_mode: bool = False) -> None:  # noqa: ARG001
        raise UsageValidationError("boom", error_code="BAD_INPUT")

    def fake_cleanup() -> None:
        calls["count"] += 1

    monkeypatch.setattr(cli_main, "app", fake_app)
    monkeypatch.setattr(cli_main, "close_open_clients_sync", fake_cleanup)

    with pytest.raises(SystemExit):
        cli_main.main()

    assert calls["count"] == 1
