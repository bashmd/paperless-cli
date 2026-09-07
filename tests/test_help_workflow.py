"""Execute rendered help recipes against a local API with deliberately misleading candidates.

This verifies examples and wire parameters, not independent agent usability or
Paperless's search engine. Filter names were checked against upstream 2.20.10.
"""

import json
import shlex
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from test_http_integration import run_cli


@pytest.fixture
def recipe_api() -> Iterator[str]:
    def document(pk: int, date: str, tags: list[int], topic: str = "insurance") -> dict[str, Any]:
        return {
            "id": pk,
            "created": date,
            "added": "2026-08-01T12:00:00Z",
            "tags": tags,
            "document_type": 7 if pk == 42 else 8,
            "title": f"{topic.title()} notice {pk}",
            "page_count": 1,
            "content": f"{topic.title()} notice {pk}. Monthly premium: {pk} EUR. "
            "Keep this notice for your records.",
        }

    documents = [
        document(42, "2026-07-01", [7, 8]),
        document(17, "2026-04-01", [7]),
        document(9, "2026-01-01", [7]),
        document(801, "2025-12-31", [7]),
        document(802, "2027-01-01", [7]),
        document(803, "2026-07-02", [8]),
        document(804, "2026-07-03", [7], "invoice"),
    ]
    allowed = {
        "query",
        "page",
        "page_size",
        "ordering",
        "id__in",
        "tags__id__all",
        "tags__id__in",
        "created__gte",
        "created__lt",
        "added__date__gte",
        "added__date__lt",
        "document_type__id__in",
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def respond(self, payload: object, status: int = 200) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            params = {key: values[0] for key, values in parse_qs(url.query).items()}
            rows: list[dict[str, Any]]
            if url.path == "/api/schema/":
                self.respond({})
                return
            if url.path == "/api/tags/":
                tags = [{"id": 7, "name": "Insurance"}, {"id": 8, "name": "Bank"}]
                rows = [
                    tag
                    for tag in tags
                    if params.get("name__icontains", "").lower() in str(tag["name"]).lower()
                ]
            elif url.path == "/api/documents/":
                if params.keys() - allowed:
                    self.respond({"detail": "Unexpected filter spelling"}, 400)
                    return
                rows = list(documents)
                needle = params.get("query", "").lower()
                rows = [doc for doc in rows if needle in doc["content"].lower()]
                for key, field in [("id__in", "id"), ("document_type__id__in", "document_type")]:
                    if key in params:
                        ids = list(map(int, params[key].split(",")))
                        rows = [doc for doc in rows if doc[field] in ids]
                for key in ["tags__id__all", "tags__id__in"]:
                    if key in params:
                        tag_ids = set(map(int, params[key].split(",")))
                        rows = [
                            doc
                            for doc in rows
                            if (
                                tag_ids.issubset(doc["tags"])
                                if key.endswith("__all")
                                else tag_ids.intersection(doc["tags"])
                            )
                        ]
                for field in ["created", "added__date"]:
                    lower, upper = params.get(field + "__gte"), params.get(field + "__lt")
                    attr = field.split("__")[0]
                    rows = [
                        doc
                        for doc in rows
                        if (lower is None or doc[attr][:10] >= lower)
                        and (upper is None or doc[attr][:10] < upper)
                    ]
                if params.get("ordering") == "-created":
                    rows.sort(key=lambda doc: doc["created"], reverse=True)
            else:
                for doc in documents:
                    if url.path == f"/api/documents/{doc['id']}/":
                        self.respond(doc)
                        return
                self.respond({"detail": "Unexpected endpoint"}, 404)
                return
            page, size = int(params.get("page", 1)), int(params.get("page_size", 150))
            start = (page - 1) * size
            self.respond(
                {
                    "count": len(rows),
                    "next": "next" if start + size < len(rows) else None,
                    "previous": None,
                    "all": [row["id"] for row in rows],
                    "results": rows[start : start + size],
                }
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def help_command(help_text: str, prefix: str) -> list[str]:
    """Copy one command, including shell continuations, from rendered help."""
    lines = iter(help_text.splitlines())
    for line in lines:
        command = line.strip()
        if command.startswith(prefix):
            while command.endswith("\\"):
                command = command[:-1] + next(lines).strip()
            return shlex.split(command)[1:]
    pytest.fail(f"No executable help recipe starting with {prefix}")


def help_for(*command: str) -> str:
    result = run_cli(*command, "--help")
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def invoke(url: str, command: list[str]) -> str:
    result = run_cli(*command, f"url={url}", "token=test")
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_help_guided_shortlist_skim_and_read(recipe_api: str) -> None:
    overview = help_for("docs")
    find_help = help_for("docs", "find")
    tag_command = help_command(find_help, "pcli tags list")
    tags = json.loads(invoke(recipe_api, tag_command))["data"]["items"]
    assert tags == [{"id": 7, "name": "Insurance"}]
    tag_id = tags[0]["id"]
    find_command = help_command(find_help, "pcli docs find query=insurance tags__id__all=")
    find_command = [
        f"tags__id__all={tag_id}" if arg.startswith("tags__id__all=") else arg
        for arg in find_command
    ]
    # Use the documented page_size and cursor controls to force a partial shortlist.
    find_command += ["page_size=1", "format=ndjson"]
    ids: list[int] = []
    cursor = None
    for _ in range(5):
        records = [
            json.loads(line)
            for line in invoke(
                recipe_api, find_command + ([f"cursor={cursor}"] if cursor else [])
            ).splitlines()
        ]
        ids.extend(row["id"] for row in records if row["type"] == "item")
        meta = records[-1]["meta"]
        if meta["complete"]:
            break
        assert meta["next_cursor"] and meta["next_cursor"] != cursor
        cursor = meta["next_cursor"]
    else:
        pytest.fail("Documented continuation did not finish")
    assert ids == [42, 17, 9]  # Decoys excluded, lower date included, upper excluded.

    for action in ["peek", "skim"]:
        command = help_command(overview, f"pcli docs {action} ids=")
        command = [
            f"ids={','.join(map(str, ids))}" if arg.startswith("ids=") else arg for arg in command
        ]
        payload = json.loads(invoke(recipe_api, [*command, "format=json"]))
        rows = payload["data"]["items"]
        assert [row.get("id", row.get("doc_id")) for row in rows] == ids
        assert payload["meta"]["complete"] is True
        if action == "skim":
            assert all("premium" in row["text"] for row in rows)

    read_command = help_command(overview, "pcli get 42 max_chars=")
    full_text = invoke(recipe_api, read_command)
    assert "Monthly premium: 42 EUR" in full_text
    get_help = help_for("get")
    assert "meta.next_start" in get_help and "start_char=0" in get_help
    first = json.loads(invoke(recipe_api, ["get", str(ids[0]), "max_chars=20"]))
    tail = json.loads(
        invoke(recipe_api, ["get", str(ids[0]), f"start_char={first['meta']['next_start']}"])
    )
    assert first["data"]["text"] + tail["data"]["text"] == full_text


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"tags__id__all": "7,8"}, [42]),
        ({"tags__id__all": None, "tags__id__in": "7,8"}, [803, 42, 17, 9]),
        ({"doc_type": "7"}, [42]),
        (
            {
                "created__gte": None,
                "created__lt": None,
                "added__date__gte": "2026-01-01",
                "added__date__lt": "2027-01-01",
            },
            [802, 42, 17, 9, 801],
        ),
    ],
)
def test_documented_filter_variants(
    recipe_api: str,
    change: dict[str, str | None],
    expected: list[int],
) -> None:
    command = help_command(
        help_for("docs", "find"), "pcli docs find query=insurance tags__id__all="
    )
    command = [arg for arg in command if arg.split("=", 1)[0] not in change]
    command += [f"{key}={value}" for key, value in change.items() if value is not None]
    payload = json.loads(invoke(recipe_api, [*command, "format=json"]))
    assert [row["id"] for row in payload["data"]["items"]] == expected
    assert payload["meta"]["complete"] is True
