"""Tests for singleton resource command registration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from typer.testing import CliRunner

import pcli.cli.singleton_resources as singleton_cli
from pcli.cli.main import app
from pcli.core.errors import UsageValidationError
from pcli.core.runtime import RuntimeContext

runner = CliRunner()

SINGLETON_CASES = [
    ("status", "status"),
    ("stats", "statistics"),
    ("remote-version", "remote_version"),
]


@dataclass(slots=True)
class FakeItem:
    _data: dict[str, Any] = field(default_factory=dict)


@pytest.mark.parametrize(("resource", "helper_attr"), SINGLETON_CASES)
def test_singleton_resource_get_routes(
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
    helper_attr: str,
) -> None:
    seen_helpers: list[str] = []

    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_fetch_singleton(client: Any, *, helper_name: str) -> FakeItem:
        _ = client
        seen_helpers.append(helper_name)
        return FakeItem(_data={"id": 1, "name": "singleton"})

    monkeypatch.setattr(singleton_cli, "create_client", fake_create_client)
    monkeypatch.setattr(singleton_cli, "fetch_singleton_sync", fake_fetch_singleton)

    result = runner.invoke(app, [resource, "get"])
    assert result.exit_code == 0
    assert seen_helpers == [helper_attr]

    payload = json.loads(result.output)
    assert payload["resource"] == resource
    assert payload["action"] == "get"
    assert payload["data"]["item"]["name"] == "singleton"


def test_config_get_defaults_to_id_one_and_allows_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_ids: list[int] = []

    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_fetch_resource(
        client: Any,
        *,
        helper_name: str,
        item_id: int,
        full_perms: bool = False,
    ) -> FakeItem:
        _ = (client, helper_name, full_perms)
        seen_ids.append(item_id)
        return FakeItem(_data={"id": item_id, "name": "config"})

    monkeypatch.setattr(singleton_cli, "create_client", fake_create_client)
    monkeypatch.setattr(singleton_cli, "fetch_resource_sync", fake_fetch_resource)

    default_result = runner.invoke(app, ["config", "get"])
    override_result = runner.invoke(app, ["config", "get", "id=3"])

    assert default_result.exit_code == 0
    assert override_result.exit_code == 0
    assert seen_ids == [1, 3]

    override_payload = json.loads(override_result.output)
    assert override_payload["meta"]["id"] == 3


def test_config_get_rejects_invalid_id() -> None:
    with pytest.raises(UsageValidationError) as exc:
        runner.invoke(app, ["config", "get", "id=0"], catch_exceptions=False)
    assert exc.value.payload.code == "INVALID_ID"
