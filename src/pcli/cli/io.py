"""CLI output helpers."""

from __future__ import annotations

from typing import Any

import typer

from pcli.core.output import render_success, to_json


def emit_success(
    *,
    resource: str,
    action: str,
    data: Any,
    meta: dict[str, Any] | None = None,
) -> None:
    """Emit successful response in JSON envelope mode."""
    payload = render_success(resource=resource, action=action, data=data, meta=meta)
    typer.echo(to_json(payload))
