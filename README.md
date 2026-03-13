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

Recommended one-liner from a repo (pinned ref, auto Rust acceleration when available):

```bash
uvx --from git+https://github.com/<org>/<repo>.git@<tag-or-commit> pcli install from=git+https://github.com/<org>/<repo>.git@<tag-or-commit> rust=auto
```

Direct global install:

```bash
uv tool install --from git+https://github.com/<org>/<repo>.git@<tag-or-commit> pcli
```

From a local checkout:

```bash
uv tool install --from . pcli
```

For local development with `uvx`, pin a commit/tag in `--from` to avoid stale cached builds.

## Upgrade

```bash
uv tool install --from git+https://github.com/<org>/<repo>.git@<tag-or-commit> pcli --reinstall
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
  | pcli docs peek from_stdin=true max_docs=30
```

Pipeline shortlist into skim:

```bash
pcli docs find query="late fee" ids_only=true format=ndjson \
  | pcli docs skim from_stdin=true query="late fee" context_before=120 context_after=200
```

Fetch one document:

```bash
pcli get 123
```

## Output Modes

1. `format=json`: stable envelope output for machine consumers.
2. `format=ndjson`: streaming `item`/`summary` records for pipelines.
3. `format=rg`: ripgrep-style scan output (default for `docs find|peek|skim`).
4. `format=text`: human-readable convenience mode (not contract-stable).

## Current Retrieval Limitation

`docs get` currently returns OCR-backed text (`source=ocr`) for deep retrieval.
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
