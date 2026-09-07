"""Retrieval help is usable without credentials, rich rendering, or PDF imports."""

import re
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from pcli.cli.main import app


@pytest.mark.parametrize(
    "command,required",
    [
        (["docs", "find"], ["ids_only=false", "max_docs=200", "fields=LIST", "chars_total"]),
        (["docs", "peek"], ["per_doc_max_chars=1200", "max_docs=20", "allow_partial=false"]),
        (
            ["docs", "skim"],
            ["context_before=200", "context_after=300", "max_hits_per_doc=3", "NOT regex"],
        ),
        (
            ["docs", "facets"],
            ["facet_scope=page", "top_values=20", "corpus_complete", "values_truncated"],
        ),
        (["docs", "get"], ["pages=SPEC", "max_pages=N", "max_chars=20000", "page_spans"]),
        (["get"], ["pages=SPEC", "max_pages=N", "max_chars=20000", "page_spans"]),
    ],
)
def test_help_contains_examples_defaults_and_readable_options(
    command: list[str],
    required: list[str],
) -> None:
    result = CliRunner().invoke(app, [*command, "--help"])
    assert result.exit_code == 0
    assert "Examples:" in result.stdout and "pcli " in result.stdout
    assert "\x1b[" not in result.stdout
    for value in required:
        assert value in result.stdout
    assert re.search(r"^\s+(query=TEXT|source=auto)\s+\w", result.stdout, re.MULTILINE)


def test_pdf_reader_is_not_loaded_for_cli_startup() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from pcli.cli.main import app; assert 'pypdf' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "command,examples",
    [
        (["auth"], ["pcli auth status", "pcli auth switch work", "pcli auth logout profile=work"]),
        (["docs"], ["pcli get 42 max_chars=5000 format=text", "pcli get 42 pages=1-3"]),
    ],
)
def test_group_help_keeps_each_example_on_its_own_line(
    command: list[str],
    examples: list[str],
) -> None:
    result = CliRunner().invoke(app, [*command, "--help"])
    assert result.exit_code == 0
    lines = [line.strip() for line in result.stdout.splitlines()]
    for example in examples:
        assert example in lines
    assert "\b" not in result.stdout and "\x1b[" not in result.stdout


def test_docs_orientation_precedes_command_catalog() -> None:
    result = CliRunner().invoke(app, ["docs", "--help"])
    intro = result.stdout.split("Commands:")[0]
    for phrase in [
        "Shortlist by topic",
        "Preview the beginning",
        "literal hits",
        "bounded OCR",
        "list/search",
        "positional",
        "without discovery budgets or cursors",
    ]:
        assert phrase in intro
