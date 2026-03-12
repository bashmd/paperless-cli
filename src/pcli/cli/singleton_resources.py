"""Singleton resource command registration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import typer

from pcli.adapters.client import create_client
from pcli.adapters.resource_handler import (
    fetch_resource_sync,
    fetch_singleton_sync,
    serialize_resource,
)
from pcli.cli.io import emit_success
from pcli.core.errors import UsageValidationError
from pcli.core.options import GlobalOptions, parse_scalar
from pcli.core.parsing import parse_tokens
from pcli.core.validation import validate_raw_allowed

_GLOBAL_KEYS = {
    "url",
    "token",
    "profile",
    "timeout",
    "format",
    "raw",
    "verbose",
}
_GLOBAL_WITH_ID_KEYS = _GLOBAL_KEYS | {"id"}


@dataclass(slots=True, frozen=True)
class SingletonResourceSpec:
    """Mapping between CLI singleton resource and helper path."""

    cli_name: str
    helper_attr: str
    supports_id: bool = False
    default_id: int | None = None


SINGLETON_RESOURCE_SPECS = [
    SingletonResourceSpec(cli_name="status", helper_attr="status"),
    SingletonResourceSpec(cli_name="stats", helper_attr="statistics"),
    SingletonResourceSpec(cli_name="config", helper_attr="config", supports_id=True, default_id=1),
    SingletonResourceSpec(cli_name="remote-version", helper_attr="remote_version"),
]


def _parse_positive_int(
    *,
    value: str | None,
    default: int,
    field_name: str,
    error_code: str,
) -> int:
    if value is None:
        return default
    parsed = parse_scalar(value)
    if not isinstance(parsed, int) or isinstance(parsed, bool) or parsed <= 0:
        raise UsageValidationError(
            f"{field_name} must be a positive integer.",
            details={"value": value},
            error_code=error_code,
        )
    return parsed


def _parse_tokens_for_resource(
    *,
    raw_tokens: list[str],
    known_keys: set[str],
    command_label: str,
) -> dict[str, str]:
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=known_keys,
        boolean_option_keys={"raw", "verbose"},
        strict_boolean_values=True,
    )
    if parsed.positional or parsed.passthrough_tokens or parsed.passthrough_filters:
        raise UsageValidationError(
            f"{command_label} accepts only key=value or --option arguments.",
            details={
                "positional": parsed.positional,
                "tokens": parsed.passthrough_tokens,
                "filters": parsed.passthrough_filters,
            },
            error_code="UNEXPECTED_ARGS",
        )
    return parsed.updates


def build_singleton_resource_app(spec: SingletonResourceSpec) -> typer.Typer:
    """Build a Typer sub-app for singleton resources."""
    resource_app = typer.Typer(
        help=f"{spec.cli_name} singleton resource commands.",
        add_completion=False,
    )

    @resource_app.command(
        "get",
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    )
    def get_cmd(
        ctx: typer.Context,
        tokens: Annotated[
            list[str] | None,
            typer.Argument(help="Global options."),
        ] = None,
    ) -> None:
        known_keys = _GLOBAL_WITH_ID_KEYS if spec.supports_id else _GLOBAL_KEYS
        updates = _parse_tokens_for_resource(
            raw_tokens=[*(tokens or []), *ctx.args],
            known_keys=known_keys,
            command_label=f"{spec.cli_name} get",
        )

        data_id: int | None = None
        if spec.supports_id:
            if spec.default_id is None:
                raise UsageValidationError(
                    "Resource spec missing default id for id-enabled singleton.",
                    details={"resource": spec.cli_name},
                    error_code="INVALID_RESOURCE_SPEC",
                )
            data_id = _parse_positive_int(
                value=updates.get("id"),
                default=spec.default_id,
                field_name="id",
                error_code="INVALID_ID",
            )

        global_options = GlobalOptions.from_updates(updates)
        validate_raw_allowed(raw=global_options.raw, command_path=f"{spec.cli_name} get")
        client, runtime_context = create_client(global_options)

        if data_id is not None:
            item = fetch_resource_sync(client, helper_name=spec.helper_attr, item_id=data_id)
        else:
            item = fetch_singleton_sync(client, helper_name=spec.helper_attr)

        meta: dict[str, str | int] = {"profile": runtime_context.profile}
        if data_id is not None:
            meta["id"] = data_id

        emit_success(
            resource=spec.cli_name,
            action="get",
            data={"item": serialize_resource(item)},
            meta=meta,
        )

    return resource_app
