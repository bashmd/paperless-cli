"""Translate known transport and dependency failures without exposing request headers."""

import aiohttp
import click
from pypaperless.exceptions import (
    ItemNotFoundError,
    PaperlessAuthError,
    PaperlessConnectionError,
    PaperlessError,
    PaperlessForbiddenError,
    TaskNotFoundError,
)

from pcli.core.errors import PcliError
from pcli.core.exit_codes import ExitCode


def normalize_error(exc: Exception) -> PcliError:
    if isinstance(exc, PcliError):
        return exc
    status = exc.status if isinstance(exc, aiohttp.ClientResponseError) else None
    if isinstance(exc, click.ClickException):
        code, message, exit_code = (
            "INVALID_ARGUMENTS",
            exc.format_message(),
            ExitCode.USAGE_VALIDATION_ERROR,
        )
    elif isinstance(exc, PaperlessAuthError) or status == 401:
        code, message, exit_code = "AUTH_FAILURE", "Authentication failed.", ExitCode.AUTH_FAILURE
    elif isinstance(exc, PaperlessForbiddenError) or status == 403:
        code, message, exit_code = (
            "PERMISSION_DENIED",
            "Permission denied.",
            ExitCode.PERMISSION_DENIED,
        )
    elif isinstance(exc, (ItemNotFoundError, TaskNotFoundError)) or status == 404:
        code, message, exit_code = "NOT_FOUND", "Resource not found.", ExitCode.NOT_FOUND
    elif isinstance(exc, (TimeoutError, aiohttp.ClientConnectionError, PaperlessConnectionError)):
        code, message, exit_code = (
            "NETWORK_ERROR",
            "Could not reach Paperless or request timed out.",
            ExitCode.NETWORK_TIMEOUT,
        )
    else:
        code, message, exit_code = (
            "API_REQUEST_FAILED",
            "Paperless request failed.",
            ExitCode.API_SERVER_ERROR,
        )
    error = PcliError(message, error_code=code, details={"status": status} if status else {})
    error.exit_code = exit_code
    return error


REQUEST_ERRORS = (PaperlessError, aiohttp.ClientError, TimeoutError, click.ClickException)
