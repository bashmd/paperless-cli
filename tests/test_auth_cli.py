"""Tests for auth CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import pcli.cli.auth as auth_cli
from pcli.adapters.auth import TokenNetworkError, TokenRequestError
from pcli.cli.main import app
from pcli.core.errors import AuthFailureError, NetworkTimeoutError, UsageValidationError

runner = CliRunner()


def test_auth_login_status_list_logout_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def fake_request_token(url: str, username: str, password: str) -> str:
        assert url == "https://paperless.local"
        assert username == "alice"
        assert password == "secret"
        return "token-123"

    monkeypatch.setattr(auth_cli, "request_api_token_sync", fake_request_token)

    login = runner.invoke(app, ["auth", "alice", "secret", "url=paperless.local"])
    assert login.exit_code == 0
    login_payload = json.loads(login.output)
    assert login_payload["ok"] is True
    assert login_payload["data"]["profile"] == "default"
    assert login_payload["data"]["token_stored"] is True

    status = runner.invoke(app, ["auth", "status"])
    assert status.exit_code == 0
    status_payload = json.loads(status.output)
    assert status_payload["data"]["has_token"] is True
    assert status_payload["data"]["url"] == "https://paperless.local"

    listed = runner.invoke(app, ["auth", "list"])
    assert listed.exit_code == 0
    list_payload = json.loads(listed.output)
    assert list_payload["data"]["profiles"][0]["profile"] == "default"

    logout = runner.invoke(app, ["auth", "logout"])
    assert logout.exit_code == 0
    logout_payload = json.loads(logout.output)
    assert logout_payload["data"]["removed"] is True


def test_auth_requires_url_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    with pytest.raises(UsageValidationError):
        runner.invoke(app, ["auth", "alice", "secret"], catch_exceptions=False)


def test_auth_failure_raises_auth_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def fake_request_token(url: str, username: str, password: str) -> str:
        _ = (url, username, password)
        raise TokenRequestError(
            code="AUTH_INVALID_CREDENTIALS",
            message="Authentication failed. Check username and password.",
            details={"reason": "invalid credentials"},
    )

    monkeypatch.setattr(auth_cli, "request_api_token_sync", fake_request_token)
    with pytest.raises(AuthFailureError):
        runner.invoke(
            app,
            ["auth", "alice", "badpass", "url=paperless.local"],
            catch_exceptions=False,
        )


def test_auth_login_supports_password_with_equals(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def fake_request_token(url: str, username: str, password: str) -> str:
        assert url == "https://paperless.local"
        assert username == "alice"
        assert password == "sec=ret"
        return "token-123"

    monkeypatch.setattr(auth_cli, "request_api_token_sync", fake_request_token)
    result = runner.invoke(app, ["auth", "alice", "sec=ret", "url=paperless.local"])
    assert result.exit_code == 0


def test_auth_explicit_login_supports_reserved_action_name_username(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def fake_request_token(url: str, username: str, password: str) -> str:
        assert url == "https://paperless.local"
        assert username == "status"
        assert password == "secret"
        return "token-123"

    monkeypatch.setattr(auth_cli, "request_api_token_sync", fake_request_token)
    result = runner.invoke(
        app,
        ["auth", "login", "status", "secret", "url=paperless.local"],
    )
    assert result.exit_code == 0


def test_auth_network_failure_raises_network_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def fake_request_token(url: str, username: str, password: str) -> str:
        _ = (url, username, password)
        raise TokenNetworkError(
            code="AUTH_NETWORK_ERROR",
            message="Unable to reach Paperless token endpoint.",
            details={"reason": "connection refused"},
        )

    monkeypatch.setattr(auth_cli, "request_api_token_sync", fake_request_token)
    with pytest.raises(NetworkTimeoutError):
        runner.invoke(
            app,
            ["auth", "alice", "secret", "url=paperless.local"],
            catch_exceptions=False,
        )


def test_auth_status_with_positional_arg_is_rejected() -> None:
    with pytest.raises(UsageValidationError) as exc:
        runner.invoke(app, ["auth", "status", "foo"], catch_exceptions=False)
    assert exc.value.payload.code == "UNEXPECTED_ARGS"
    assert "auth login status <password>" in exc.value.payload.message


def test_auth_list_with_positional_arg_is_rejected() -> None:
    with pytest.raises(UsageValidationError) as exc:
        runner.invoke(app, ["auth", "list", "foo"], catch_exceptions=False)
    assert exc.value.payload.code == "UNEXPECTED_ARGS"
    assert "auth login list <password>" in exc.value.payload.message


def test_auth_switch_action_takes_precedence_over_login_shorthand_collision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def unexpected_token_request(url: str, username: str, password: str) -> str:
        _ = (url, username, password)
        pytest.fail("switch action must not trigger auth token request")

    monkeypatch.setattr(auth_cli, "request_api_token_sync", unexpected_token_request)
    result = runner.invoke(app, ["auth", "switch", "workspace-profile"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["action"] == "switch"


def test_auth_logout_action_takes_precedence_over_login_shorthand_collision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def unexpected_token_request(url: str, username: str, password: str) -> str:
        _ = (url, username, password)
        pytest.fail("logout action must not trigger auth token request")

    monkeypatch.setattr(auth_cli, "request_api_token_sync", unexpected_token_request)
    result = runner.invoke(app, ["auth", "logout", "workspace-profile"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["action"] == "logout"
