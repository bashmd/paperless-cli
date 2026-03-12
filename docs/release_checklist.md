# Release Checklist

## 1. Pre-Release Validation

1. Ensure worktree is clean: `git status --short`.
2. Run full quality gate:
   - `uv run pytest -q`
   - `uv run ruff check .`
   - `uv run mypy`
3. Run discovery performance benchmark:
   - `uv run python benchmarks/discovery_benchmark.py --docs 10000 --chars 2500 --repeats 3`
4. Run NDJSON memory validation:
   - `uv run python benchmarks/ndjson_memory_check.py --items 250000 --text-size 256 --max-peak-mb 160`

## 2. Contract and Documentation Checks

1. Confirm `plan.md` contract changes (if any) are reflected in:
   - `docs/command_cookbook.md`
   - `docs/performance_benchmarks.md`
2. Verify new commands include tests covering:
   - success path
   - validation/failure path
3. Verify `implementation_plan.md` task checkboxes reflect merged work.

## 3. Versioning Notes

Use semantic versioning:

1. `MAJOR` for breaking CLI contract changes (argument semantics, output schema, exit-code behavior).
2. `MINOR` for backward-compatible command additions or option additions.
3. `PATCH` for bug fixes and documentation-only updates that do not change command contracts.

Tag format:

1. `v<major>.<minor>.<patch>` (for example `v1.4.2`).
2. Tag must point to a commit that passes the full quality gate above.

## 4. Release Procedure

1. Update changelog/release notes summary for the new version.
2. Bump version in package metadata (`pyproject.toml` / package `__init__`).
3. Commit version bump and notes.
4. Create signed tag:
   - `git tag -s vX.Y.Z -m "pcli vX.Y.Z"`
5. Push branch and tag:
   - `git push origin <branch>`
   - `git push origin vX.Y.Z`

## 5. Post-Release Smoke

1. Install from published artifact in a clean environment.
2. Verify:
   - `pcli --version`
   - `pcli --help`
   - `pcli auth --help`
   - `pcli docs find --help`
3. Execute one real API smoke command against a staging Paperless instance.
