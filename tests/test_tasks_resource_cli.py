"""Tests for tasks resource commands."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from pypaperless.exceptions import TaskNotFoundError
from typer.testing import CliRunner

import pcli.cli.tasks_resource as tasks_cli
from pcli.cli.main import app
from pcli.core.errors import UsageValidationError
from pcli.core.runtime import RuntimeContext

runner = CliRunner()


@dataclass(slots=True)
class FakeItem:
    _data: dict[str, Any] = field(default_factory=dict)


def test_tasks_list_returns_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_list_tasks(client: Any) -> list[FakeItem]:
        _ = client
        return [FakeItem(_data={"id": 1, "task_id": "uuid-1"})]

    monkeypatch.setattr(tasks_cli, "create_client", fake_create_client)
    monkeypatch.setattr(tasks_cli, "_list_tasks_sync", fake_list_tasks)

    result = runner.invoke(app, ["tasks", "list"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["resource"] == "tasks"
    assert payload["action"] == "list"
    assert payload["meta"]["count"] == 1
    assert payload["data"]["items"][0]["task_id"] == "uuid-1"


def test_tasks_get_supports_int_and_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_refs: list[int | str] = []

    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_fetch_task(client: Any, task_ref: int | str) -> FakeItem:
        _ = client
        seen_refs.append(task_ref)
        return FakeItem(_data={"id": 1, "task_id": str(task_ref)})

    monkeypatch.setattr(tasks_cli, "create_client", fake_create_client)
    monkeypatch.setattr(tasks_cli, "_fetch_task_sync", fake_fetch_task)

    by_int = runner.invoke(app, ["tasks", "get", "7"])
    by_uuid = runner.invoke(app, ["tasks", "get", "task-uuid-123"])

    assert by_int.exit_code == 0
    assert by_uuid.exit_code == 0
    assert seen_refs == [7, "task-uuid-123"]


def test_tasks_get_reports_not_found_and_invalid_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_not_found(client: Any, task_ref: int | str) -> FakeItem:
        _ = (client, task_ref)
        raise TaskNotFoundError("missing")

    monkeypatch.setattr(tasks_cli, "create_client", fake_create_client)
    monkeypatch.setattr(tasks_cli, "_fetch_task_sync", fake_not_found)

    with pytest.raises(UsageValidationError) as not_found:
        runner.invoke(app, ["tasks", "get", "missing"], catch_exceptions=False)
    assert not_found.value.payload.code == "TASK_NOT_FOUND"

    with pytest.raises(UsageValidationError) as invalid:
        runner.invoke(app, ["tasks", "get", "0"], catch_exceptions=False)
    assert invalid.value.payload.code == "INVALID_TASK_ID"
