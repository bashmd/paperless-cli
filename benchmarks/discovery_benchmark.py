"""Synthetic benchmark for discovery pipelines (find/peek/skim)."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass

from pcli.cli.docs import (
    _extract_skim_hits,
    _project_find_document,
    _project_peek_document,
    _sorted_find_documents,
)


@dataclass(slots=True)
class FakeDocument:
    id: int
    title: str
    created: dt.date
    content: str
    tags: list[int]
    search_hit: object | None = None


def _build_documents(*, count: int, chars_per_doc: int, query: str) -> list[FakeDocument]:
    base_chunk = f"{query} alpha beta gamma delta "
    repeats = max(1, chars_per_doc // len(base_chunk))
    body = (base_chunk * repeats)[:chars_per_doc]

    docs: list[FakeDocument] = []
    for index in range(count):
        docs.append(
            FakeDocument(
                id=index + 1,
                title=f"Document {index + 1}",
                created=dt.date(2025, 1, 1) + dt.timedelta(days=index % 365),
                content=body,
                tags=[index % 10, (index + 3) % 10],
            )
        )
    return docs


def _measure_seconds(fn: Callable[[], int], *, repeats: int) -> tuple[float, int]:
    samples: list[float] = []
    items = 0
    for _ in range(repeats):
        started = time.perf_counter()
        items = fn()
        samples.append(time.perf_counter() - started)
    return statistics.median(samples), items


def run_benchmark(
    *,
    doc_count: int,
    chars_per_doc: int,
    repeats: int,
    query: str,
    context_before: int,
    context_after: int,
    max_hits_per_doc: int,
) -> dict[str, object]:
    documents = _build_documents(count=doc_count, chars_per_doc=chars_per_doc, query=query)

    def run_find() -> int:
        sorted_docs = _sorted_find_documents(documents)
        rows = [
            _project_find_document(doc, ["id", "title", "created", "score", "snippet"])
            for doc in sorted_docs
        ]
        return len(rows)

    def run_peek() -> int:
        rows = [
            _project_peek_document(
                doc,
                ["id", "title", "created", "tags", "excerpt"],
                max_chars=1200,
            )
            for doc in documents
        ]
        return len(rows)

    def run_skim() -> int:
        hits = 0
        for doc in documents:
            hits += len(
                _extract_skim_hits(
                    doc,
                    query=query,
                    context_before=context_before,
                    context_after=context_after,
                    max_hits_per_doc=max_hits_per_doc,
                )
            )
        return hits

    find_seconds, find_items = _measure_seconds(run_find, repeats=repeats)
    peek_seconds, peek_items = _measure_seconds(run_peek, repeats=repeats)
    skim_seconds, skim_items = _measure_seconds(run_skim, repeats=repeats)

    return {
        "inputs": {
            "doc_count": doc_count,
            "chars_per_doc": chars_per_doc,
            "repeats": repeats,
            "query": query,
            "context_before": context_before,
            "context_after": context_after,
            "max_hits_per_doc": max_hits_per_doc,
        },
        "metrics": {
            "find_seconds_median": round(find_seconds, 6),
            "find_items": find_items,
            "peek_seconds_median": round(peek_seconds, 6),
            "peek_items": peek_items,
            "skim_seconds_median": round(skim_seconds, 6),
            "skim_hits": skim_items,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docs",
        type=int,
        default=10_000,
        help="Number of synthetic documents.",
    )
    parser.add_argument(
        "--chars",
        type=int,
        default=2500,
        help="Characters per synthetic document.",
    )
    parser.add_argument("--repeats", type=int, default=3, help="Number of timing repeats.")
    parser.add_argument(
        "--query",
        type=str,
        default="invoice",
        help="Query term for skim benchmark.",
    )
    parser.add_argument(
        "--context-before",
        type=int,
        default=160,
        help="Skim context_before setting.",
    )
    parser.add_argument(
        "--context-after",
        type=int,
        default=240,
        help="Skim context_after setting.",
    )
    parser.add_argument("--max-hits-per-doc", type=int, default=3, help="Skim max hits per doc.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_benchmark(
        doc_count=args.docs,
        chars_per_doc=args.chars,
        repeats=args.repeats,
        query=args.query,
        context_before=args.context_before,
        context_after=args.context_after,
        max_hits_per_doc=args.max_hits_per_doc,
    )
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=True))


if __name__ == "__main__":
    main()
