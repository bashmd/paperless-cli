"""Tests for installer command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import pcli.cli.install as install_cli
from pcli.cli.main import app
from pcli.core.errors import PcliError, UsageValidationError

runner = CliRunner()


def test_install_uses_inferred_source_and_reinstall_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(install_cli, "_infer_source_from_direct_url", lambda: "file:///tmp/pcli")
    monkeypatch.setattr(
        install_cli,
        "_install_optional_rust_extension",
        lambda **_kwargs: {"mode": "auto", "status": "skipped", "reason": "toolchain_missing"},
    )

    def fake_which(name: str) -> str | None:
        if name == "uv":
            return "/usr/bin/uv"
        if name == "pcli":
            return str(Path.home() / ".local" / "bin" / "pcli")
        return None

    monkeypatch.setattr("pcli.cli.install.shutil.which", fake_which)

    called: dict[str, list[str]] = {}

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        called["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(install_cli, "_run_install_command", fake_run)

    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["action"] == "install"
    assert payload["data"]["source"] == "file:///tmp/pcli"
    assert payload["data"]["bin_path"] == str(Path.home() / ".local" / "bin" / "pcli")
    assert payload["data"]["rust"]["status"] == "skipped"
    assert "--reinstall" in called["command"]


def test_install_supports_explicit_source_and_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(install_cli, "_infer_source_from_direct_url", lambda: None)
    monkeypatch.setattr(
        install_cli,
        "_install_optional_rust_extension",
        lambda **_kwargs: {"mode": "auto", "status": "skipped", "reason": "toolchain_missing"},
    )

    def fake_which(name: str) -> str | None:
        if name == "uv":
            return "/usr/bin/uv"
        if name == "pcli":
            return "/home/test/.local/bin/pcli"
        return None

    monkeypatch.setattr("pcli.cli.install.shutil.which", fake_which)

    called: dict[str, list[str]] = {}

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        called["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(install_cli, "_run_install_command", fake_run)

    result = runner.invoke(
        app,
        [
            "install",
            "from=git+https://github.com/example/pcli.git",
            "reinstall=false",
            "editable=true",
            "python=/usr/bin/python3.12",
        ],
    )
    assert result.exit_code == 0
    command = called["command"]
    assert command[:5] == [
        "/usr/bin/uv",
        "tool",
        "install",
        "--from",
        "git+https://github.com/example/pcli.git",
    ]
    assert "--reinstall" not in command
    assert "--editable" in command
    assert "--python" in command


def test_install_supports_rust_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(install_cli, "_infer_source_from_direct_url", lambda: None)
    monkeypatch.setattr("pcli.cli.install.shutil.which", lambda _name: "/usr/bin/uv")

    called: dict[str, str] = {}

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    def fake_rust(**kwargs: str) -> dict[str, str]:
        called["mode"] = kwargs["mode"]
        return {"mode": kwargs["mode"], "status": "skipped", "reason": "disabled"}

    monkeypatch.setattr(install_cli, "_run_install_command", fake_run)
    monkeypatch.setattr(install_cli, "_install_optional_rust_extension", fake_rust)

    result = runner.invoke(app, ["install", "from=file:///tmp/pcli", "rust=false"])
    assert result.exit_code == 0
    assert called["mode"] == "false"


def test_install_requires_source_if_inference_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(install_cli, "_infer_source_from_direct_url", lambda: None)

    with pytest.raises(UsageValidationError) as exc:
        runner.invoke(app, ["install"], catch_exceptions=False)

    assert exc.value.payload.code == "MISSING_INSTALL_SOURCE"


def test_install_failure_raises_pcli_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(install_cli, "_infer_source_from_direct_url", lambda: "file:///tmp/pcli")
    monkeypatch.setattr(
        "pcli.cli.install.shutil.which",
        lambda name: "/usr/bin/uv" if name == "uv" else "/home/test/.local/bin/pcli",
    )

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 9, stdout="out", stderr="err")

    monkeypatch.setattr(install_cli, "_run_install_command", fake_run)

    with pytest.raises(PcliError) as exc:
        runner.invoke(app, ["install"], catch_exceptions=False)

    assert exc.value.payload.code == "INSTALL_FAILED"


def test_install_invalid_rust_mode_raises_usage_error() -> None:
    with pytest.raises(UsageValidationError) as exc:
        runner.invoke(
            app,
            ["install", "from=file:///tmp/pcli", "rust=maybe"],
            catch_exceptions=False,
        )
    assert exc.value.payload.code == "INVALID_RUST_MODE"


def test_uv_global_env_removes_uv_tool_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UV_TOOL_BIN_DIR", "/tmp/uvx-bin")
    monkeypatch.setenv("UV_TOOL_DIR", "/tmp/uvx-tools")
    monkeypatch.setenv("PCLI_TEST_KEEP", "1")

    env = install_cli._uv_global_env()

    assert "UV_TOOL_BIN_DIR" not in env
    assert "UV_TOOL_DIR" not in env
    assert env["PCLI_TEST_KEEP"] == "1"


def test_derive_rust_requirement_for_git_source() -> None:
    requirement = install_cli._derive_rust_requirement("git+https://example.test/pcli.git@main")
    assert requirement == "git+https://example.test/pcli.git@main#subdirectory=rust/pcli_rust_norm"


def test_derive_rust_requirement_for_local_source(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    crate = repo / "rust" / "pcli_rust_norm"
    crate.mkdir(parents=True)
    requirement = install_cli._derive_rust_requirement(str(repo))
    assert requirement == str(crate)


def test_install_optional_rust_skips_without_toolchain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(install_cli, "_rust_toolchain_available", lambda: False)
    result = install_cli._install_optional_rust_extension(
        source="file:///tmp/pcli",
        uv_bin="/usr/bin/uv",
        mode="auto",
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "toolchain_missing"
