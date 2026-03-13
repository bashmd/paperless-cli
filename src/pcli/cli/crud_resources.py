"""Generic CRUD resource command registration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

import typer

from pcli.adapters.client import create_client
from pcli.adapters.resource_handler import (
    coerce_mutation_fields,
    create_resource_sync,
    delete_resource_sync,
    fetch_resource_sync,
    list_resource_sync,
    mutation_error_details,
    require_confirmation,
    resolve_only_changed,
    serialize_resource,
    serialize_resource_list,
    update_resource_sync,
)
from pcli.cli.io import emit_success
from pcli.core.errors import PcliError, UsageValidationError
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
_UPDATE_KEYS = _GLOBAL_KEYS | {"only_changed"}
_DELETE_KEYS = _GLOBAL_KEYS | {"yes"}


@dataclass(slots=True, frozen=True)
class CrudResourceSpec:
    """Mapping between CLI resource name and pypaperless helper attribute."""

    cli_name: str
    helper_attr: str


CRUD_RESOURCE_SPECS = [
    CrudResourceSpec(cli_name="tags", helper_attr="tags"),
    CrudResourceSpec(cli_name="correspondents", helper_attr="correspondents"),
    CrudResourceSpec(cli_name="doc-types", helper_attr="document_types"),
    CrudResourceSpec(cli_name="storage-paths", helper_attr="storage_paths"),
    CrudResourceSpec(cli_name="custom-fields", helper_attr="custom_fields"),
    CrudResourceSpec(cli_name="share-links", helper_attr="share_links"),
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
    boolean_keys: set[str] | None = None,
    passthrough_filter_mode: bool = False,
) -> tuple[dict[str, str], dict[str, str]]:
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=known_keys,
        boolean_option_keys=boolean_keys or {"raw", "verbose", "full_perms"},
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


def _mutation_error_details(exc: Exception) -> dict[str, Any]:
    return mutation_error_details(exc)


def build_crud_resource_app(spec: CrudResourceSpec) -> typer.Typer:
    """Build a Typer sub-app for a CRUD resource."""
    resource_app = typer.Typer(
        help=f"Manage {spec.cli_name} resources (list/get/create/update/delete).",
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

    @resource_app.command(
        "create",
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    )
    def create_cmd(
        ctx: typer.Context,
        tokens: Annotated[
            list[str] | None,
            typer.Argument(help="Field assignments."),
        ] = None,
    ) -> None:
        updates, fields_raw = _parse_tokens_for_resource(
            raw_tokens=[*(tokens or []), *ctx.args],
            known_keys=_GLOBAL_KEYS,
            command_label=f"{spec.cli_name} create",
            passthrough_filter_mode=True,
        )
        if not fields_raw:
            raise UsageValidationError(
                f"{spec.cli_name} create requires at least one field=value assignment.",
                error_code="MISSING_CREATE_FIELDS",
            )
        fields = coerce_mutation_fields(fields_raw)

        global_options = GlobalOptions.from_updates(updates)
        validate_raw_allowed(raw=global_options.raw, command_path=f"{spec.cli_name} create")
        client, runtime_context = create_client(global_options)
        try:
            result = create_resource_sync(client, helper_name=spec.helper_attr, fields=fields)
        except Exception as exc:  # pragma: no cover - defensive mapping
            raise PcliError(
                f"{spec.cli_name} create failed.",
                details=_mutation_error_details(exc),
                error_code="RESOURCE_CREATE_FAILED",
            ) from exc

        emit_success(
            resource=spec.cli_name,
            action="create",
            data={"result": result},
            meta={"profile": runtime_context.profile},
        )

    @resource_app.command(
        "update",
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    )
    def update_cmd(
        ctx: typer.Context,
        resource_id: Annotated[
            int,
            typer.Argument(help="Resource ID."),
        ],
        tokens: Annotated[
            list[str] | None,
            typer.Argument(help="Field assignments."),
        ] = None,
    ) -> None:
        updates, fields_raw = _parse_tokens_for_resource(
            raw_tokens=[*(tokens or []), *ctx.args],
            known_keys=_UPDATE_KEYS,
            command_label=f"{spec.cli_name} update",
            passthrough_filter_mode=True,
        )
        if resource_id <= 0:
            raise UsageValidationError(
                "id must be a positive integer.",
                details={"id": resource_id},
                error_code="INVALID_ID",
            )
        if not fields_raw:
            raise UsageValidationError(
                f"{spec.cli_name} update requires at least one field=value assignment.",
                error_code="MISSING_UPDATE_FIELDS",
            )
        only_changed = resolve_only_changed(updates)
        fields = coerce_mutation_fields(fields_raw)

        global_options = GlobalOptions.from_updates(updates)
        validate_raw_allowed(raw=global_options.raw, command_path=f"{spec.cli_name} update")
        client, runtime_context = create_client(global_options)
        full_perms = parse_bool(updates["full_perms"]) if "full_perms" in updates else False
        item = fetch_resource_sync(
            client,
            helper_name=spec.helper_attr,
            item_id=resource_id,
            full_perms=full_perms,
        )
        try:
            updated = update_resource_sync(item, fields=fields, only_changed=only_changed)
        except Exception as exc:  # pragma: no cover - defensive mapping
            raise PcliError(
                f"{spec.cli_name} update failed.",
                details=_mutation_error_details(exc),
                error_code="RESOURCE_UPDATE_FAILED",
            ) from exc

        emit_success(
            resource=spec.cli_name,
            action="update",
            data={
                "updated": updated,
                "id": resource_id,
                "only_changed": only_changed,
            },
            meta={"profile": runtime_context.profile},
        )

    @resource_app.command(
        "delete",
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    )
    def delete_cmd(
        ctx: typer.Context,
        resource_id: Annotated[
            int,
            typer.Argument(help="Resource ID."),
        ],
        tokens: Annotated[
            list[str] | None,
            typer.Argument(help="Options including yes=true."),
        ] = None,
    ) -> None:
        updates, _ = _parse_tokens_for_resource(
            raw_tokens=[*(tokens or []), *ctx.args],
            known_keys=_DELETE_KEYS,
            command_label=f"{spec.cli_name} delete",
            boolean_keys={"raw", "verbose", "yes"},
        )
        if resource_id <= 0:
            raise UsageValidationError(
                "id must be a positive integer.",
                details={"id": resource_id},
                error_code="INVALID_ID",
            )
        require_confirmation(updates, command_path=f"{spec.cli_name} delete")

        global_options = GlobalOptions.from_updates(updates)
        validate_raw_allowed(raw=global_options.raw, command_path=f"{spec.cli_name} delete")
        client, runtime_context = create_client(global_options)
        full_perms = parse_bool(updates["full_perms"]) if "full_perms" in updates else False
        item = fetch_resource_sync(
            client,
            helper_name=spec.helper_attr,
            item_id=resource_id,
            full_perms=full_perms,
        )
        try:
            deleted = delete_resource_sync(item)
        except Exception as exc:  # pragma: no cover - defensive mapping
            raise PcliError(
                f"{spec.cli_name} delete failed.",
                details=_mutation_error_details(exc),
                error_code="RESOURCE_DELETE_FAILED",
            ) from exc

        emit_success(
            resource=spec.cli_name,
            action="delete",
            data={"deleted": deleted, "id": resource_id},
            meta={"profile": runtime_context.profile},
        )

    return resource_app
