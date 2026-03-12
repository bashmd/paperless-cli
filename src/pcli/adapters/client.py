"""Paperless client factory built from CLI/runtime context."""

from __future__ import annotations

import asyncio

from pypaperless import Paperless

from pcli.adapters.auth import normalize_base_url
from pcli.adapters.storage import ConfigStore, CredentialStore, StoragePaths
from pcli.core.errors import AuthFailureError, UsageValidationError
from pcli.core.options import GlobalOptions
from pcli.core.runtime import RuntimeContext, resolve_runtime_context

_OPEN_CLIENTS: list[Paperless] = []


def load_runtime_context(
    cli_options: GlobalOptions,
    *,
    paths: StoragePaths | None = None,
) -> RuntimeContext:
    """Resolve runtime context from CLI options and local profile/token stores."""
    resolved_paths = paths or StoragePaths.from_env()
    config = ConfigStore(resolved_paths.config_path).load()
    credentials = CredentialStore(resolved_paths.credentials_path).load()
    return resolve_runtime_context(cli_options, config, credentials)


def create_client(
    cli_options: GlobalOptions,
    *,
    paths: StoragePaths | None = None,
) -> tuple[Paperless, RuntimeContext]:
    """Create configured Paperless client and resolved runtime context."""
    context = load_runtime_context(cli_options, paths=paths)
    if not context.url:
        raise UsageValidationError(
            "Missing URL. Set url=<base-url>, --url, profile url, or PCLI_URL.",
            error_code="MISSING_URL",
        )
    if not context.token:
        raise AuthFailureError(
            "Missing API token. Run `pcli auth <username> <password>` or set PCLI_TOKEN.",
            error_code="AUTH_TOKEN_MISSING",
        )

    normalized_url = normalize_base_url(context.url)
    request_args: dict[str, object] | None = None
    if cli_options.timeout is not None:
        request_args = {"timeout": cli_options.timeout}

    # Runtime class is concrete; typing marks it abstract because resources are attached lazily.
    client = Paperless(normalized_url, context.token, request_args=request_args)  # type: ignore[abstract]
    _OPEN_CLIENTS.append(client)
    normalized_context = RuntimeContext(
        profile=context.profile,
        url=normalized_url,
        token=context.token,
    )
    return client, normalized_context


async def _close_client_quietly(client: Paperless) -> None:
    try:
        await client.close()
    except Exception:
        # Best-effort cleanup to avoid noisy unclosed-session warnings.
        pass


def close_open_clients_sync() -> None:
    """Close all clients created during current CLI invocation."""
    while _OPEN_CLIENTS:
        client = _OPEN_CLIENTS.pop()
        try:
            asyncio.run(_close_client_quietly(client))
        except RuntimeError:
            # Fallback for environments that already have a running event loop.
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_close_client_quietly(client))
            finally:
                loop.close()
