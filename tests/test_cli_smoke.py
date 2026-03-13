"""Smoke tests for CLI bootstrap."""

from __future__ import annotations

from importlib.metadata import entry_points

from typer.testing import CliRunner

from pcli.cli.main import app

runner = CliRunner()


def test_help_works() -> None:
    """CLI help should be available."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Paperless CLI" in result.output
    assert "Quick start:" in result.output


def test_version_works() -> None:
    """CLI version option should return version."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == "0.1.0"


def test_no_args_shows_help() -> None:
    """Invoking pcli without args should show help and succeed."""
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_auth_help_includes_action_forms() -> None:
    """Auth help should explain supported invocation forms."""
    result = runner.invoke(app, ["auth", "--help"])
    assert result.exit_code == 0
    assert "Action forms:" in result.output
    assert "pcli auth <username> <password>" in result.output
    assert "pcli auth switch <profile>" in result.output


def test_console_script_entrypoint_wiring() -> None:
    """Console script should be wired to the expected callable."""
    scripts = entry_points(group="console_scripts")
    pcli_script = next(ep for ep in scripts if ep.name == "pcli")
    assert pcli_script.value == "pcli.cli.main:main"
