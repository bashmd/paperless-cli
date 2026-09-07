"""Measure real discovery scanning with unique paginated bodies and a discard sink.

The buffered mode emulates the previous eager-fetch/eager-output architecture;
it is a comparison baseline, not an alternative production implementation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
import tracemalloc
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass, replace
from typing import Any

from pcli.cli.docs import _extract_skim_hits
from pcli.core.discovery_scan import scan_batch
from pcli.core.output import ndjson_item, to_json
from pcli.models.discovery import CanonicalDocumentSearch, canonicalize_document_search


@dataclass(slots=True)
class Document:
    id: int
    content: str


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=positive_int, default=250_000)
    parser.add_argument("--text-size", type=positive_int, default=256)
    parser.add_argument("--stop-after", type=positive_int, default=None)
    parser.add_argument("--mode", choices=["streaming", "buffered"], default="streaming")
    parser.add_argument("--max-peak-mb", type=float, default=16.0)
    return parser.parse_args()


def run_memory_check(
    *, item_count: int, text_size: int, stop_after: int | None = None, mode: str = "streaming"
) -> dict[str, Any]:
    fetched = requests = output_bytes = 0
    first_row_seconds: float | None = None
    fetched_at_first_row: int | None = None
    pattern = re.compile("needle", re.IGNORECASE)
    search = canonicalize_document_search(query="needle", max_docs=item_count, page_size=item_count)

    async def pages(batch: CanonicalDocumentSearch) -> AsyncGenerator[Document]:
        nonlocal fetched, requests
        start = (batch.page - 1) * batch.page_size
        end = min(item_count, start + batch.max_docs)
        for offset in range(start, end, batch.page_size):
            # Allocate unique bodies one API page at a time, not a prebuilt corpus
            # or a shared string. Match Paperless's whole-page response granularity.
            documents = [
                Document(i + 1, f"needle {i + 1} ".ljust(text_size, "x"))
                for i in range(offset, min(offset + batch.page_size, item_count))
            ]
            fetched += len(documents)
            requests += 1
            for index, doc in enumerate(documents, start=offset):
                if index >= end:
                    break
                yield doc

    async def fetch(batch: CanonicalDocumentSearch) -> AsyncGenerator[Document]:
        if mode == "buffered":
            # The old engine loaded max_docs plus lookahead before projecting rows.
            documents = [
                doc async for doc in pages(replace(batch, page_size=150, max_docs=item_count + 1))
            ]
            for doc in documents:
                yield doc
        else:
            async with aclosing(pages(batch)) as source:
                async for doc in source:
                    yield doc

    def emit(row: dict[str, Any]) -> None:
        nonlocal output_bytes, first_row_seconds, fetched_at_first_row
        output_bytes += len(ndjson_item(row).encode()) + 1
        if first_row_seconds is None:
            first_row_seconds = time.perf_counter() - started
            fetched_at_first_row = fetched

    async def scan() -> dict[str, Any]:
        result = await scan_batch(
            search=search,
            fetch=fetch,
            project=lambda doc: _extract_skim_hits(
                doc,
                query="needle",
                query_pattern=pattern,
                context_before=100,
                context_after=200,
                max_hits_per_doc=3,
            ),
            character_cost=lambda row: len(row["text"]),
            page_cost=lambda doc: 1,
            command="docs.skim",
            signature={},
            offset=0,
            max_matches=stop_after,
            emit=emit if mode == "streaming" else None,
        )
        for row in result.items:
            emit(row)
        return result.meta

    tracemalloc.start()
    started = time.perf_counter()
    meta = asyncio.run(scan())
    output_bytes += len(to_json({"type": "summary", "meta": meta}).encode()) + 1
    elapsed = time.perf_counter() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "peak_memory_mb": round(peak_bytes / (1024 * 1024), 4),
        "seconds": round(elapsed, 6),
        "first_row_seconds": round(first_row_seconds, 6) if first_row_seconds is not None else None,
        "fetched_documents": fetched,
        "fetched_at_first_row": fetched_at_first_row,
        "page_requests": requests,
        "output_bytes": output_bytes,
        "emitted_rows": meta["count"],
        "complete": meta["complete"],
    }


def main() -> None:
    args = parse_args()
    metrics = run_memory_check(
        item_count=args.items,
        text_size=args.text_size,
        stop_after=args.stop_after,
        mode=args.mode,
    )
    payload = {
        "inputs": vars(args),
        "metrics": metrics,
        "ok": metrics["peak_memory_mb"] <= args.max_peak_mb,
    }
    print(json.dumps(payload, separators=(",", ":"), ensure_ascii=True))
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
