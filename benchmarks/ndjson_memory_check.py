"""NDJSON streaming memory validation harness."""

from __future__ import annotations

import argparse
import json
import tracemalloc
from io import StringIO

from pcli.core.output import ndjson_item, ndjson_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--items",
        type=int,
        default=250_000,
        help="Number of NDJSON item lines to emit.",
    )
    parser.add_argument(
        "--text-size",
        type=int,
        default=256,
        help="Characters per synthetic payload text.",
    )
    parser.add_argument(
        "--max-peak-mb",
        type=float,
        default=160.0,
        help="Maximum allowed peak memory in MiB before failing.",
    )
    return parser.parse_args()


def run_memory_check(*, item_count: int, text_size: int) -> tuple[float, int]:
    sink = StringIO()
    text = ("x" * max(1, text_size))[:text_size]

    tracemalloc.start()
    for index in range(item_count):
        line = ndjson_item({"id": index + 1, "text": text})
        sink.write(line)
        sink.write("\n")
    sink.write(ndjson_summary(next_cursor=None))
    sink.write("\n")

    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak_bytes / (1024 * 1024), sink.tell()


def main() -> None:
    args = parse_args()
    peak_mb, total_bytes = run_memory_check(item_count=args.items, text_size=args.text_size)

    payload = {
        "inputs": {
            "items": args.items,
            "text_size": args.text_size,
            "max_peak_mb": args.max_peak_mb,
        },
        "metrics": {
            "peak_memory_mb": round(peak_mb, 4),
            "output_bytes": total_bytes,
        },
        "ok": peak_mb <= args.max_peak_mb,
    }
    print(json.dumps(payload, separators=(",", ":"), ensure_ascii=True))
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
