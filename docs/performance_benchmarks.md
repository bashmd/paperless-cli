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

Validate streaming memory behavior for NDJSON-heavy workloads:

```bash
uv run python benchmarks/ndjson_memory_check.py --items 250000 --text-size 256 --max-peak-mb 160
```

Expected behavior:

1. Exit code `0` and JSON `ok=true`.
2. `peak_memory_mb <= 160` for the default workload.
