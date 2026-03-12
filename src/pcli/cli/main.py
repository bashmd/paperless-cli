"""CLI entrypoint for pcli."""

from __future__ import annotations

from typing import Annotated

import typer

from pcli import __version__
from pcli.cli.auth import app as auth_app
from pcli.cli.crud_resources import CRUD_RESOURCE_SPECS, build_crud_resource_app
from pcli.cli.docs import app as docs_app
from pcli.cli.docs import docs_get
from pcli.cli.readonly_resources import READ_ONLY_RESOURCE_SPECS, build_readonly_resource_app
from pcli.core.errors import PcliError
from pcli.core.output import render_error, to_json

app = typer.Typer(
    add_completion=False,
    help="Paperless CLI for LLM-friendly retrieval and management.",
    no_args_is_help=False,
    invoke_without_command=True,
)
app.add_typer(auth_app, name="auth")
app.add_typer(docs_app, name="docs")
for crud_spec in CRUD_RESOURCE_SPECS:
    app.add_typer(build_crud_resource_app(crud_spec), name=crud_spec.cli_name)
for readonly_spec in READ_ONLY_RESOURCE_SPECS:
    app.add_typer(build_readonly_resource_app(readonly_spec), name=readonly_spec.cli_name)


@app.command(
    "get",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def get_alias(
    ctx: typer.Context,
    document_id: Annotated[
        int,
        typer.Argument(help="Document ID."),
    ],
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Options passed to docs get."),
    ] = None,
) -> None:
    """Alias for `pcli docs get`."""
    docs_get(ctx=ctx, document_id=document_id, tokens=tokens)


def _version_callback(value: bool) -> None:
    """Print version and exit for eager --version option."""
    if value:
        typer.echo(__version__)
        raise typer.Exit(code=0)


@app.callback()
def root(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            help="Show version and exit.",
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Run root CLI callback."""
    _ = version
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=0)


def main() -> None:
    """Run CLI app."""
    try:
        app(standalone_mode=False)
    except PcliError as exc:
        typer.echo(to_json(render_error(exc.payload)))
        raise SystemExit(int(exc.exit_code)) from exc
