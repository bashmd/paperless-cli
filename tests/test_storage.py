"""Tests for config and credential stores."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from pcli.adapters.storage import (
    ConfigData,
    ConfigStore,
    CredentialsData,
    CredentialStore,
)


def test_config_store_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    store = ConfigStore(path)
    data = ConfigData(
        active_profile="default",
        profiles={"default": {"url": "https://paperless.local"}},
    )
    store.save(data)
    loaded = store.load()
    assert loaded.active_profile == "default"
    assert loaded.profiles["default"]["url"] == "https://paperless.local"


def test_config_store_roundtrip_with_special_profile_name(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    store = ConfigStore(path)
    profile_name = 'prod.eu "blue"'
    data = ConfigData(
        active_profile=profile_name,
        profiles={profile_name: {"url": "https://paperless.local"}},
    )
    store.save(data)
    loaded = store.load()
    assert loaded.active_profile == profile_name
    assert loaded.profiles[profile_name]["url"] == "https://paperless.local"


def test_config_store_load_invalid_toml_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("active_profile = \n[profiles", encoding="utf-8")
    store = ConfigStore(path)
    loaded = store.load()
    assert loaded.active_profile == "default"
    assert loaded.profiles == {}


def test_credential_store_roundtrip_and_permissions(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    store = CredentialStore(path)
    data = CredentialsData(
        profiles={
            "default": {
                "token": "token-value",
                "username": "alice",
            }
        }
    )
    store.save(data)
    loaded = store.load()
    assert loaded.profiles["default"]["token"] == "token-value"
    assert loaded.profiles["default"]["username"] == "alice"

    file_mode = stat.S_IMODE(path.stat().st_mode)
    assert file_mode == 0o600


def test_credential_store_load_invalid_json_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text("{not-json", encoding="utf-8")
    store = CredentialStore(path)
    loaded = store.load()
    assert loaded.profiles == {}


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX symlink semantics")
def test_credential_store_rejects_symlink_path(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    path.symlink_to(target)

    store = CredentialStore(path)
    with pytest.raises(PermissionError):
        store.save(CredentialsData(profiles={"default": {"token": "abc"}}))
