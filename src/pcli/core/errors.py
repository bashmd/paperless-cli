"""Error model for pcli."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pcli.core.exit_codes import ExitCode


@dataclass(slots=True)
class ErrorPayload:
    """Structured error payload for output adapters."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Convert payload into serializable dictionary."""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class PcliError(Exception):
    """Base exception carrying structured payload and exit code."""

    exit_code: ExitCode = ExitCode.API_SERVER_ERROR
    error_code = "UNSPECIFIED_ERROR"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.payload = ErrorPayload(
            code=error_code or self.error_code,
            message=message,
            details=details or {},
        )


class UsageValidationError(PcliError):
    """Input usage or validation failure."""

    exit_code = ExitCode.USAGE_VALIDATION_ERROR
    error_code = "USAGE_VALIDATION_ERROR"


class AuthFailureError(PcliError):
    """Authentication failure."""

    exit_code = ExitCode.AUTH_FAILURE
    error_code = "AUTH_FAILURE"


class NetworkTimeoutError(PcliError):
    """Network or timeout failure when calling remote API."""

    exit_code = ExitCode.NETWORK_TIMEOUT
    error_code = "NETWORK_TIMEOUT"
