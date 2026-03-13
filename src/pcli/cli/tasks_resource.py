"""Tasks resource command group."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

import typer
from pypaperless.exceptions import TaskNotFoundError

from pcli.adapters.client import create_client
from pcli.adapters.resource_handler import serialize_resource, serialize_resource_list
from pcli.cli.io import emit_success
from pcli.core.errors import UsageValidationError
from pcli.core.options import GlobalOptions
from pcli.core.parsing import parse_tokens
from pcli.core.validation import validate_raw_allowed

app = typer.Typer(
    help="Task endpoint operations (list/get).",
    add_completion=False,
    rich_markup_mode=None,
)

_TASKS_GLOBAL_KEYS = {
    "url",
    "token",
    "profile",
    "timeout",
    "format",
    "raw",
    "verbose",
}


def _parse_task_tokens(
    *,
    raw_tokens: list[str],
    command_label: str,
) -> dict[str, str]:
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=_TASKS_GLOBAL_KEYS,
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


def _parse_task_reference(raw: str) -> int | str:
    task_ref = raw.strip()
    if not task_ref:
        raise UsageValidationError(
            "task id or task_uuid is required.",
            error_code="MISSING_TASK_ID",
        )
    if task_ref.isdigit():
        task_id = int(task_ref)
        if task_id <= 0:
            raise UsageValidationError(
                "task id must be a positive integer.",
                details={"task_id": task_ref},
                error_code="INVALID_TASK_ID",
            )
        return task_id
    return task_ref


async def _list_tasks(client: Any) -> list[Any]:
    if not getattr(client, "is_initialized", False) and hasattr(client, "initialize"):
        await client.initialize()
    return [task async for task in client.tasks]


def _list_tasks_sync(client: Any) -> list[Any]:
    return asyncio.run(_list_tasks(client))


async def _fetch_task(client: Any, task_ref: int | str) -> Any:
    if not getattr(client, "is_initialized", False) and hasattr(client, "initialize"):
        await client.initialize()
    return await client.tasks(task_ref)


def _fetch_task_sync(client: Any, task_ref: int | str) -> Any:
    return asyncio.run(_fetch_task(client, task_ref))


@app.command(
    "list",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def tasks_list(
    ctx: typer.Context,
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Global options."),
    ] = None,
) -> None:
    """List tasks."""
    updates = _parse_task_tokens(
        raw_tokens=[*(tokens or []), *ctx.args],
        command_label="tasks list",
    )

    global_options = GlobalOptions.from_updates(updates)
    validate_raw_allowed(raw=global_options.raw, command_path="tasks list")
    client, runtime_context = create_client(global_options)
    items = _list_tasks_sync(client)

    emit_success(
        resource="tasks",
        action="list",
        data={"items": serialize_resource_list(items)},
        meta={"count": len(items), "profile": runtime_context.profile},
    )


@app.command(
    "get",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def tasks_get(
    ctx: typer.Context,
    task_ref: Annotated[
        str,
        typer.Argument(help="Task primary ID or task UUID."),
    ],
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Global options."),
    ] = None,
) -> None:
    """Get one task by ID or UUID."""
    updates = _parse_task_tokens(raw_tokens=[*(tokens or []), *ctx.args], command_label="tasks get")
    parsed_ref = _parse_task_reference(task_ref)

    global_options = GlobalOptions.from_updates(updates)
    validate_raw_allowed(raw=global_options.raw, command_path="tasks get")
    client, runtime_context = create_client(global_options)
    try:
        task = _fetch_task_sync(client, parsed_ref)
    except TaskNotFoundError as exc:
        raise UsageValidationError(
            "Task not found.",
            details={"task": task_ref},
            error_code="TASK_NOT_FOUND",
        ) from exc

    emit_success(
        resource="tasks",
        action="get",
        data={"item": serialize_resource(task)},
        meta={"task": task_ref, "profile": runtime_context.profile},
    )
