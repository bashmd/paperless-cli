"""Paperless client factory built from CLI/runtime context."""

from __future__ import annotations

import urllib.error
import urllib.request

from pypaperless import Paperless
from pypaperless import const as pypaperless_const

from pcli.adapters.auth import normalize_base_url
from pcli.adapters.storage import ConfigStore, CredentialStore, StoragePaths
from pcli.core.errors import AuthFailureError, UsageValidationError
from pcli.core.options import GlobalOptions
from pcli.core.runtime import RuntimeContext, resolve_runtime_context

_PYPAPERLESS_JSON_INDEX = "/api/"
_PYPAPERLESS_SCHEMA_INDEX = "/api/schema/"
_DEFAULT_VERSION_PROBE_TIMEOUT_SECONDS = 3


def _apply_index_endpoint_compat() -> None:
    """Force pypaperless init probe to JSON index endpoint when needed.

    Some Paperless deployments render HTML for `/api/schema/`, which causes
    pypaperless initialization to fail because it expects JSON. Using `/api/`
    preserves initialization semantics while remaining API-compatible.
    """
    if pypaperless_const.API_PATH.get("index") == _PYPAPERLESS_SCHEMA_INDEX:
        pypaperless_const.API_PATH["index"] = _PYPAPERLESS_JSON_INDEX


def _resolve_request_api_version(
    *,
    base_url: str,
    token: str,
    timeout_seconds: int | None = None,
) -> int | None:
    """Probe host API version so older Paperless instances can initialize.

    When probing fails, return `None` to let pypaperless fall back to its default.
    """
    timeout = timeout_seconds or _DEFAULT_VERSION_PROBE_TIMEOUT_SECONDS
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{_PYPAPERLESS_JSON_INDEX}",
        headers={
            "Authorization": f"Token {token}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            header_value = response.headers.get("x-api-version")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    if header_value is None:
        return None
    try:
        parsed = int(header_value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


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
    _apply_index_endpoint_compat()
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
    request_api_version = _resolve_request_api_version(
        base_url=normalized_url,
        token=context.token,
        timeout_seconds=cli_options.timeout,
    )

    # Runtime class is concrete; typing marks it abstract because resources are attached lazily.
    client = Paperless(
        normalized_url,
        context.token,
        request_args=request_args,
        request_api_version=request_api_version,
    )  # type: ignore[abstract]
    normalized_context = RuntimeContext(
        profile=context.profile,
        url=normalized_url,
        token=context.token,
    )
    return client, normalized_context
