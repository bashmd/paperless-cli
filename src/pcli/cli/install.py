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
from urllib.parse import unquote, urlparse

import typer

from pcli.cli.io import emit_success
from pcli.core.errors import PcliError, UsageValidationError
from pcli.core.options import parse_bool
from pcli.core.parsing import parse_tokens

_INSTALL_KNOWN_OPTION_KEYS = {"from", "reinstall", "editable", "python", "rust"}


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


def _parse_rust_mode(raw_value: str | None) -> str:
    if raw_value is None:
        return "auto"
    normalized = raw_value.strip().lower()
    if normalized == "auto":
        return "auto"
    try:
        enabled = parse_bool(raw_value)
    except UsageValidationError as exc:
        raise UsageValidationError(
            "rust must be one of: auto, true, false.",
            details={"value": raw_value},
            error_code="INVALID_RUST_MODE",
        ) from exc
    return "true" if enabled else "false"


def _run_install_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    env = _uv_global_env()
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_uv_tool_dir_command(uv_bin: str) -> subprocess.CompletedProcess[str]:
    env = _uv_global_env()
    return subprocess.run(
        [uv_bin, "tool", "dir"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_rust_install_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    env = _uv_global_env()
    return subprocess.run(
        command,
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


def _resolve_tool_python(uv_bin: str) -> str | None:
    result = _run_uv_tool_dir_command(uv_bin)
    if result.returncode != 0:
        return None
    tools_dir = (result.stdout or "").strip()
    if not tools_dir:
        return None
    if os.name == "nt":
        candidate = Path(tools_dir) / "pcli" / "Scripts" / "python.exe"
    else:
        candidate = Path(tools_dir) / "pcli" / "bin" / "python"
    if not candidate.exists():
        return None
    return str(candidate)


def _derive_rust_requirement(source: str) -> str | None:
    if source.startswith(("git+", "hg+", "svn+", "bzr+")):
        if "#subdirectory=" in source:
            return source
        if "#" in source:
            return f"{source}&subdirectory=rust/pcli_rust_norm"
        return f"{source}#subdirectory=rust/pcli_rust_norm"

    local_path = _source_to_local_path(source)
    if local_path is None:
        return None
    crate_dir = local_path / "rust" / "pcli_rust_norm"
    if not crate_dir.is_dir():
        return None
    return str(crate_dir)


def _source_to_local_path(source: str) -> Path | None:
    parsed = urlparse(source)
    if parsed.scheme == "file":
        decoded = unquote(parsed.path)
        if os.name == "nt" and decoded.startswith("/") and len(decoded) > 2 and decoded[2] == ":":
            decoded = decoded[1:]
        candidate = Path(decoded)
    elif parsed.scheme:
        return None
    else:
        candidate = Path(source).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if not resolved.is_dir():
        return None
    return resolved


def _rust_toolchain_available() -> bool:
    return shutil.which("cargo") is not None and shutil.which("rustc") is not None


def _build_uv_rust_install_command(*, uv_bin: str, tool_python: str, requirement: str) -> list[str]:
    return [uv_bin, "pip", "install", "--python", tool_python, "--reinstall", requirement]


def _install_optional_rust_extension(*, source: str, uv_bin: str, mode: str) -> dict[str, Any]:
    if mode == "false":
        return {"mode": mode, "status": "skipped", "reason": "disabled"}

    if not _rust_toolchain_available():
        if mode == "true":
            raise PcliError(
                "Rust toolchain not found.",
                details={"hint": "Install Rust (cargo/rustc) or run with rust=false."},
                error_code="RUST_TOOLCHAIN_MISSING",
            )
        return {"mode": mode, "status": "skipped", "reason": "toolchain_missing"}

    requirement = _derive_rust_requirement(source)
    if requirement is None:
        if mode == "true":
            raise PcliError(
                "Could not derive Rust extension source from install source.",
                details={"source": source, "hint": "Use from=<repo-root> or a VCS source."},
                error_code="RUST_SOURCE_UNSUPPORTED",
            )
        return {"mode": mode, "status": "skipped", "reason": "source_unsupported"}

    tool_python = _resolve_tool_python(uv_bin)
    if tool_python is None:
        if mode == "true":
            raise PcliError(
                "Could not locate installed pcli tool environment.",
                details={"hint": "Try running install again or use rust=false."},
                error_code="TOOL_ENV_NOT_FOUND",
            )
        return {"mode": mode, "status": "skipped", "reason": "tool_env_missing"}

    command = _build_uv_rust_install_command(
        uv_bin=uv_bin,
        tool_python=tool_python,
        requirement=requirement,
    )
    result = _run_rust_install_command(command)
    if result.returncode != 0:
        if mode == "true":
            raise PcliError(
                "Rust extension install failed.",
                details=_failure_details(result, command=command),
                error_code="RUST_INSTALL_FAILED",
            )
        return {
            "mode": mode,
            "status": "failed",
            "reason": "install_failed",
            "details": _failure_details(result, command=command),
        }

    return {
        "mode": mode,
        "status": "installed",
        "requirement": requirement,
        "command": _shell_render(command),
    }


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
    rust: dict[str, Any],
) -> dict[str, Any]:
    executable = "pcli.exe" if os.name == "nt" else "pcli"
    default_bin = Path.home() / ".local" / "bin" / executable
    return {
        "installed": True,
        "source": source,
        "command": _shell_render(command),
        "bin_path": str(default_bin),
        "rust": rust,
    }


def install_command(
    ctx: typer.Context,
    tokens: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Install options. Supports from=..., reinstall=..., editable=..., "
                "python=..., rust=auto|true|false."
            ),
        ),
    ] = None,
) -> None:
    """Install pcli as a uv tool (default target: ~/.local/bin/pcli)."""
    updates = _parse_install_tokens([*(tokens or []), *ctx.args])
    source = _resolve_install_source(updates.get("from"))
    rust_mode = _parse_rust_mode(updates.get("rust"))
    command = _build_uv_install_command(source, updates)
    result = _run_install_command(command)
    if result.returncode != 0:
        raise PcliError(
            "Install command failed.",
            details=_failure_details(result, command=command),
            error_code="INSTALL_FAILED",
        )
    rust = _install_optional_rust_extension(source=source, uv_bin=command[0], mode=rust_mode)

    emit_success(
        resource="installer",
        action="install",
        data=_success_data(source=source, command=command, rust=rust),
    )
