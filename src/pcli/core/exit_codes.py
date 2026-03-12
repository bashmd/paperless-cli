"""CLI exit codes."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Exit code contract for pcli."""

    SUCCESS = 0
    USAGE_VALIDATION_ERROR = 2
    AUTH_FAILURE = 3
    NOT_FOUND = 4
    PERMISSION_DENIED = 5
    API_SERVER_ERROR = 6
    NETWORK_TIMEOUT = 7
