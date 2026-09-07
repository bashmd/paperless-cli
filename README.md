# pcli

`pcli` is a Paperless-ngx CLI designed for reliable automation and LLM tool use.

The project focuses on two things:

1. Fast discovery and retrieval across large document sets.
2. Predictable management operations with stable, machine-friendly outputs.

It is built in Python, uses `uv`, and wraps Paperless through `pypaperless`.

## What It Can Do

### Discovery workflow (LLM-first)

Use a scalable shortlist loop:

1. `docs find` to discover candidate documents.
2. `docs facets` to inspect distribution by metadata fields.
3. `docs peek` to skim one excerpt per document.
4. `docs skim` to extract query hits with context windows.
5. `get` / `docs get` for deep retrieval on selected documents.

Discovery defaults to ripgrep-style output (`format=rg`) for scan speed/readability, while `json` and `ndjson` remain available.

### Document operations

`docs` supports:

1. `get`, `list`, `search`, `more-like`
2. `download`, `preview`, `thumbnail`
3. `metadata`, `suggestions`, `next-asn`, `email`
4. `create`, `update`, `delete`
5. `notes list`, `notes add`, `notes delete`

### Resource management

Generic resource families are exposed with consistent command shapes:

1. CRUD resources: `tags`, `correspondents`, `doc-types`, `storage-paths`, `custom-fields`, `share-links`
2. Read-only resources: `users`, `groups`, `mail-accounts`, `mail-rules`, `processed-mail`, `saved-views`, `workflows`, `workflow-actions`, `workflow-triggers`
3. Singleton reads: `status`, `stats`, `config`, `remote-version`
4. Task endpoints: `tasks list`, `tasks get`

### Auth and profiles

Profile-based auth with persisted token reuse:

1. `pcli auth <username> <password> url=<base-url>`
2. `pcli auth status`
3. `pcli auth list`
4. `pcli auth switch <profile>`
5. `pcli auth logout`

Credentials are stored under `${XDG_CONFIG_HOME:-~/.config}/pcli`.

## Install

Prerequisite: install `uv` first (<https://docs.astral.sh/uv/>).

Recommended one-liner from this repo (explicit ref, auto Rust acceleration when available):

```bash
uvx --from git+https://github.com/bashmd/paperless-cli.git@main pcli install from=git+https://github.com/bashmd/paperless-cli.git@main rust=auto
```

Direct global install:

```bash
uv tool install --from git+https://github.com/bashmd/paperless-cli.git@main pcli
```

From a local checkout:

```bash
uv tool install --from . pcli
```

For local development with `uvx`, pin a commit/tag in `--from` to avoid stale cached builds.

## Upgrade

```bash
uv tool install --from git+https://github.com/bashmd/paperless-cli.git@main pcli --reinstall
```

## Verify

```bash
pcli --version
pcli --help
```

## Quick Start

Authenticate:

```bash
pcli auth <username> <password> url=https://paperless.example.com
pcli auth status
```

Find candidate docs:

```bash
pcli docs find query="invoice acme" max_docs=50
```

Pipeline shortlist into peek:

```bash
pcli docs find query="invoice acme" ids_only=true format=ndjson \
  | pcli docs peek from_stdin=true allow_partial=true max_docs=30
```

Pipeline shortlist into skim:

```bash
pcli docs find query="late fee" ids_only=true format=ndjson \
  | pcli docs skim from_stdin=true allow_partial=true query="late fee" context_before=120 context_after=200
```

Fetch one document:

```bash
pcli get 123
```

Read bounded OCR chunks without JSON:

```bash
pcli get 123 format=text max_chars=5000
pcli get 123 format=text start_char=5000 max_chars=5000
```

## Output Modes

1. `format=json`: stable envelope output for machine consumers.
2. `format=ndjson`: streamed `item` records followed by a final `summary` for discovery pipelines.
3. `format=rg`: ripgrep-style scan output (default for `docs find|peek|skim`).
4. `format=text`: literal OCR text on `get`; rg-style output on discovery commands.

Other command groups currently emit JSON.

`find`, `peek`, and `skim` emit rg/NDJSON rows as documents are processed, without
loading the entire scan first. API pages contain at most 150 documents, fewer for
tight document/page budgets. Small match limits start with a small fetch; sparse
scans then expand to regular-sized pages. Selected IDs use bounded reorder windows to
preserve your input order. JSON still buffers the result rows into one envelope.

## Discovery Completion

Discovery summaries include `complete`, `stop_reason`, and `next_cursor`. A budget
limit is not exhaustion. Resume with the same query, filters, fields, and page size
plus `cursor=...`; per-call budgets may be changed. Cursors track document and hit
positions and are not snapshots: edits or reindexing during a scan can change order.
An initial `page=...` may produce a cursor, but omit `page` when resuming it.
Old v1 cursors must be replaced by starting a new scan.

Pipelines reject upstream failures, unterminated NDJSON, and incomplete producers.
Use `allow_partial=true` on a consumer only when you intentionally want a bounded
shortlist rather than exhaustive coverage. Its summary retains `input_complete=false`.
An impossible budget returns `BUDGET_TOO_SMALL`, never a misleading empty success.
Streamed rows are provisional until the final summary. A later request failure
exits nonzero without a success summary; NDJSON ends with an `error` record.
Lookahead may fetch another API page to distinguish a budget stop from exhaustion.
Stdin consumers validate the producer's full ID selection before fetching documents;
they retain the IDs, not the raw input or all document bodies.
Use `set -o pipefail` in shell pipelines too, to catch processes that fail before
emitting any records. Empty raw-ID input cannot distinguish that from an empty list.

`sort=-created` is translated to Paperless's `ordering` parameter. Full-text search
supports a single ordering field; unsupported composites are rejected. Default
search order is server relevance order, without per-batch local re-ranking.

## Current Retrieval Limitation

`docs get` returns OCR-backed text (`source=ocr`) once, without duplicating it in
document metadata. The default `max_chars=20000` bounds returned OCR text; choose a
larger positive value explicitly when needed. `start_char` is a zero-based Unicode
character offset in the original OCR text, not a byte offset or a normalized skim
offset. JSON reports `chars_total`, `start_char`, `end_char`, `next_start`, and
`truncated`; text mode puts only OCR text on stdout and a truncation/resume notice
on stderr. These bounds do not reduce the document response fetched from the API.

`max_pages` alone now fails explicitly rather than returning unlimited text.
Page-targeted extraction from archive/original files is not implemented yet; page/source combinations that require file extraction return explicit validation errors.

## Optional Rust Acceleration

The whitespace normalizer has an optional Rust extension (`pcli_rust_norm`) used in hot discovery paths.

Installer modes:

1. `rust=auto` (default): install Rust extension when possible, otherwise continue with Python fallback.
2. `rust=true`: require Rust extension install and fail if unavailable.
3. `rust=false`: skip Rust extension install.

Example:

```bash
pcli install from=. rust=auto
```

## Error and Safety Semantics

1. Deterministic exit codes (`0`, `2`, `3`, `4`, `5`, `6`, `7`).
2. Structured error payloads with stable error codes.
3. Destructive operations require explicit confirmation (`yes=true` / `--yes`).
4. `raw=true` is only valid for binary endpoints (`download`, `preview`, `thumbnail`).

## More Documentation

1. Cookbook with command patterns: [docs/command_cookbook.md](docs/command_cookbook.md)
2. Performance benchmark guide: [docs/performance_benchmarks.md](docs/performance_benchmarks.md)
3. Retrieval/cursor ADR: [docs/adr/0001-retrieval-and-cursor-decisions.md](docs/adr/0001-retrieval-and-cursor-decisions.md)

## License

MIT. See [LICENSE](LICENSE).
