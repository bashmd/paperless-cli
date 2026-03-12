"""Authentication-related CLI command."""

from __future__ import annotations

import os
from typing import Annotated

import typer

from pcli.adapters.auth import (
    TokenNetworkError,
    TokenRequestError,
    normalize_base_url,
    request_api_token_sync,
)
from pcli.adapters.storage import ConfigStore, CredentialStore, StoragePaths
from pcli.cli.io import emit_success
from pcli.core.errors import AuthFailureError, NetworkTimeoutError, UsageValidationError
from pcli.core.parsing import parse_tokens

app = typer.Typer(help="Authenticate and manage local auth profiles.", add_completion=False)


def _stores() -> tuple[ConfigStore, CredentialStore]:
    paths = StoragePaths.from_env()
    return ConfigStore(paths.config_path), CredentialStore(paths.credentials_path)


def _resolve_profile(profile_override: str | None, active_profile: str) -> str:
    return profile_override or os.environ.get("PCLI_PROFILE") or active_profile or "default"


def _resolve_url(*, url_override: str | None, profile_url: str | None) -> str:
    value = url_override or os.environ.get("PCLI_URL") or profile_url
    if value is None:
        raise UsageValidationError(
            "Missing URL. Provide url=<base-url> or set PCLI_URL.",
            error_code="MISSING_URL",
        )
    return normalize_base_url(value)


def _validate_no_passthrough(parsed_positional: list[str], passthrough_tokens: list[str]) -> None:
    if parsed_positional or passthrough_tokens:
        raise UsageValidationError(
            "Unexpected auth arguments.",
            details={
                "positional": parsed_positional,
                "tokens": passthrough_tokens,
            },
            error_code="UNEXPECTED_ARGS",
        )


def _action_login(
    *,
    username: str,
    password: str,
    url_override: str | None,
    profile_override: str | None,
) -> None:
    config_store, credential_store = _stores()
    config = config_store.load()
    credentials = credential_store.load()

    profile_name = _resolve_profile(profile_override, config.active_profile)
    profile_values = config.profiles.get(profile_name, {})
    url_value = _resolve_url(url_override=url_override, profile_url=profile_values.get("url"))

    try:
        token = request_api_token_sync(url_value, username, password)
    except TokenNetworkError as exc:
        raise NetworkTimeoutError(exc.message, details=exc.details, error_code=exc.code) from exc
    except TokenRequestError as exc:
        raise AuthFailureError(exc.message, details=exc.details, error_code=exc.code) from exc

    config.active_profile = profile_name
    config.profiles.setdefault(profile_name, {})
    config.profiles[profile_name]["url"] = url_value

    credentials.profiles.setdefault(profile_name, {})
    credentials.profiles[profile_name]["token"] = token
    credentials.profiles[profile_name]["username"] = username
    try:
        config_store.save(config)
        credential_store.save(credentials)
    except PermissionError as exc:
        raise AuthFailureError(
            "Unable to persist auth credentials due to file permission restrictions.",
            details={"reason": str(exc)},
            error_code="AUTH_STORAGE_PERMISSION_DENIED",
        ) from exc
    except OSError as exc:
        raise AuthFailureError(
            "Unable to persist auth credentials.",
            details={"reason": str(exc)},
            error_code="AUTH_STORAGE_WRITE_FAILED",
        ) from exc

    emit_success(
        resource="auth",
        action="login",
        data={
            "profile": profile_name,
            "url": url_value,
            "username": username,
            "token_stored": True,
        },
    )


def _action_status(*, profile_override: str | None) -> None:
    config_store, credential_store = _stores()
    config = config_store.load()
    credentials = credential_store.load()

    profile_name = _resolve_profile(profile_override, config.active_profile)
    profile_values = config.profiles.get(profile_name, {})
    credential_values = credentials.profiles.get(profile_name, {})

    emit_success(
        resource="auth",
        action="status",
        data={
            "active_profile": config.active_profile,
            "profile": profile_name,
            "url": profile_values.get("url"),
            "has_token": "token" in credential_values,
        },
    )


def _action_list() -> None:
    config_store, credential_store = _stores()
    config = config_store.load()
    credentials = credential_store.load()

    names = sorted(set(config.profiles.keys()) | set(credentials.profiles.keys()))
    profiles = []
    for name in names:
        profile_values = config.profiles.get(name, {})
        credential_values = credentials.profiles.get(name, {})
        profiles.append(
            {
                "profile": name,
                "active": name == config.active_profile,
                "has_url": "url" in profile_values,
                "has_token": "token" in credential_values,
            }
        )

    emit_success(resource="auth", action="list", data={"profiles": profiles})


def _action_switch(*, profile_name: str) -> None:
    config_store, _ = _stores()
    config = config_store.load()
    config.active_profile = profile_name
    config.profiles.setdefault(profile_name, {})
    config_store.save(config)

    emit_success(resource="auth", action="switch", data={"active_profile": profile_name})


def _action_logout(*, profile_override: str | None) -> None:
    config_store, credential_store = _stores()
    config = config_store.load()
    credentials = credential_store.load()

    profile_name = _resolve_profile(profile_override, config.active_profile)
    removed = credentials.profiles.pop(profile_name, None) is not None
    credential_store.save(credentials)

    emit_success(
        resource="auth",
        action="logout",
        data={"profile": profile_name, "removed": removed},
    )


@app.callback(invoke_without_command=True)
def auth_root(
    tokens: Annotated[list[str], typer.Argument(help="Action or credentials.")],
    url: Annotated[str | None, typer.Option("--url", help="Paperless base URL.")] = None,
    profile: Annotated[str | None, typer.Option("--profile", help="Profile name.")] = None,
) -> None:
    """Handle auth command in one compact parser.

    Supported forms:
    - `pcli auth <username> <password> [url=... profile=...]`
    - `pcli auth login <username> <password> [url=... profile=...]`
    - `pcli auth status [profile=...]`
    - `pcli auth list`
    - `pcli auth switch <profile>`
    - `pcli auth logout [profile=...]`
    """
    token_list = list(tokens)

    if len(token_list) == 0:
        raise UsageValidationError(
            "auth requires action or <username> <password>.",
            error_code="MISSING_AUTH_ARGS",
        )

    action = token_list[0]
    if action == "login":
        if len(token_list) < 3:
            raise UsageValidationError(
                "auth login requires <username> <password>.",
                error_code="MISSING_AUTH_ARGS",
            )
        username = token_list[1]
        password = token_list[2]
        parsed_tail = parse_tokens(token_list[3:], known_option_keys={"url", "profile"})
        _validate_no_passthrough(parsed_tail.positional, parsed_tail.passthrough_tokens)
        _action_login(
            username=username,
            password=password,
            url_override=parsed_tail.updates.get("url", url),
            profile_override=parsed_tail.updates.get("profile", profile),
        )
        return

    if action == "status":
        parsed_tail = parse_tokens(token_list[1:], known_option_keys={"profile"})
        if parsed_tail.positional:
            raise UsageValidationError(
                "auth status does not accept positional arguments. "
                "For username `status`, use `auth login status <password>`.",
                details={"args": parsed_tail.positional},
                error_code="UNEXPECTED_ARGS",
            )
        _validate_no_passthrough(parsed_tail.positional, parsed_tail.passthrough_tokens)
        _action_status(profile_override=parsed_tail.updates.get("profile", profile))
        return

    if action == "list":
        parsed_tail = parse_tokens(token_list[1:], known_option_keys=set())
        if parsed_tail.positional:
            raise UsageValidationError(
                "auth list does not accept positional arguments. "
                "For username `list`, use `auth login list <password>`.",
                details={"args": parsed_tail.positional},
                error_code="UNEXPECTED_ARGS",
            )
        _validate_no_passthrough(parsed_tail.positional, parsed_tail.passthrough_tokens)
        _action_list()
        return

    if action == "switch":
        parsed_tail = parse_tokens(token_list[1:], known_option_keys=set())
        if parsed_tail.passthrough_tokens:
            raise UsageValidationError(
                "Unexpected auth arguments.",
                details={"tokens": parsed_tail.passthrough_tokens},
                error_code="UNEXPECTED_ARGS",
            )
        if len(parsed_tail.positional) != 1:
            raise UsageValidationError(
                "auth switch requires exactly one profile argument.",
                error_code="MISSING_PROFILE",
            )
        _action_switch(profile_name=parsed_tail.positional[0])
        return

    if action == "logout":
        parsed_tail = parse_tokens(token_list[1:], known_option_keys={"profile"})
        if parsed_tail.passthrough_tokens:
            raise UsageValidationError(
                "Unexpected auth arguments.",
                details={"tokens": parsed_tail.passthrough_tokens},
                error_code="UNEXPECTED_ARGS",
            )
        if len(parsed_tail.positional) > 1:
            raise UsageValidationError(
                "auth logout accepts at most one positional profile argument.",
                error_code="UNEXPECTED_ARGS",
            )
        positional_profile = parsed_tail.positional[0] if len(parsed_tail.positional) == 1 else None
        _action_logout(
            profile_override=parsed_tail.updates.get("profile", profile) or positional_profile
        )
        return

    if len(token_list) < 2:
        raise UsageValidationError(
            "auth requires <username> <password>.",
            error_code="MISSING_AUTH_ARGS",
        )

    parsed_tail = parse_tokens(token_list[2:], known_option_keys={"url", "profile"})
    _validate_no_passthrough(parsed_tail.positional, parsed_tail.passthrough_tokens)

    _action_login(
        username=token_list[0],
        password=token_list[1],
        url_override=parsed_tail.updates.get("url", url),
        profile_override=parsed_tail.updates.get("profile", profile),
    )
