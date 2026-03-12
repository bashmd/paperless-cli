"""Paperless client factory built from CLI/runtime context."""

from __future__ import annotations

from pypaperless import Paperless

from pcli.adapters.auth import normalize_base_url
from pcli.adapters.storage import ConfigStore, CredentialStore, StoragePaths
from pcli.core.errors import AuthFailureError, UsageValidationError
from pcli.core.options import GlobalOptions
from pcli.core.runtime import RuntimeContext, resolve_runtime_context


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
    normalized_context = RuntimeContext(
        profile=context.profile,
        url=normalized_url,
        token=context.token,
    )
    return client, normalized_context
