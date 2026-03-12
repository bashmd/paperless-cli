"""Tests for runtime context precedence."""

from __future__ import annotations

import pytest

from pcli.adapters.storage import ConfigData, CredentialsData
from pcli.core.options import GlobalOptions
from pcli.core.runtime import resolve_runtime_context


def test_cli_precedence_over_env_and_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PCLI_URL", "https://env.example")
    monkeypatch.setenv("PCLI_TOKEN", "env-token")
    monkeypatch.setenv("PCLI_PROFILE", "env")

    cli_options = GlobalOptions(url="https://cli.example", token="cli-token", profile="cli")
    config = ConfigData(active_profile="default", profiles={"cli": {"url": "https://cfg.example"}})
    creds = CredentialsData(profiles={"cli": {"token": "cfg-token"}})
    context = resolve_runtime_context(cli_options, config, creds)
    assert context.profile == "cli"
    assert context.url == "https://cli.example"
    assert context.token == "cli-token"


def test_env_precedence_over_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PCLI_URL", "https://env.example")
    monkeypatch.delenv("PCLI_TOKEN", raising=False)
    monkeypatch.setenv("PCLI_PROFILE", "env")

    cli_options = GlobalOptions()
    config = ConfigData(active_profile="default", profiles={"env": {"url": "https://cfg.example"}})
    creds = CredentialsData(profiles={"env": {"token": "cfg-token"}})
    context = resolve_runtime_context(cli_options, config, creds)
    assert context.profile == "env"
    assert context.url == "https://env.example"
    assert context.token == "cfg-token"


def test_profile_fallback_when_no_cli_or_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PCLI_URL", raising=False)
    monkeypatch.delenv("PCLI_TOKEN", raising=False)
    monkeypatch.delenv("PCLI_PROFILE", raising=False)

    cli_options = GlobalOptions()
    config = ConfigData(active_profile="default", profiles={"default": {"url": "https://cfg.example"}})
    creds = CredentialsData(profiles={"default": {"token": "cfg-token"}})
    context = resolve_runtime_context(cli_options, config, creds)
    assert context.profile == "default"
    assert context.url == "https://cfg.example"
    assert context.token == "cfg-token"
