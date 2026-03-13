"""Installer command for one-shot uv tool installation."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Annotated, Any

import typer

from pcli.cli.io import emit_success
from pcli.core.errors import PcliError, UsageValidationError
from pcli.core.options import parse_bool
from pcli.core.parsing import parse_tokens

_INSTALL_KNOWN_OPTION_KEYS = {"from", "reinstall", "editable", "python"}


def _resolve_install_source(explicit_source: str | None) -> str:
    if explicit_source is not None and explicit_source.strip():
        return explicit_source.strip()

    inferred = _infer_source_from_direct_url()
    if inferred:
        return inferred

    raise UsageValidationError(
        "install requires from=<source> when package source cannot be inferred.",
        details={
            "hint": "Use uv tool install --from <source> pcli or pass from=<source>.",
        },
        error_code="MISSING_INSTALL_SOURCE",
    )


def _infer_source_from_direct_url() -> str | None:
    try:
        dist = metadata.distribution("pcli")
    except metadata.PackageNotFoundError:
        return None

    direct_url_path = Path(str(dist.locate_file("direct_url.json")))
    if not direct_url_path.exists():
        return None

    try:
        payload = json.loads(direct_url_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    url_value = payload.get("url")
    if not isinstance(url_value, str) or not url_value.strip():
        return None
    source = url_value.strip()

    vcs_info = payload.get("vcs_info")
    if isinstance(vcs_info, dict):
        vcs = vcs_info.get("vcs")
        requested_revision = vcs_info.get("requested_revision")
        if isinstance(vcs, str) and vcs and not source.startswith(f"{vcs}+"):
            source = f"{vcs}+{source}"
        if (
            isinstance(requested_revision, str)
            and requested_revision
            and "@" not in source
            and source.startswith(("git+", "hg+", "svn+", "bzr+"))
        ):
            source = f"{source}@{requested_revision}"
    return source


def _parse_install_tokens(raw_tokens: list[str]) -> dict[str, str]:
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=_INSTALL_KNOWN_OPTION_KEYS,
        boolean_option_keys={"reinstall", "editable"},
        strict_boolean_values=True,
    )
    if parsed.positional or parsed.passthrough_tokens or parsed.passthrough_filters:
        raise UsageValidationError(
            "install accepts only key=value or --option arguments.",
            details={
                "positional": parsed.positional,
                "tokens": parsed.passthrough_tokens,
                "filters": parsed.passthrough_filters,
            },
            error_code="UNEXPECTED_ARGS",
        )
    return parsed.updates


def _build_uv_install_command(source: str, updates: dict[str, str]) -> list[str]:
    uv_bin = shutil.which("uv")
    if uv_bin is None:
        raise PcliError(
            "uv executable not found in PATH.",
            details={"hint": "Install uv first: https://docs.astral.sh/uv/"},
            error_code="UV_NOT_FOUND",
        )

    command = [uv_bin, "tool", "install", "--from", source, "pcli"]
    reinstall = parse_bool(updates["reinstall"]) if "reinstall" in updates else True
    if reinstall:
        command.append("--reinstall")
    editable = parse_bool(updates["editable"]) if "editable" in updates else False
    if editable:
        command.append("--editable")
    python_value = updates.get("python")
    if python_value:
        command.extend(["--python", python_value])
    return command


def _run_install_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    env = _uv_global_env()
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_uv_tool_dir(uv_bin: str) -> subprocess.CompletedProcess[str]:
    env = _uv_global_env()
    return subprocess.run(
        [uv_bin, "tool", "dir", "--bin"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _shell_render(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _uv_global_env() -> dict[str, str]:
    env = dict(os.environ)
    # `uvx` sets these to its own tool/bin paths; clear them so installation
    # targets the user's normal uv tool location.
    env.pop("UV_TOOL_BIN_DIR", None)
    env.pop("UV_TOOL_DIR", None)
    return env


def _failure_details(
    result: subprocess.CompletedProcess[str],
    *,
    command: list[str],
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "returncode": int(result.returncode),
        "command": _shell_render(command),
    }
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    if stderr:
        details["stderr"] = stderr[-4000:]
    if stdout:
        details["stdout"] = stdout[-2000:]
    return details


def _success_data(
    *,
    source: str,
    command: list[str],
) -> dict[str, Any]:
    executable = "pcli.exe" if os.name == "nt" else "pcli"
    default_bin = Path.home() / ".local" / "bin" / executable
    bin_path = str(default_bin)
    uv_bin = command[0] if command else ""
    if uv_bin:
        tool_dir_result = _run_uv_tool_dir(uv_bin)
        if tool_dir_result.returncode == 0:
            candidate_dir = (tool_dir_result.stdout or "").strip()
            if candidate_dir:
                bin_path = str((Path(candidate_dir).expanduser() / executable).resolve())
    return {
        "installed": True,
        "source": source,
        "command": _shell_render(command),
        "bin_path": bin_path,
    }


def install_command(
    ctx: typer.Context,
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Install options. Supports from=..., reinstall=..., editable=...."),
    ] = None,
) -> None:
    """Install pcli as a uv tool (default target: ~/.local/bin/pcli)."""
    updates = _parse_install_tokens([*(tokens or []), *ctx.args])
    source = _resolve_install_source(updates.get("from"))
    command = _build_uv_install_command(source, updates)
    result = _run_install_command(command)
    if result.returncode != 0:
        raise PcliError(
            "Install command failed.",
            details=_failure_details(result, command=command),
            error_code="INSTALL_FAILED",
        )

    emit_success(
        resource="installer",
        action="install",
        data=_success_data(source=source, command=command),
    )
