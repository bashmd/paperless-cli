# Discovery Performance Benchmarks

## Purpose

Track regression-sensitive performance for high-volume LLM discovery flows:

- `docs find` shortlist projection
- `docs peek` lightweight excerpt generation
- `docs skim` hit extraction with context windows

## How To Run

```bash
uv run python benchmarks/discovery_benchmark.py --docs 10000 --chars 2500 --repeats 3
```

The benchmark prints one JSON object with inputs and median timings.

## Regression Thresholds

Use these thresholds for local regression checks (non-CI hard gate for now):

1. `find_seconds_median <= 1.50` for `docs=10000 chars=2500`.
2. `peek_seconds_median <= 2.00` for `docs=10000 chars=2500`.
3. `skim_seconds_median <= 4.00` for `docs=10000 chars=2500 max_hits_per_doc=3`.

If any threshold is exceeded:

1. Re-run with `--repeats 5` to rule out transient noise.
2. Compare against last known-good benchmark output in PR notes.
3. Treat persistent regressions above 20% as release blockers.

## NDJSON Memory Check

Exercise the actual async scan engine, skim projection, and NDJSON serialization
with unique document bodies generated one page at a time. Output goes to a counting
discard sink, not an accumulating `StringIO`:

```bash
uv run python benchmarks/ndjson_memory_check.py --items 250000 --text-size 256 --max-peak-mb 16
```

Expected behavior:

1. Exit code `0` and JSON `ok=true`.
2. `peak_memory_mb <= 16` for the default workload.
3. `emitted_rows=250000` and `complete=true`.

Compare early stopping with the former eager-fetch/eager-output architecture:

```bash
uv run python benchmarks/ndjson_memory_check.py --items 2000 --text-size 10000 --stop-after 1 --mode buffered --max-peak-mb 64
uv run python benchmarks/ndjson_memory_check.py --items 2000 --text-size 10000 --stop-after 1
uv run python benchmarks/ndjson_memory_check.py --items 2000 --text-size 10000
uv run python benchmarks/ndjson_memory_check.py --items 20000 --text-size 10000
```

`--mode buffered` emulates the former architecture using the same projector and
scanner; it is not a supported CLI mode or a checkout of the old implementation.

### Measurements (2026-09-07)

Python 3.12, Rust normalizer enabled, one synthetic hit per document:

| Workload | Bodies fetched | API-sized pages | Peak Python allocation | First row |
| --- | ---: | ---: | ---: | ---: |
| 2,000 x 10,000 chars, stop after 1, buffered baseline | 2,000 | 14 | 19.3349 MiB | 18.260 ms |
| Same workload, streaming | 2 | 1 | 0.0429 MiB | 0.475 ms |
| 2,000 x 10,000 chars, complete streaming scan | 2,000 | 14 | 2.9314 MiB | 1.366 ms |
| 20,000 x 10,000 chars, complete streaming scan | 20,000 | 134 | 2.9193 MiB | 1.350 ms |

Both one-hit runs emit identical byte counts (567); complete scans emit all 2,000
and 20,000 rows respectively. Peak document-body memory stays page-bounded rather
than growing with corpus size. The default 250,000-document, 256-character run emits
all 250,000 rows (76,139,104 serialized bytes) with a 0.1383 MiB peak.
Timing includes `tracemalloc` overhead and excludes
process startup, HTTP, server search, and real stdout I/O. It is not a production
latency estimate. Python tracing also does not measure Rust allocations or total RSS.

### Streaming Boundaries

- `find`, `peek`, and `skim` stream rg/NDJSON rows immediately; JSON retains only the
  bounded output rows. Other listing and facet commands are unchanged.
- Transport pages contain at most 150 documents, reduced for tighter document/page
  budgets. A small hit budget reduces the initial fetch, but sparse scans expand to
  regular-sized pages when more hits are needed. A size change can refetch an
  overlapping prefix, which is skipped using the absolute document position.
  An individual document can still be arbitrarily large; a character output budget
  is not a network byte limit. The dependency can temporarily retain adjacent pages.
- One-document lookahead may require the next whole API page. It preserves honest
  exhaustion reporting instead of assuming that hitting a limit means more exists.
- Selected IDs use bounded body-reordering windows. The ID selection itself is
  retained; stdin is validated to EOF before document fetching begins.
- Paperless can include an `all` array of matching IDs in each response. That
  server-generated metadata and startup schema memory are not included in the
  synthetic source, so total real-client memory is not strictly corpus-independent.
- Schema initialization and the first page must still finish before the first row.
  Streaming does not accelerate server-side search or add concurrent requests.
- A late failure leaves provisional rows and a nonzero exit, never a successful
  terminal summary. Consumers must check the summary and exit status.

`tests/test_discovery_streaming_http.py` separately tests real dependency pagination
and subprocess stdout against a local server. It blocks page two until the first
row is observed, verifies early-stop request counts, injects late HTTP errors, and
checks cleanup when the downstream reader closes its pipe.
