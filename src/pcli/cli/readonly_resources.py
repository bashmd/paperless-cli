"""Read-only resource command registration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import typer

from pcli.adapters.client import create_client
from pcli.adapters.resource_handler import (
    fetch_resource_sync,
    list_resource_sync,
    serialize_resource,
    serialize_resource_list,
)
from pcli.cli.io import emit_success
from pcli.core.errors import UsageValidationError
from pcli.core.options import GlobalOptions, parse_bool, parse_scalar
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
    "full_perms",
}
_LIST_KEYS = _GLOBAL_KEYS | {"page", "page_size"}


@dataclass(slots=True, frozen=True)
class ReadOnlyResourceSpec:
    """Mapping between CLI resource name and pypaperless helper path."""

    cli_name: str
    helper_attr: str


READ_ONLY_RESOURCE_SPECS = [
    ReadOnlyResourceSpec(cli_name="users", helper_attr="users"),
    ReadOnlyResourceSpec(cli_name="groups", helper_attr="groups"),
    ReadOnlyResourceSpec(cli_name="mail-accounts", helper_attr="mail_accounts"),
    ReadOnlyResourceSpec(cli_name="mail-rules", helper_attr="mail_rules"),
    ReadOnlyResourceSpec(cli_name="processed-mail", helper_attr="processed_mail"),
    ReadOnlyResourceSpec(cli_name="saved-views", helper_attr="saved_views"),
    ReadOnlyResourceSpec(cli_name="workflows", helper_attr="workflows"),
    ReadOnlyResourceSpec(cli_name="workflow-actions", helper_attr="workflows.actions"),
    ReadOnlyResourceSpec(cli_name="workflow-triggers", helper_attr="workflows.triggers"),
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
    passthrough_filter_mode: bool = False,
) -> tuple[dict[str, str], dict[str, str]]:
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=known_keys,
        boolean_option_keys={"raw", "verbose", "full_perms"},
        strict_boolean_values=True,
        passthrough_filter_mode=passthrough_filter_mode,
    )
    if parsed.positional or parsed.passthrough_tokens:
        raise UsageValidationError(
            f"{command_label} accepts only key=value or --option arguments.",
            details={"positional": parsed.positional, "tokens": parsed.passthrough_tokens},
            error_code="UNEXPECTED_ARGS",
        )
    return parsed.updates, parsed.passthrough_filters


def build_readonly_resource_app(spec: ReadOnlyResourceSpec) -> typer.Typer:
    """Build a Typer sub-app for read-only resources."""
    resource_app = typer.Typer(
        help=f"Inspect {spec.cli_name} read-only resources (list/get).",
        add_completion=False,
        rich_markup_mode=None,
    )

    @resource_app.command(
        "list",
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    )
    def list_cmd(
        ctx: typer.Context,
        tokens: Annotated[
            list[str] | None,
            typer.Argument(help="List options and filters."),
        ] = None,
    ) -> None:
        updates, filters = _parse_tokens_for_resource(
            raw_tokens=[*(tokens or []), *ctx.args],
            known_keys=_LIST_KEYS,
            command_label=f"{spec.cli_name} list",
            passthrough_filter_mode=True,
        )
        page = _parse_positive_int(
            value=updates.get("page"),
            default=1,
            field_name="page",
            error_code="INVALID_PAGE",
        )
        page_size = _parse_positive_int(
            value=updates.get("page_size"),
            default=150,
            field_name="page_size",
            error_code="INVALID_PAGE_SIZE",
        )

        global_options = GlobalOptions.from_updates(updates)
        validate_raw_allowed(raw=global_options.raw, command_path=f"{spec.cli_name} list")
        client, runtime_context = create_client(global_options)
        full_perms = parse_bool(updates["full_perms"]) if "full_perms" in updates else False
        page_data = list_resource_sync(
            client,
            helper_name=spec.helper_attr,
            page=page,
            page_size=page_size,
            filters=filters,
            full_perms=full_perms,
        )
        rows = serialize_resource_list(page_data.items)

        emit_success(
            resource=spec.cli_name,
            action="list",
            data={"items": rows},
            meta={
                "count": page_data.count,
                "page": page_data.page,
                "page_size": page_data.page_size,
                "next_page": page_data.next_page,
                "previous_page": page_data.previous_page,
                "profile": runtime_context.profile,
            },
        )

    @resource_app.command(
        "get",
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    )
    def get_cmd(
        ctx: typer.Context,
        resource_id: Annotated[
            int,
            typer.Argument(help="Resource ID."),
        ],
        tokens: Annotated[
            list[str] | None,
            typer.Argument(help="Global options."),
        ] = None,
    ) -> None:
        updates, _ = _parse_tokens_for_resource(
            raw_tokens=[*(tokens or []), *ctx.args],
            known_keys=_GLOBAL_KEYS,
            command_label=f"{spec.cli_name} get",
        )
        if resource_id <= 0:
            raise UsageValidationError(
                "id must be a positive integer.",
                details={"id": resource_id},
                error_code="INVALID_ID",
            )

        global_options = GlobalOptions.from_updates(updates)
        validate_raw_allowed(raw=global_options.raw, command_path=f"{spec.cli_name} get")
        client, runtime_context = create_client(global_options)
        full_perms = parse_bool(updates["full_perms"]) if "full_perms" in updates else False
        item = fetch_resource_sync(
            client,
            helper_name=spec.helper_attr,
            item_id=resource_id,
            full_perms=full_perms,
        )

        emit_success(
            resource=spec.cli_name,
            action="get",
            data={"item": serialize_resource(item)},
            meta={"id": resource_id, "profile": runtime_context.profile},
        )

    return resource_app
