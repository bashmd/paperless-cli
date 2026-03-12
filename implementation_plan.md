# Paperless CLI Implementation Plan

Status: draft v1  
Input spec: [plan.md](/home/cmd/distro-boxes/ubuntu-2404/paperless-cli/plan.md)

## 1. Objective

Implement `pcli` in phased increments so each phase is shippable and testable, while preserving the API contract in `plan.md`.

## 2. Global Acceptance Criteria

1. All implemented commands conform to grammar and option behavior defined in `plan.md`.
2. Contract modes `format=json` and `format=ndjson` are stable and tested.
3. Exit codes are deterministic (`0/2/3/4/5/6/7`) and mapped consistently.
4. Python runtime baseline is `>=3.12,<3.15`.
5. No phase merges without automated tests for new behavior.

## 2.1 Execution Tracking

- [x] `P0-T1` Initialize project structure and tooling.
- [x] `P0-T2` Define package layout (`cli`, `core`, `adapters`, `models`, `tests`).
- [x] `P0-T3` Add CI-quality local checks (`pytest`, lint, type checks).
- [x] `P0-T4` Add baseline command entrypoint (`pcli --help`).
- [x] `P0-T5` Lock implicit contract decisions in ADR.
- [x] `P1-T1` Build argument normalization layer.
- [x] `P1-T2` Implement typed value parser.
- [x] `P1-T3` Implement global options handling.
- [x] `P1-T4` Implement output adapters.
- [x] `P1-T5` Implement error model and exit-code mapper.
- [x] `P1-T6` Implement validation framework for command-level constraints.
- [x] `P1-T7` Implement query-filter passthrough rules.
- [x] `P2-T1` Implement config and credential stores.
- [x] `P2-T2` Enforce secure file permissions (`0600`) for credential file.
- [x] `P2-T3` Implement runtime precedence resolver.
- [x] `P2-T4` Implement auth commands.
- [x] `P2-T5` Build API client factory.
- [x] `P3-T1` Implement document search adapter and canonical query/filter model.
- [x] `P3-T2` Implement `docs find`.
- [x] `P3-T3` Implement `docs facets`.
- [x] `P3-T4` Implement `docs peek`.
- [x] `P3-T5` Implement `docs skim`.
- [x] `P3-T6` Implement stdin/selector contract.
- [x] `P3-T7` Implement `ids_only=true` output mode for `docs find`.
- [x] `P3-T8` Implement budget controls and alias normalization.
- [x] `P3-T9` Implement cursor rules.
- [x] `P4-T1` Implement `pcli get` alias to `docs get`.
- [x] `P4-T2` Implement page spec parser.
- [x] `P4-T3` Implement source strategy.
- [x] `P4-T4` Implement `docs list/search/more-like`.
- [x] `P4-T5` Implement binary endpoints.
- [x] `P4-T6` Implement metadata/suggestions/next-asn/email.
- [x] `P4-T7` Implement document notes.
- [x] `P4-T8` Implement document mutations.
- [x] `P5-T1` Build reusable resource handler abstraction.
- [x] `P5-T2` Implement CRUD resources.
- [x] `P5-T3` Implement read-only resources.
- [x] `P5-T4` Implement singleton reads.
- [ ] `P5-T5` Implement tasks endpoint.
- [ ] `P5-T6` Implement permissions expansion option.
- [ ] `P6-T1` Expand test coverage for failure modes and boundary conditions.
- [ ] `P6-T2` Add performance benchmarks for large-scale workflows.
- [ ] `P6-T3` Validate memory behavior in NDJSON streaming workloads.
- [ ] `P6-T4` Produce command cookbook.
- [ ] `P6-T5` Add release checklist and versioning notes.

## 3. Phase Breakdown

## Phase 0 - Project Bootstrap and Skeleton

Objective: establish a runnable, testable CLI codebase with `uv`.

### Tasks

1. `P0-T1` Initialize project structure and tooling.
2. `P0-T2` Define package layout (`cli`, `core`, `adapters`, `models`, `tests`).
3. `P0-T3` Add CI-quality local checks (`pytest`, lint, type checks).
4. `P0-T4` Add baseline command entrypoint (`pcli --help`).
5. `P0-T5` Lock implicit contract decisions in a short ADR:
   - `find` ranking and snippet generation behavior
   - cursor token encoding and compatibility rules.

### Acceptance Criteria

1. `uv run pcli --help` exits `0`.
2. `uv run pytest` runs successfully with bootstrap tests.
3. Python constraint is declared and enforced in project metadata.
4. Adding a new command requires only:
   - one handler module
   - one registry/dispatch entry
   - no parser/core refactor.
5. ADR from `P0-T5` is committed and referenced by later phase tasks.

## Phase 1 - Core Contract Engine

Objective: implement shared parsing, validation, output, and error infrastructure.

### Tasks

1. `P1-T1` Build argument normalization layer:
   - support both `--flag value` and `key=value`
   - apply last-wins precedence.
2. `P1-T2` Implement typed value parser:
   - bool/null/number/list(JSON/CSV) coercion.
3. `P1-T3` Implement global options handling:
   - `url`, `profile`, `format`, `raw`, `verbose`, `timeout`
   - `format=text` as human-readable non-contract mode.
4. `P1-T4` Implement output adapters:
   - JSON envelope mode
   - NDJSON stream mode with `item/error/summary`.
5. `P1-T5` Implement error model and exit-code mapper.
6. `P1-T6` Implement validation framework for command-level constraints.
7. `P1-T7` Implement query-filter passthrough rules:
   - unknown keys pass through for `list/search/find` style commands.

### Acceptance Criteria

1. JSON mode always returns envelope for non-stream commands.
2. NDJSON mode emits typed records and terminal `summary` with `next_cursor`.
3. Invalid `raw=true` on non-binary commands returns exit code `2`.
4. Unknown/invalid input types produce structured `usage/validation` errors.
5. `format=text` behavior is documented and validated as non-machine-contract mode.
6. Unknown filter passthrough is verified for `list/search/find`.
7. Unit tests cover parser coercion and exit code mapping edge-cases.

## Phase 2 - Auth, Profiles, and Runtime Context

Objective: implement authentication and persistent profile/token handling.

### Tasks

1. `P2-T1` Implement config and credential stores:
   - config: `${XDG_CONFIG_HOME:-~/.config}/pcli/config.toml`
   - credentials: `${XDG_CONFIG_HOME:-~/.config}/pcli/credentials.json`.
2. `P2-T2` Enforce secure file permissions (`0600`) for credential file.
3. `P2-T3` Implement runtime precedence resolver:
   - CLI args > `PCLI_URL`/`PCLI_TOKEN`/`PCLI_PROFILE` > active profile.
4. `P2-T4` Implement auth commands:
   - `auth <username> <password>`
   - `auth login <username> <password>` for reserved action-name usernames
   - `auth status`
   - `auth logout`
   - `auth switch`
   - `auth list`.
5. `P2-T5` Build API client factory around `pypaperless` session lifecycle.

### Acceptance Criteria

1. `pcli auth <user> <pass> url=...` stores usable token and active profile.
2. Commands run without explicit token after auth.
3. Auth failures map to exit code `3` with stable error codes/messages.
4. Credential file has `0600` permissions on supported platforms.
5. Integration tests validate precedence resolution and auth command flows.

## Phase 3 - LLM Discovery Core (`find`/`facets`/`peek`/`skim`)

Objective: deliver high-throughput discovery and skim pipeline.

### Tasks

1. `P3-T1` Implement document search adapter and canonical query/filter model.
2. `P3-T2` Implement `docs find`:
   - projected fields
   - deterministic default sort
   - `max_docs` with deprecated `top` alias.
   - must follow ADR 0001 ranking/snippet decisions.
3. `P3-T3` Implement `docs facets`:
   - client-side aggregation
   - `facet_scope=page|all`
   - default `facet_scope=page`
   - mapping `doc_type -> document_type`.
4. `P3-T4` Implement `docs peek`:
   - selector handling (`ids`, `query`, `from_stdin`)
   - per-doc excerpt generation and truncation metadata.
5. `P3-T5` Implement `docs skim`:
   - required query
   - context extraction (`context_before`/`context_after`)
   - hit schema with nullable `page` and offsets.
6. `P3-T6` Implement stdin/selector contract:
   - `from_stdin=true` accepts newline ints and NDJSON `type=item` records
   - supports `id` and `doc_id` keys
   - ignores `summary` and `error` input records
   - enforces `from_stdin=true` and `ids=...` mutual exclusivity
   - when IDs are provided (`stdin` or `ids`), `query` is optional additional filter.
7. `P3-T7` Implement `ids_only=true` output mode for `docs find`.
8. `P3-T8` Implement budget controls and alias normalization:
   - `max_docs`, `max_pages_total`, `max_chars_total`, `per_doc_max_chars`, `max_hits_per_doc`, `stop_after_matches`
   - normalize `top -> max_docs`
   - normalize `max_chars -> per_doc_max_chars` (`peek`)
   - enforce documented stop order.
9. `P3-T9` Implement cursor rules:
   - bind cursor to normalized query/filter/sort/page_size/fields/context/budget parameters
   - enforce cursor exclusion with explicit `page` and `from_stdin=true`
   - return `CURSOR_MISMATCH` on drift
   - emit terminal NDJSON `summary` with `next_cursor` (`null` when complete).
   - must follow ADR 0001 cursor encoding compatibility decisions.

### Acceptance Criteria

1. `find -> skim` and `find -> peek` pipelines work in NDJSON mode end-to-end.
2. `skim` rejects missing query with exit code `2`.
3. `ids_only=true` emits chainable ID-only `item` records.
4. `from_stdin=true` with `ids=...` fails with exit code `2`.
5. `peek` without selector source fails with exit code `2`.
6. Budget limits and stop-order behavior are enforced and tested.
7. Cursor is rejected when combined with `page` or `from_stdin=true`.
8. Cursor resume works when parameters match and fails with `CURSOR_MISMATCH` when they differ.
9. NDJSON terminal `summary` always includes `next_cursor`, set to `null` when complete.
10. Tests cover large-input streaming and stdin precedence edge-cases.

## Phase 4 - Deep Retrieval and Document Operations

Objective: implement `get` and document-specific management features.

### Tasks

1. `P4-T1` Implement `pcli get` alias to `docs get`.
2. `P4-T2` Implement page spec parser:
   - `1`, `1-3`, `1,3,5-7`
   - normalization + dedupe + `max_pages`.
3. `P4-T3` Implement source strategy:
   - `auto|ocr|archive|original`
   - `auto` fallback order: `ocr` (no pages), `archive` then `original` (with pages)
   - enforce `source=ocr` + `pages` invalid.
4. `P4-T4` Implement `docs list/search/more-like`.
5. `P4-T5` Implement binary endpoints:
   - `download`, `preview`, `thumbnail`
   - `raw=true` and output path behavior.
6. `P4-T6` Implement metadata/suggestions/next-asn/email.
7. `P4-T7` Implement document notes:
   - list/add/delete.
8. `P4-T8` Implement document mutations:
   - create/update/delete with safety checks
   - default update mode `only_changed=true` with override `only_changed=false`
   - preserve server payload in `error.details` for create/update failures.

### Acceptance Criteria

1. `pcli get <id>` returns JSON envelope with required keys:
   - `ok`, `resource`, `action`, `data`, `meta`
   - and retrieval payload fields from the spec.
2. Invalid page specs fail with exit code `2`.
3. `source=ocr pages=...` fails with exit code `2`.
4. `source=auto` follows documented fallback order and returns clear failure when page extraction is not possible.
5. Binary commands enforce `raw` and `output` semantics exactly as specified.
6. Delete operations require explicit confirmation (`yes=true`/`--yes`).
7. `docs update` defaults to patch behavior and supports explicit full update override.
8. Create/update failures preserve server payload in `error.details`.
9. Integration tests cover all doc subcommands.

## Phase 5 - Generic Resource Management

Objective: implement non-document resources with consistent command patterns.

### Tasks

1. `P5-T1` Build reusable resource handler abstraction:
   - list/get/create/update/delete patterns
   - default update mode `only_changed=true` with explicit override
   - create/update failure mapping with server payload in `error.details`
   - delete confirmation guard (`yes=true`/`--yes`) for destructive actions.
2. `P5-T2` Implement CRUD resources:
   - `tags`, `correspondents`, `doc-types`, `storage-paths`, `custom-fields`, `share-links`.
3. `P5-T3` Implement read-only resources:
   - `users`, `groups`, `mail-accounts`, `mail-rules`, `processed-mail`, `saved-views`, `workflows`, `workflow-actions`, `workflow-triggers`.
4. `P5-T4` Implement singleton reads:
   - `status`, `stats`, `config`, `remote-version`.
5. `P5-T5` Implement tasks endpoint:
   - `tasks list`
   - `tasks get <id-or-task_uuid>`.
6. `P5-T6` Implement permissions expansion option where supported (`full_perms=true`).

### Acceptance Criteria

1. Each resource command obeys the global parser/output/error contract.
2. Unsupported operations fail with explicit validation errors.
3. `config get` defaults to `id=1`, overridable with `id=<n>`.
4. Resource command matrix matches section 9 of `plan.md`.
5. Integration tests cover:
   - list/get for each resource family
   - at least one create/update/delete path for every CRUD resource.
6. CRUD resource updates default to patch-style behavior and honor override.
7. CRUD create/update failures include server payload in `error.details`.
8. Resource deletes require explicit confirmation (`yes=true`/`--yes`).

## Phase 6 - Hardening, Performance, and Documentation

Objective: finalize quality, performance, and operator guidance.

### Tasks

1. `P6-T1` Expand test coverage for failure modes and boundary conditions.
2. `P6-T2` Add performance benchmarks for large-scale `find/peek/skim`.
3. `P6-T3` Validate memory behavior in NDJSON streaming workloads.
4. `P6-T4` Produce command cookbook:
   - LLM pipeline examples
   - auth/profile quick start
   - retrieval and management snippets.
5. `P6-T5` Add release checklist and versioning notes.

### Acceptance Criteria

1. Test suite covers parser, auth, streaming, cursor, retrieval, and resource operations.
2. Benchmark thresholds are documented for regression tracking.
3. Cookbook examples run as documented.
4. Release checklist is complete and executable.

## 4. Cross-Phase Dependencies

1. Phase 1 is required before all feature phases.
2. Phase 2 is required before any API-backed command tests.
3. Phase 3 should precede Phase 4 to establish retrieval primitives and cursor/stream infrastructure.
4. Phase 5 depends on finalized generic handlers from Phase 1 and API client from Phase 2.
5. Phase 6 starts after Phases 3-5 reach feature-complete status.

## 5. Risk Register and Mitigations

1. Risk: page-level text extraction complexity for mixed document formats.
   - Mitigation: keep fallback hierarchy explicit and return clear partial-result metadata.
2. Risk: cursor inconsistency across changing datasets.
   - Mitigation: bind cursor to parameter set and return deterministic mismatch errors.
3. Risk: large corpus performance/memory pressure.
   - Mitigation: strict budget enforcement, streaming-only pipelines, benchmark gates.
4. Risk: contract drift between implementation and `plan.md`.
   - Mitigation: add spec-conformance tests keyed to major contract rules.

## 6. Definition of Done

1. Phases 0-6 completed with all acceptance criteria met.
2. All implemented commands documented and validated against `plan.md`.
3. No open critical defects in auth, retrieval pipeline, or destructive operation safeguards.
