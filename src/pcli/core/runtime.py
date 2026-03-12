"""Runtime context resolution for profile/env/CLI precedence."""

from __future__ import annotations

import os
from dataclasses import dataclass

from pcli.adapters.storage import ConfigData, CredentialsData
from pcli.core.options import GlobalOptions


@dataclass(slots=True)
class RuntimeContext:
    """Resolved runtime context for API operations."""

    profile: str
    url: str | None
    token: str | None


def resolve_runtime_context(
    cli_options: GlobalOptions,
    config: ConfigData,
    credentials: CredentialsData,
) -> RuntimeContext:
    """Resolve runtime settings using precedence rules.

    Precedence:
    - CLI args
    - environment: PCLI_URL/PCLI_TOKEN/PCLI_PROFILE
    - active profile
    """
    env_profile = os.environ.get("PCLI_PROFILE")
    env_url = os.environ.get("PCLI_URL")
    env_token = os.environ.get("PCLI_TOKEN")

    profile = cli_options.profile or env_profile or config.active_profile or "default"
    profile_values = config.profiles.get(profile, {})
    credential_values = credentials.profiles.get(profile, {})

    url = cli_options.url or env_url or profile_values.get("url")
    token = cli_options.token or env_token or credential_values.get("token")

    return RuntimeContext(profile=profile, url=url, token=token)
