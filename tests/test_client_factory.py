"""Tests for Paperless client factory and runtime context loading."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from pypaperless import Paperless

import pcli.adapters.client as client_factory
from pcli.adapters.client import close_open_clients_sync, create_client
from pcli.adapters.storage import (
    ConfigData,
    ConfigStore,
    CredentialsData,
    CredentialStore,
    StoragePaths,
)
from pcli.core.errors import AuthFailureError, UsageValidationError
from pcli.core.options import GlobalOptions


@pytest.fixture(autouse=True)
def _cleanup_open_clients() -> Iterator[None]:
    yield
    close_open_clients_sync()


def _write_profile_data(
    *,
    base_dir: Path,
    profile: str = "default",
    url: str | None = "https://paperless.local",
    token: str | None = "token-123",
) -> StoragePaths:
    paths = StoragePaths(config_dir=base_dir)
    config_profiles: dict[str, dict[str, str]] = {profile: {}}
    if url is not None:
        config_profiles[profile]["url"] = url

    credential_profiles: dict[str, dict[str, str]] = {profile: {}}
    if token is not None:
        credential_profiles[profile]["token"] = token

    ConfigStore(paths.config_path).save(
        ConfigData(
            active_profile=profile,
            profiles=config_profiles,
        )
    )
    CredentialStore(paths.credentials_path).save(
        CredentialsData(
            profiles=credential_profiles,
        )
    )
    return paths


def test_create_client_from_profile_store(tmp_path: Path) -> None:
    paths = _write_profile_data(base_dir=tmp_path)
    client, context = create_client(GlobalOptions(), paths=paths)
    assert isinstance(client, Paperless)
    assert context.profile == "default"
    assert context.url == "https://paperless.local"
    assert context.token == "token-123"


def test_create_client_uses_timeout_request_arg(tmp_path: Path) -> None:
    paths = _write_profile_data(base_dir=tmp_path)
    options = GlobalOptions(timeout=30)
    client, _ = create_client(options, paths=paths)
    assert client._request_args["timeout"] == 30


def test_create_client_requires_url(tmp_path: Path) -> None:
    paths = _write_profile_data(base_dir=tmp_path, url=None)
    with pytest.raises(UsageValidationError) as exc:
        create_client(GlobalOptions(), paths=paths)
    assert exc.value.payload.code == "MISSING_URL"


def test_create_client_requires_token(tmp_path: Path) -> None:
    paths = _write_profile_data(base_dir=tmp_path, token=None)
    with pytest.raises(AuthFailureError) as exc:
        create_client(GlobalOptions(), paths=paths)
    assert exc.value.payload.code == "AUTH_TOKEN_MISSING"


def test_close_open_clients_sync_clears_registered_clients() -> None:
    class _FakeClient:
        def __init__(self) -> None:
            self.close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1

    fake = _FakeClient()
    client_factory._OPEN_CLIENTS.append(fake)  # type: ignore[arg-type]
    close_open_clients_sync()
    assert fake.close_calls == 1
    assert client_factory._OPEN_CLIENTS == []
