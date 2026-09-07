"""Verify streaming across the real CLI, dependency pagination, and stdout pipe."""

import json
import queue
import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest


@dataclass
class StreamAPI:
    url: str = ""
    requests: list[tuple[int, int]] = field(default_factory=list)
    second_requested: threading.Event = field(default_factory=threading.Event)
    release_second: threading.Event = field(default_factory=threading.Event)
    fail_second: bool = False
    total: int = 500


@pytest.fixture
def stream_api() -> Iterator[StreamAPI]:
    state = StreamAPI()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            payload: dict[str, Any] = {}
            status = 200
            if self.path.startswith("/api/documents/"):
                params = parse_qs(urlsplit(self.path).query)
                page, size = int(params["page"][0]), int(params["page_size"][0])
                state.requests.append((page, size))
                if page > 1:
                    state.second_requested.set()
                    if not state.release_second.wait(10):
                        status = 504
                    elif state.fail_second:
                        status = 500
                start = (page - 1) * size
                payload = {
                    "count": state.total,
                    "next": "next" if start + size < state.total else None,
                    "previous": None,
                    "all": [],
                    "results": [
                        {"id": i + 1, "title": f"Document {i + 1}", "content": "fixture " * 3}
                        for i in range(start, min(start + size, state.total))
                    ],
                }
            data = json.dumps(payload if status == 200 else {"detail": "fixture failure"}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield state
    finally:
        state.release_second.set()
        server.shutdown()
        server.server_close()
        thread.join()


def cli_args(api: StreamAPI, action: str, *options: str) -> list[str]:
    return [
        sys.executable,
        "-c",
        "from pcli.cli.main import main; main()",
        "docs",
        action,
        "query=fixture",
        f"url={api.url}",
        "token=test",
        *options,
    ]


@pytest.mark.parametrize("action", ["find", "peek", "skim"])
@pytest.mark.parametrize("mode", ["rg", "ndjson"])
def test_output_arrives_while_next_page_is_blocked(
    stream_api: StreamAPI,
    action: str,
    mode: str,
) -> None:
    process = subprocess.Popen(
        cli_args(stream_api, action, f"format={mode}", "page_size=2", "max_hits_per_doc=1"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    stdout = process.stdout
    first_line: queue.Queue[str] = queue.Queue()
    reader = threading.Thread(target=lambda: first_line.put(stdout.readline()))
    reader.start()
    try:
        assert stream_api.second_requested.wait(5), "CLI did not request the next page"
        line = first_line.get(timeout=2)
        assert line.strip(), "No output before next-page response"
        if mode == "ndjson":
            assert json.loads(line)["type"] == "item"
        else:
            assert not line.startswith("#")
        stream_api.release_second.set()
        rest, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, rest + stderr
        assert "summary" in rest
        assert stderr == ""
    finally:
        stream_api.release_second.set()
        if process.poll() is None:
            process.kill()
        process.wait()
        reader.join(timeout=5)


@pytest.mark.parametrize("action", ["find", "peek", "skim"])
def test_match_budget_requests_only_one_small_page(stream_api: StreamAPI, action: str) -> None:
    result = subprocess.run(
        cli_args(stream_api, action, "format=ndjson", "max_docs=2000", "stop_after_matches=1"),
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(records) == 2
    assert records[-1]["meta"]["matches"] == 1
    assert records[-1]["meta"]["complete"] is False
    assert stream_api.requests == [(1, 2)]
    assert result.stderr == ""


@pytest.mark.parametrize("mode", ["rg", "ndjson", "json"])
def test_late_failure_is_nonzero_without_success_summary(stream_api: StreamAPI, mode: str) -> None:
    stream_api.fail_second = True
    stream_api.release_second.set()
    result = subprocess.run(
        cli_args(stream_api, "find", f"format={mode}", "page_size=2"),
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 6, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    error = json.loads(lines[-1])
    assert "error" in error
    if mode == "ndjson":
        assert error["type"] == "error"
        assert len(lines) == 3
    elif mode == "json":
        assert len(lines) == 1
        assert error["ok"] is False
    assert "summary" not in result.stdout
    assert result.stderr == ""


def test_broken_pipe_stops_without_traceback(stream_api: StreamAPI) -> None:
    process = subprocess.Popen(
        cli_args(stream_api, "find", "format=ndjson", "page_size=500", "max_docs=500"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None and process.stderr is not None
    try:
        assert process.stdout.readline()
        process.stdout.close()
        stream_api.release_second.set()
        assert process.wait(timeout=5) != 0
        assert process.stderr.read() == b""
        assert len(stream_api.requests) <= 2
    finally:
        stream_api.release_second.set()
        if process.poll() is None:
            process.kill()
        process.wait()


def test_explicit_page_maps_to_absolute_position_with_smaller_fetches(
    stream_api: StreamAPI,
) -> None:
    stream_api.release_second.set()
    result = subprocess.run(
        cli_args(stream_api, "find", "format=json", "page=3", "page_size=10", "max_docs=1"),
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["data"]["items"][0]["id"] == 21
    assert payload["meta"]["complete"] is False
    assert stream_api.requests == [(11, 2)]
