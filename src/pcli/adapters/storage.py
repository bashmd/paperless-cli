"""Persistent storage helpers for profiles and credentials."""

from __future__ import annotations

import json
import os
import stat
import tomllib
from dataclasses import dataclass, field
from errno import ELOOP
from pathlib import Path
from typing import Any


def _xdg_config_home() -> Path:
    env_value = os.environ.get("XDG_CONFIG_HOME")
    if env_value:
        return Path(env_value).expanduser()
    return Path("~/.config").expanduser()


@dataclass(slots=True)
class StoragePaths:
    """Filesystem paths used by pcli."""

    config_dir: Path

    @property
    def config_path(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def credentials_path(self) -> Path:
        return self.config_dir / "credentials.json"

    @classmethod
    def from_env(cls) -> StoragePaths:
        """Build storage paths from environment."""
        return cls(config_dir=_xdg_config_home() / "pcli")


@dataclass(slots=True)
class ConfigData:
    """Profile config data stored as TOML."""

    active_profile: str = "default"
    profiles: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ConfigData:
        active_profile = str(payload.get("active_profile", "default"))
        raw_profiles = payload.get("profiles", {})
        profiles: dict[str, dict[str, str]] = {}
        if isinstance(raw_profiles, dict):
            for name, values in raw_profiles.items():
                if isinstance(values, dict):
                    profile_values: dict[str, str] = {}
                    if "url" in values and values["url"] is not None:
                        profile_values["url"] = str(values["url"])
                    profiles[str(name)] = profile_values
        return cls(active_profile=active_profile, profiles=profiles)

    def to_toml(self) -> str:
        """Serialize config to small TOML document."""
        lines = [f"active_profile = {_toml_quote(self.active_profile)}"]
        if self.profiles:
            lines.append("")
            lines.append("[profiles]")
            for profile_name in sorted(self.profiles):
                values = self.profiles[profile_name]
                profile_key = _toml_quote(profile_name)
                if "url" in values:
                    url_value = _toml_quote(values["url"])
                    lines.append(f"{profile_key} = {{ url = {url_value} }}")
                else:
                    lines.append(f"{profile_key} = {{}}")
        return "\n".join(lines).strip() + "\n"


@dataclass(slots=True)
class CredentialsData:
    """Credential payload stored as JSON."""

    profiles: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CredentialsData:
        raw_profiles = payload.get("profiles", {})
        profiles: dict[str, dict[str, str]] = {}
        if isinstance(raw_profiles, dict):
            for name, values in raw_profiles.items():
                if isinstance(values, dict):
                    entry: dict[str, str] = {}
                    for field_name in ("token", "username"):
                        if field_name in values and values[field_name] is not None:
                            entry[field_name] = str(values[field_name])
                    profiles[str(name)] = entry
        return cls(profiles=profiles)

    def to_dict(self) -> dict[str, Any]:
        """Serialize credentials payload."""
        return {"profiles": self.profiles}


class ConfigStore:
    """Load and save profile TOML config."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> ConfigData:
        """Load config from disk."""
        if not self.path.exists():
            return ConfigData()
        try:
            payload = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return ConfigData()
        return ConfigData.from_dict(payload)

    def save(self, data: ConfigData) -> None:
        """Save config to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(data.to_toml(), encoding="utf-8")


class CredentialStore:
    """Load and save credential data."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> CredentialsData:
        """Load credentials from disk."""
        if not self.path.exists():
            return CredentialsData()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return CredentialsData()
        if not isinstance(payload, dict):
            return CredentialsData()
        return CredentialsData.from_dict(payload)

    def save(self, data: CredentialsData) -> None:
        """Save credentials to disk and enforce restrictive permissions."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data.to_dict(), indent=2, sort_keys=True)
        if os.name == "posix":
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                fd = os.open(self.path, flags, 0o600)
            except OSError as exc:
                if exc.errno == ELOOP:
                    msg = "Credential file path must not be a symlink."
                    raise PermissionError(msg) from exc
                raise

            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode):
                os.close(fd)
                msg = "Credential file path must be a regular file."
                raise PermissionError(msg)
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(payload)
            file_mode = stat.S_IMODE(self.path.stat().st_mode)
            if file_mode != 0o600:
                os.chmod(self.path, 0o600)
                verified_mode = stat.S_IMODE(self.path.stat().st_mode)
                if verified_mode != 0o600:
                    msg = "Failed to enforce 0600 permissions on credential file."
                    raise PermissionError(msg)
            return

        self.path.write_text(payload, encoding="utf-8")


def _toml_quote(value: str) -> str:
    """Return TOML-safe quoted string."""
    return json.dumps(value)
