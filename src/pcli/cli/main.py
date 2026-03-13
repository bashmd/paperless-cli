"""CLI entrypoint for pcli."""

from __future__ import annotations

from typing import Annotated

import typer

from pcli import __version__
from pcli.adapters.client import close_open_clients_sync
from pcli.cli.auth import app as auth_app
from pcli.cli.crud_resources import CRUD_RESOURCE_SPECS, build_crud_resource_app
from pcli.cli.docs import app as docs_app
from pcli.cli.docs import docs_get
from pcli.cli.install import install_command
from pcli.cli.readonly_resources import READ_ONLY_RESOURCE_SPECS, build_readonly_resource_app
from pcli.cli.singleton_resources import SINGLETON_RESOURCE_SPECS, build_singleton_resource_app
from pcli.cli.tasks_resource import app as tasks_app
from pcli.core.errors import PcliError
from pcli.core.output import render_error, to_json

_MAIN_HELP = "Paperless CLI for predictable, LLM-friendly retrieval and management."
_MAIN_EPILOG = (
    "\b\n"
    "Quick start:\n"
    "  pcli auth <username> <password> url=https://paperless.example.com\n"
    "  pcli docs find query=\"invoice acme\" max_docs=50\n"
    "  pcli docs find query=\"invoice acme\" ids_only=true format=ndjson |\n"
    "    pcli docs peek from_stdin=true\n"
    "\n"
    "Run `pcli auth --help` and `pcli docs --help` for detailed command usage."
)

app = typer.Typer(
    add_completion=False,
    help=_MAIN_HELP,
    epilog=_MAIN_EPILOG,
    no_args_is_help=False,
    invoke_without_command=True,
    rich_markup_mode=None,
)
app.add_typer(auth_app, name="auth")
app.add_typer(docs_app, name="docs")
for crud_spec in CRUD_RESOURCE_SPECS:
    app.add_typer(
        build_crud_resource_app(crud_spec),
        name=crud_spec.cli_name,
        help=f"Manage {crud_spec.cli_name} (list/get/create/update/delete).",
    )
for readonly_spec in READ_ONLY_RESOURCE_SPECS:
    app.add_typer(
        build_readonly_resource_app(readonly_spec),
        name=readonly_spec.cli_name,
        help=f"Inspect {readonly_spec.cli_name} (list/get).",
    )
for singleton_spec in SINGLETON_RESOURCE_SPECS:
    app.add_typer(
        build_singleton_resource_app(singleton_spec),
        name=singleton_spec.cli_name,
        help=f"Read {singleton_spec.cli_name} singleton data.",
    )
app.add_typer(tasks_app, name="tasks")


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


@app.command(
    "install",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def install(
    ctx: typer.Context,
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Install options."),
    ] = None,
) -> None:
    """Install pcli globally via uv tool install."""
    install_command(ctx=ctx, tokens=tokens)


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
    finally:
        close_open_clients_sync()
