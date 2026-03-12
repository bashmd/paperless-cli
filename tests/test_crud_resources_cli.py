"""Tests for generic CRUD resource command registration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from typer.testing import CliRunner

import pcli.cli.crud_resources as crud_cli
from pcli.adapters.resource_handler import ListPage
from pcli.cli.main import app
from pcli.core.errors import UsageValidationError
from pcli.core.runtime import RuntimeContext

runner = CliRunner()

RESOURCE_CASES = [
    ("tags", "tags"),
    ("correspondents", "correspondents"),
    ("doc-types", "document_types"),
    ("storage-paths", "storage_paths"),
    ("custom-fields", "custom_fields"),
    ("share-links", "share_links"),
]


@dataclass(slots=True)
class FakeItem:
    _data: dict[str, Any] = field(default_factory=dict)


@pytest.mark.parametrize(("resource", "helper_attr"), RESOURCE_CASES)
def test_crud_resource_list_and_get_routes(
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
    helper_attr: str,
) -> None:
    seen_helpers: list[str] = []
    seen_full_perms: list[bool] = []

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
        _ = client
        seen_helpers.append(helper_name)
        seen_full_perms.append(full_perms)
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
        _ = (client, item_id)
        seen_helpers.append(helper_name)
        seen_full_perms.append(full_perms)
        return FakeItem(_data={"id": 7, "name": "y"})

    monkeypatch.setattr(crud_cli, "create_client", fake_create_client)
    monkeypatch.setattr(crud_cli, "list_resource_sync", fake_list_items)
    monkeypatch.setattr(crud_cli, "fetch_resource_sync", fake_get)

    list_result = runner.invoke(
        app,
        [resource, "list", "page=2", "page_size=1", "name__icontains=a", "full_perms=true"],
    )
    get_result = runner.invoke(app, [resource, "get", "7", "full_perms=true"])

    assert list_result.exit_code == 0
    assert get_result.exit_code == 0
    assert seen_helpers == [helper_attr, helper_attr]
    assert seen_full_perms == [True, True]

    list_payload = json.loads(list_result.output)
    get_payload = json.loads(get_result.output)
    assert list_payload["resource"] == resource
    assert list_payload["action"] == "list"
    assert get_payload["action"] == "get"
    assert get_payload["data"]["item"]["id"] == 7


@pytest.mark.parametrize(("resource", "helper_attr"), RESOURCE_CASES)
def test_crud_resource_create_update_delete_routes(
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
    helper_attr: str,
) -> None:
    seen_helpers: list[str] = []
    seen_only_changed: list[bool] = []
    seen_full_perms: list[bool] = []

    def fake_create_client(options: Any) -> tuple[object, RuntimeContext]:
        _ = options
        return object(), RuntimeContext(profile="default", url="https://example", token="token")

    def fake_update(
        item: Any,
        *,
        fields: dict[str, Any],
        only_changed: bool = True,
    ) -> bool:
        _ = (item, fields)
        seen_helpers.append("update")
        seen_only_changed.append(only_changed)
        return True

    def fake_delete(item: Any) -> bool:
        _ = item
        seen_helpers.append("delete")
        return True

    def fake_fetch(
        client: Any,
        *,
        helper_name: str,
        item_id: int,
        full_perms: bool = False,
    ) -> FakeItem:
        _ = (client, helper_name, item_id)
        seen_helpers.append(helper_name)
        seen_full_perms.append(full_perms)
        return FakeItem(_data={"id": item_id, "name": "x"})

    def fake_create_resource(client: Any, *, helper_name: str, fields: dict[str, Any]) -> int:
        _ = (client, fields)
        seen_helpers.append(helper_name)
        seen_helpers.append("create")
        return 99

    monkeypatch.setattr(crud_cli, "create_client", fake_create_client)
    monkeypatch.setattr(crud_cli, "fetch_resource_sync", fake_fetch)
    monkeypatch.setattr(crud_cli, "create_resource_sync", fake_create_resource)
    monkeypatch.setattr(crud_cli, "update_resource_sync", fake_update)
    monkeypatch.setattr(crud_cli, "delete_resource_sync", fake_delete)

    create_result = runner.invoke(app, [resource, "create", "name=demo"])
    update_result = runner.invoke(
        app,
        [resource, "update", "4", "name=changed", "only_changed=false", "full_perms=true"],
    )
    delete_result = runner.invoke(app, [resource, "delete", "4", "yes=true", "full_perms=true"])

    assert create_result.exit_code == 0
    assert update_result.exit_code == 0
    assert delete_result.exit_code == 0
    assert seen_helpers == [helper_attr, "create", helper_attr, "update", helper_attr, "delete"]
    assert seen_only_changed == [False]
    assert seen_full_perms == [True, True]

    create_payload = json.loads(create_result.output)
    update_payload = json.loads(update_result.output)
    delete_payload = json.loads(delete_result.output)
    assert create_payload["action"] == "create"
    assert update_payload["action"] == "update"
    assert delete_payload["action"] == "delete"
    assert delete_payload["data"]["deleted"] is True


def test_crud_resource_delete_requires_confirmation() -> None:
    with pytest.raises(UsageValidationError) as exc:
        runner.invoke(app, ["tags", "delete", "3"], catch_exceptions=False)
    assert exc.value.payload.code == "CONFIRMATION_REQUIRED"


def test_crud_resource_list_rejects_invalid_page_and_boolean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        _ = (client, helper_name, page, page_size, filters, full_perms)
        return ListPage(
            items=[],
            count=0,
            page=page,
            page_size=page_size,
            next_page=None,
            previous_page=None,
        )

    monkeypatch.setattr(crud_cli, "create_client", fake_create_client)
    monkeypatch.setattr(crud_cli, "list_resource_sync", fake_list_items)

    with pytest.raises(UsageValidationError) as invalid_page:
        runner.invoke(app, ["tags", "list", "page=0"], catch_exceptions=False)
    assert invalid_page.value.payload.code == "INVALID_PAGE"

    with pytest.raises(UsageValidationError) as invalid_boolean:
        runner.invoke(app, ["tags", "list", "full_perms=maybe"], catch_exceptions=False)
    assert invalid_boolean.value.payload.code == "INVALID_BOOLEAN"
