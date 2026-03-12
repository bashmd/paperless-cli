"""Auth adapter around pypaperless token helper."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import aiohttp
from pypaperless import Paperless
from pypaperless.exceptions import BadJsonResponseError, JsonResponseWithError, PaperlessError


@dataclass(slots=True)
class TokenRequestError(Exception):
    """Normalized token request failure used by CLI error mapper."""

    code: str
    message: str
    details: dict[str, Any]

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True)
class TokenNetworkError(Exception):
    """Network or timeout failure while requesting token."""

    code: str
    message: str
    details: dict[str, Any]

    def __str__(self) -> str:
        return self.message


def normalize_base_url(url: str) -> str:
    """Normalize base URL to include scheme and no trailing slash."""
    cleaned = url.strip().rstrip("/")
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"
    return cleaned


async def request_api_token(url: str, username: str, password: str) -> str:
    """Request API token from Paperless."""
    normalized_url = normalize_base_url(url)
    try:
        return await Paperless.generate_api_token(normalized_url, username, password)
    except JsonResponseWithError as exc:
        raise TokenRequestError(
            code="AUTH_INVALID_CREDENTIALS",
            message="Authentication failed. Check username and password.",
            details={"reason": str(exc)},
        ) from exc
    except BadJsonResponseError as exc:
        raise TokenRequestError(
            code="AUTH_BAD_RESPONSE",
            message="Authentication endpoint returned an unexpected response.",
            details={"reason": str(exc)},
        ) from exc
    except TimeoutError as exc:
        raise TokenNetworkError(
            code="AUTH_NETWORK_TIMEOUT",
            message="Timed out while contacting Paperless token endpoint.",
            details={"reason": str(exc)},
        ) from exc
    except aiohttp.ClientError as exc:
        raise TokenNetworkError(
            code="AUTH_NETWORK_ERROR",
            message="Unable to reach Paperless token endpoint.",
            details={"reason": str(exc)},
        ) from exc
    except PaperlessError as exc:
        raise TokenRequestError(
            code="AUTH_REQUEST_FAILED",
            message="Failed to authenticate with Paperless.",
            details={"reason": str(exc)},
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive mapping
        raise TokenRequestError(
            code="AUTH_REQUEST_FAILED",
            message="Failed to authenticate with Paperless.",
            details={"reason": str(exc)},
        ) from exc


def request_api_token_sync(url: str, username: str, password: str) -> str:
    """Synchronous wrapper for token request."""
    return asyncio.run(request_api_token(url, username, password))
