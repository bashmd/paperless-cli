"""Tests for generic read-only resource command registration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from typer.testing import CliRunner

import pcli.cli.readonly_resources as readonly_cli
from pcli.adapters.resource_handler import ListPage
from pcli.cli.main import app
from pcli.core.runtime import RuntimeContext

runner = CliRunner()

RESOURCE_CASES = [
    ("users", "users"),
    ("groups", "groups"),
    ("mail-accounts", "mail_accounts"),
    ("mail-rules", "mail_rules"),
    ("processed-mail", "processed_mail"),
    ("saved-views", "saved_views"),
    ("workflows", "workflows"),
    ("workflow-actions", "workflows.actions"),
    ("workflow-triggers", "workflows.triggers"),
]


@dataclass(slots=True)
class FakeItem:
    _data: dict[str, Any] = field(default_factory=dict)


@pytest.mark.parametrize(("resource", "helper_attr"), RESOURCE_CASES)
def test_readonly_resource_list_and_get_routes(
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
    helper_attr: str,
) -> None:
    seen_helpers: list[str] = []

    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_list_items(
        client: Any,
        *,
        helper_name: str,
        page: int,
        page_size: int,
        filters: dict[str, Any] | None = None,
        full_perms: bool = False,
    ) -> ListPage:
        _ = (client, page, page_size, filters, full_perms)
        seen_helpers.append(helper_name)
        return ListPage(
            items=[FakeItem(_data={"id": 1, "name": "x"})],
            count=1,
            page=page,
            page_size=page_size,
            next_page=None,
            previous_page=None,
        )

    def fake_get(
        client: Any,
        *,
        helper_name: str,
        item_id: int,
        full_perms: bool = False,
    ) -> FakeItem:
        _ = (client, item_id, full_perms)
        seen_helpers.append(helper_name)
        return FakeItem(_data={"id": 7, "name": "y"})

    monkeypatch.setattr(readonly_cli, "create_client", fake_create_client)
    monkeypatch.setattr(readonly_cli, "list_resource_sync", fake_list_items)
    monkeypatch.setattr(readonly_cli, "fetch_resource_sync", fake_get)

    list_result = runner.invoke(
        app,
        [resource, "list", "page=2", "page_size=1", "name__icontains=a"],
    )
    get_result = runner.invoke(app, [resource, "get", "7"])

    assert list_result.exit_code == 0
    assert get_result.exit_code == 0
    assert seen_helpers == [helper_attr, helper_attr]

    list_payload = json.loads(list_result.output)
    get_payload = json.loads(get_result.output)
    assert list_payload["resource"] == resource
    assert list_payload["action"] == "list"
    assert get_payload["action"] == "get"
    assert get_payload["data"]["item"]["id"] == 7


def test_readonly_resource_create_is_not_supported() -> None:
    result = runner.invoke(app, ["users", "create", "name=x"])
    assert result.exit_code == 2
    assert "No such command 'create'" in result.output
