"""Exercise real dependency sessions and the installed CLI boundary against localhost."""

import json
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from pdf_fixtures import make_pdf


@pytest.fixture
def local_api() -> Iterator[tuple[str, list[str]]]:
    methods: list[str] = []
    pdf = make_pdf(["First page", "Second page", "Third page"])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def respond(self, payload: object, status: int = 200) -> None:
            methods.append(self.command)
            data = (
                b""
                if status == 204
                else payload
                if isinstance(payload, bytes)
                else json.dumps(payload).encode()
            )
            self.send_response(status)
            self.send_header(
                "Content-Type",
                "application/pdf" if isinstance(payload, bytes) else "application/json",
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            for doc_id in [42, 43, 44, 45]:
                if path == f"/api/documents/{doc_id}/":
                    methods.append(self.path)
                    self.respond(
                        {
                            "id": doc_id,
                            "content": "OCR text",
                            "page_count": 20,
                            "archived_file_name": "archive.pdf",
                            "original_file_name": "original.pdf",
                        }
                    )
                    return
                if path == f"/api/documents/{doc_id}/download/":
                    methods.append(self.path)
                    original = parse_qs(urlsplit(self.path).query).get("original") == ["true"]
                    if doc_id in [43, 44] and not original:
                        self.respond({"detail": "Unavailable"}, 404 if doc_id == 43 else 403)
                    else:
                        self.respond(b"not PDF" if doc_id == 45 else pdf)
                    return
            if self.path.startswith("/api/documents/"):
                methods.append(self.path)
                self.respond({"count": 0, "next": None, "previous": None, "results": [], "all": []})
                return
            if self.path.startswith("/api/tags/"):
                status = self.path.rstrip("/").split("/")[-1]
                if status in {"401", "403", "404", "500"}:
                    self.respond({"detail": "Fixture failure"}, int(status))
                    return
            self.respond({"id": 1, "name": "Before"} if "/tags/1/" in self.path else {})

        def do_PATCH(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.respond({"id": 1, "name": "After"})

        def do_DELETE(self) -> None:
            self.respond({}, 204)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", methods
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def run_cli(*args: str, input: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", "from pcli.cli.main import main; main()", *args],
        capture_output=True,
        text=True,
        timeout=15,
        input=input,
    )


def test_real_resource_mutations(local_api: tuple[str, list[str]]) -> None:
    url, methods = local_api
    for operation, option in [("update", "name=After"), ("delete", "yes=true")]:
        result = run_cli("tags", operation, "1", option, f"url={url}", "token=test")
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["ok"] is True
        assert result.stderr == ""
    assert methods.count("PATCH") == 1
    assert methods.count("DELETE") == 1


def test_connection_failure_is_structured(local_api: tuple[str, list[str]]) -> None:
    # Closed ephemeral listener avoids relying on a particular system port being free.
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_port
    server.server_close()
    result = run_cli("docs", "find", "query=x", f"url=http://127.0.0.1:{port}", "token=test")
    assert result.returncode == 7
    assert json.loads(result.stdout)["error"]["code"] == "NETWORK_ERROR"
    assert result.stderr == ""


def test_click_usage_failure_is_structured() -> None:
    result = run_cli("get", "not-an-id")
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_ARGUMENTS"
    assert result.stderr == ""


@pytest.mark.parametrize(("status", "exit_code"), [(401, 3), (403, 5), (404, 4), (500, 6)])
def test_http_failures_have_stable_exit_codes(
    local_api: tuple[str, list[str]],
    status: int,
    exit_code: int,
) -> None:
    result = run_cli("tags", "get", str(status), f"url={local_api[0]}", "token=test")
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert json.loads(result.stdout)["ok"] is False
    assert result.stderr == ""


def test_failed_producer_exits_nonzero_without_pipefail() -> None:
    result = run_cli("docs", "peek", "from_stdin=true", input='{"ok":false,"error":{}}\n')
    assert result.returncode == 6
    assert json.loads(result.stdout)["error"]["code"] == "UPSTREAM_FAILED"


def test_sort_reaches_real_dependency_request(local_api: tuple[str, list[str]]) -> None:
    url, requests = local_api
    result = run_cli("docs", "find", "query=fixture", "sort=-created", f"url={url}", "token=test")
    assert result.returncode == 0, result.stdout + result.stderr
    request = next(path for path in requests if path.startswith("/api/documents/"))
    params = parse_qs(urlsplit(request).query)
    assert params["ordering"] == ["-created"]
    assert "sort" not in params


@pytest.mark.parametrize("doc_type", ["7", "7,8"])
def test_document_type_alias_is_an_id_filter_on_wire(
    local_api: tuple[str, list[str]],
    doc_type: str,
) -> None:
    url, requests = local_api
    result = run_cli(
        "docs", "find", "query=fixture", f"doc_type={doc_type}", f"url={url}", "token=test"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    request = next(path for path in requests if path.startswith("/api/documents/"))
    params = parse_qs(urlsplit(request).query)
    assert params["document_type__id__in"] == [doc_type]
    assert "document_type" not in params


@pytest.mark.parametrize(("status", "exit_code"), [(401, 3), (403, 5), (404, 4), (500, 6)])
def test_mutation_does_not_disguise_transport_failures(
    local_api: tuple[str, list[str]],
    status: int,
    exit_code: int,
) -> None:
    result = run_cli(
        "tags", "update", str(status), "name=After", f"url={local_api[0]}", "token=test"
    )
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert json.loads(result.stdout)["ok"] is False
    assert result.stderr == ""


@pytest.mark.parametrize(
    "options,pages,source",
    [
        (["pages=1,3"], [1, 3], "archive"),
        (["max_pages=2"], [1, 2], "archive"),
        (["source=original", "pages=2"], [2], "original"),
        (["max_pages=50"], [1, 2, 3], "archive"),
    ],
)
def test_real_pdf_get_uses_one_session_and_correct_source(
    local_api: tuple[str, list[str]],
    options: list[str],
    pages: list[int],
    source: str,
) -> None:
    url, methods = local_api
    result = run_cli("get", "42", *options, f"url={url}", "token=test")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["data"]["pages"] == pages
    assert payload["data"]["source"] == source
    assert payload["meta"]["page_count"] == 3
    assert "content" not in payload["data"]["document"]
    downloads = [path for path in methods if "/download/" in path]
    assert len(downloads) == 1
    assert f"original={'true' if source == 'original' else 'false'}" in downloads[0]
    assert result.stderr == ""


def test_pdf_get_chunks_reassemble_selected_text(local_api: tuple[str, list[str]]) -> None:
    options = ["get", "42", "pages=1,3", f"url={local_api[0]}", "token=test"]
    first = run_cli(*options, "max_chars=6")
    payload = json.loads(first.stdout)
    second = run_cli(*options, f"start_char={payload['meta']['next_start']}")
    tail = json.loads(second.stdout)
    assert payload["data"]["text"] + tail["data"]["text"] == "First page\n\f\nThird page"
    assert tail["meta"]["next_start"] is None
    plain = run_cli(*options, "max_chars=6", "format=text")
    assert plain.stdout == "First "
    assert "source=archive pages=1,3 start_char=6" in plain.stderr


@pytest.mark.parametrize("doc_id,code,downloads", [(43, 0, 2), (44, 5, 1), (45, 2, 2)])
def test_auto_fallback_does_not_hide_permission_failure(
    local_api: tuple[str, list[str]],
    doc_id: int,
    code: int,
    downloads: int,
) -> None:
    url, methods = local_api
    result = run_cli("get", str(doc_id), "pages=1", f"url={url}", "token=test")
    assert result.returncode == code, result.stdout + result.stderr
    assert len([path for path in methods if "/download/" in path]) == downloads
    if code == 0:
        assert json.loads(result.stdout)["data"]["source"] == "original"
    assert result.stderr == ""
