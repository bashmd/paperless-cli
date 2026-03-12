# Paperless CLI Plan (`pcli`) - API Contract First

Status: draft v2 (planning only, no implementation yet)

## 1. Scope and Goals

We are building a Python CLI (with `uv`) on top of `tb1337/paperless-api` (`pypaperless`) with two primary goals:

1. Excellent document information retrieval for LLM tool calls at scale.
2. Complete, predictable management flows for Paperless resources.

Non-goal for v1: replicate every Paperless-ngx UI behavior. The CLI will prioritize stable automation semantics and machine-friendly output.

## 2. Source-Capability Baseline (from `pypaperless`)

Confirmed capability groups:

1. Auth/token generation (`Paperless.generate_api_token`).
2. Generic resource access patterns: `get`, `list`, iterate pages, filters via query params, create/update/delete where supported.
3. Document-specific operations: search, more-like, download/preview/thumbnail, metadata, suggestions, notes create/delete, next ASN, email.
4. Permissions toggle on supported helpers using `full_perms=true`.
5. Additional resources: tags, correspondents, document types, storage paths, custom fields, share links, tasks, users, groups, workflows, mail resources, config, status, statistics, remote version.

## 3. LLM Retrieval Loop We Must Support

The CLI should map to this fast exploration loop:

1. `find` candidate documents (broad, cheap, ranked).
2. `facets` to refine search dimensions.
3. `peek` each candidate quickly (head-style preview).
4. `skim` query hits with context (grep-style across many docs).
5. `get` deep retrieval for selected documents/pages.

This is the minimum loop needed to handle huge corpora without pulling full documents too early.

## 4. Design Principles (contract rules)

1. Predictable shape: `pcli <resource> <action> ...`
2. Document shortcut: `pcli get <document-id>` maps to `pcli docs get <document-id>`.
3. LLM-friendly args: support both long flags and trailing `key=value`.
4. Discovery default output is ripgrep-style text (`format=rg`), with `json`/`ndjson` available.
5. Same names everywhere:
   - `id` for primary keys
   - `page`, `page_size`
   - `pages`, `max_pages` for content page slicing
   - `query` for document search query string
6. Deterministic errors: stable exit codes + structured error JSON.
7. Budget-first retrieval for large data:
   - `max_docs`, `max_pages_total`, `max_chars_total`, `max_hits_per_doc`
8. Pipeline-native operation:
   - `from_stdin=true` input
   - `format=ndjson` output
9. No hidden behavior for destructive actions (explicit confirmation unless `yes=true`/`--yes`).

## 5. Global Contract

## 5.1 Command grammar

Primary grammar:

```bash
pcli [global-options] <resource> <action> [positional...] [key=value...]
```

Document shortcut:

```bash
pcli [global-options] get <document-id> [key=value...]
```

## 5.2 Global options

```text
url=<base-url> | --url <base-url>
profile=<name> | --profile <name>
format=rg|json|text|ndjson | --format ...
raw=true|false | --raw
verbose=true|false | --verbose
timeout=<seconds> | --timeout <seconds>
```

`key=value` and `--option value` are equivalent. If both are present, last one wins.

`format=text` semantics:

1. `format=text` is for human-readable summaries only.
2. `format=text` is not stable for machine parsing.
3. `rg` is optimized for scan/readability; `json` and `ndjson` remain available for structured tooling.

`raw` semantics:

1. `raw=true` is only valid for binary-producing commands: `docs download`, `docs preview`, `docs thumbnail`.
2. For non-binary commands, `raw=true` is a validation error (exit code `2`).

## 5.3 Value parsing rules

1. Booleans: `true`/`false`
2. Null: `null`
3. Integers/floats parsed numerically
4. Lists:
   - CSV for simple lists: `tags=1,2,3`
   - JSON for complex values: `filter_rules='[{"rule_type":1}]'`
5. Unknown keys for list/search commands pass through as API query filters.

## 5.4 Output contract

`format=json` success envelope:

```json
{
  "ok": true,
  "resource": "docs",
  "action": "get",
  "data": {},
  "meta": {}
}
```

Error:

```json
{
  "ok": false,
  "error": {
    "code": "AUTH_INVALID_TOKEN",
    "message": "Token rejected by Paperless",
    "details": {}
  }
}
```

`format=ndjson` contract:

1. No outer envelope.
2. One JSON object per line.
3. Record schema:
   - `{"type":"item", ...}` for data rows
   - `{"type":"error", ...}` for stream-level failure records
   - final `{"type":"summary","meta":{"next_cursor":...}}` line
4. `next_cursor` is `null` when scan is complete.

Exit codes:

1. `0` success
2. `2` usage/validation error
3. `3` auth failure
4. `4` not found
5. `5` permission denied
6. `6` API/server error
7. `7` network/timeout

## 5.5 Streaming and chaining contract

For high-volume document retrieval commands (`docs find`, `docs peek`, `docs skim`):

1. `format=ndjson` emits one object per line for easy piping.
2. `from_stdin=true` reads document IDs from stdin:
   - newline-separated integers, or
   - NDJSON objects with `id` or `doc_id` field
3. `ids_only=true` emits minimal ID records to chain fast shortlist flows.
4. `from_stdin=true` and `ids=...` are mutually exclusive.
5. When IDs are provided (stdin or `ids=`), `query` is optional and acts as an additional filter.
6. For NDJSON stdin:
   - only `type="item"` records are consumed
   - `type="summary"` and `type="error"` are ignored

## 6. Auth and Token Storage Contract

Required UX from request:

```bash
pcli auth <username> <password> [url=<base-url>] [profile=<name>]
```

Behavior:

1. Calls Paperless token endpoint through `pypaperless` helper.
2. Stores token for automatic reuse.
3. Sets/updates active profile (default: `default`).

Storage:

1. Config file: `${XDG_CONFIG_HOME:-~/.config}/pcli/config.toml`
2. Credential file: `${XDG_CONFIG_HOME:-~/.config}/pcli/credentials.json`
3. Enforce `0600` on credential file.

Precedence for runtime connection values:

1. Explicit CLI args
2. Environment (`PCLI_URL`, `PCLI_TOKEN`, `PCLI_PROFILE`)
3. Active profile in config

Auth companion commands:

```bash
pcli auth status
pcli auth logout [profile=<name>]
pcli auth switch <profile>
pcli auth list
```

Reserved action-name rule:

1. The shorthand `pcli auth <username> <password>` reserves action keywords:
   - `login`, `status`, `list`, `switch`, `logout`
2. If username equals one of those keywords, use explicit login form:
   - `pcli auth login <username> <password> [url=...] [profile=...]`

## 7. Document Retrieval Contract (single-document deep retrieval)

## 7.1 Core command

```bash
pcli get <document-id> [pages=<spec>] [max_pages=<n>] [source=auto|ocr|archive|original]
```

Alias:

```bash
pcli docs get <document-id> ...
```

Default behavior:

1. Return document metadata + OCR text (`content`) quickly.
2. If `pages` is provided, perform page-aware extraction from downloadable file (`archive` by default; fallback based on `source`).

## 7.2 Page filter semantics

`pages` supports:

1. Single page: `pages=2`
2. Range: `pages=1-3`
3. Mixed: `pages=1,3,5-7`

Rules:

1. 1-based indexing.
2. Normalized and deduplicated in ascending order.
3. Invalid specs fail with exit code `2`.
4. `max_pages` caps selected pages after normalization.

## 7.3 Retrieval source semantics

1. `source=ocr`: use document `content` field only (no true per-page extraction).
2. `source=archive`: use archived file endpoint.
3. `source=original`: use original file endpoint.
4. `source=auto`:
   - no page filters: prefer `ocr`
   - with page filters: prefer `archive`, then `original`, then fail clearly if page extraction impossible.
5. `source=ocr` with `pages=...` is invalid and returns exit code `2`.

## 7.4 Retrieval output shape

```json
{
  "ok": true,
  "resource": "docs",
  "action": "get",
  "data": {
    "document": {},
    "text": "...",
    "pages": [1, 2, 3],
    "source": "archive",
    "truncated": false
  },
  "meta": {
    "id": 123,
    "page_count": 9
  }
}
```

## 7.5 Retrieval-adjacent doc commands

```bash
pcli docs list [query=<q>] [custom_field_query=<expr>] [page=1] [page_size=150] [<filter>=...]
pcli docs search <query> [page=1] [page_size=150] [<filter>=...]
pcli docs more-like <document-id> [page=1] [page_size=150]
pcli docs metadata <document-id>
pcli docs suggestions <document-id>
pcli docs download <document-id> [original=true|false] [output=<path>]
pcli docs preview <document-id> [original=true|false] [output=<path>]
pcli docs thumbnail <document-id> [original=true|false] [output=<path>]
pcli docs notes list <document-id>
pcli docs notes add <document-id> note="<text>"
pcli docs notes delete <document-id> <note-id> [yes=true]
pcli docs next-asn
pcli docs email docs=1,2 to="a@b.com,c@d.com" subject="..." message="..." [use_archive_version=true]
```

Search boundary:

1. `docs search` is a thin pass-through to Paperless search parameters and pagination.
2. `docs find` (below) is the LLM shortlist wrapper with deterministic defaults and projected output.

## 8. LLM Discovery and Bulk-Skim Contract

## 8.1 `docs find` (broad shortlist)

Goal: fast candidate discovery with small payloads.

```bash
pcli docs find query="..." [max_docs=200] [top=200] [page_size=150] [fields=id,title,created,score,snippet] [<filter>=...]
```

Rules:

1. Uses Paperless search/query capabilities first.
2. Returns sorted shortlist with stable ordering.
3. `fields` projects output to keep payload small.
4. Supports `ids_only=true` for fastest chaining.
5. `max_docs` is the canonical limit. `top` is a deprecated alias.
6. Default sort is deterministic (`score desc`, then `id asc` unless overridden).

## 8.2 `docs facets` (refinement map)

Goal: quickly understand where interesting docs are concentrated.

```bash
pcli docs facets query="..." by=tags,doc_type,correspondent,year [facet_scope=page|all] [top_values=20] [<filter>=...]
```

Output includes value/count buckets for requested facet dimensions.

Facet semantics:

1. Facets are client-side aggregations over matched documents; no server facet endpoint is assumed.
2. `facet_scope=page|all` controls whether counts are page-local or full scan (default: `page`).
3. `by=doc_type` maps to Paperless field `document_type`.

## 8.3 `docs peek` (head-style preview per doc)

Goal: one lightweight preview per document, no full extraction.

```bash
pcli docs peek [ids=1,2,3 | query="..."] [max_docs=20] [top=20] [per_doc_max_chars=1200] [max_chars=1200] [pages=1] [fields=id,title,created,tags,excerpt]
```

`peek` behavior:

1. No query required when IDs are known.
2. Returns one short excerpt per document (for rapid triage).
3. Excerpt source defaults to OCR content; if unavailable, use archive/original fallback when possible.
4. At least one selector source is required: `ids=...`, `query=...`, or `from_stdin=true`.
5. If IDs are provided (`ids` or stdin), `query` is optional and acts as an additional filter.

Example NDJSON record:

```json
{"type":"item","id":123,"title":"Invoice 2025-02","excerpt":"...","chars":782,"truncated":true}
```

## 8.4 `docs skim` (grep-style, query hit extraction)

Goal: extract only matching spans with context, across many docs.

```bash
pcli docs skim query="invoice number" [ids=1,2,3] [context_before=200] [context_after=300] [max_hits_per_doc=3] [max_docs=200] [format=ndjson]
```

`skim` behavior:

1. Query-driven, multi-hit extraction.
2. Context windows are character-based by default (better fit for OCR/PDF text than line-based chunks).
3. Returns zero-to-many hits per doc.
4. `skim` always requires `query`. Use `docs peek` for head-style previews.

Example NDJSON record:

```json
{"type":"item","doc_id":123,"page":null,"hit":"invoice number","start":1540,"end":1890,"text":"...context...","score":0.81}
```

Hit-field semantics:

1. `page` is nullable and only populated when page-level extraction is available.
2. `start` and `end` are character offsets in the extracted document text stream.

## 8.5 Pipeline examples (LLM-style chaining)

```bash
# shortlist -> skim
pcli docs find query="vendor:acme type:invoice" ids_only=true format=ndjson \
  | pcli docs skim from_stdin=true query="late fee" context_before=150 context_after=250 format=ndjson

# shortlist -> peek
pcli docs find query="contract renewal" ids_only=true format=ndjson \
  | pcli docs peek from_stdin=true per_doc_max_chars=900 format=ndjson
```

## 8.6 Budget and cursor controls for huge corpora

Supported controls on `find`/`peek`/`skim`:

1. `max_docs`
2. `max_pages_total`
3. `max_chars_total`
4. `per_doc_max_chars`
5. `max_hits_per_doc`
6. `stop_after_matches`
7. `cursor=<opaque-token>` for resumable scans

Normalization and stop order:

1. `max_docs` is canonical. `top` is deprecated alias.
2. `per_doc_max_chars` is canonical. `max_chars` (on `peek`) is deprecated alias.
3. Processing stops at the first reached limit among:
   - `max_docs`
   - `max_pages_total`
   - `max_chars_total`
   - `max_hits_per_doc`
   - `stop_after_matches`

Cursor semantics:

1. Cursor is a CLI-issued opaque token encoding normalized query/filter/sort/page_size and scan position.
2. Cursor is invalid if bound parameters change; return `CURSOR_MISMATCH` (exit code `2`).
3. `cursor` is mutually exclusive with explicit `page` and with `from_stdin=true`.

Cursor binding includes all output-shaping inputs:

1. `query`, filters, `sort`, `page_size`, `fields`
2. `context_before`, `context_after`
3. `per_doc_max_chars`, `max_hits_per_doc`

Response metadata includes `next_cursor` when more data is available.

## 9. Management Contract by Resource

Generic pattern (where supported):

```bash
pcli <resource> list [page=<n>] [page_size=<n>] [<filter>=...]
pcli <resource> get <id> [full_perms=true|false]
pcli <resource> create <field>=<value>...
pcli <resource> update <id> <field>=<value>... [only_changed=true|false]
pcli <resource> delete <id> [yes=true]
```

Resource map for v1:

1. Full CRUD: `docs`, `tags`, `correspondents`, `doc-types`, `storage-paths`, `custom-fields`, `share-links`
2. Read-only list/get: `users`, `groups`, `mail-accounts`, `mail-rules`, `processed-mail`, `saved-views`, `workflows`, `workflow-actions`, `workflow-triggers`
3. Singleton read: `status`, `stats`, `config`, `remote-version`
4. Tasks: `tasks list`, `tasks get <id-or-task_uuid>`

Notes:

1. `logs` is intentionally not exposed in `pypaperless` and excluded from v1.
2. Permissions expansion (`full_perms=true`) only applies to resources that support it.
3. `config get` defaults to `id=1` (override with `id=<n>`).

## 10. Mutation Safety and Consistency

1. `delete` requires `yes=true` or `--yes`.
2. `update` defaults to patch behavior (`only_changed=true`).
3. `create`/`update` errors return server payload in `error.details`.
4. `--dry-run` planned for v2 (not v1 blocker).

## 11. Step-by-Step Build Plan (implementation phases)

## Phase 1 - CLI Foundation

1. Initialize `uv` Python project and dependency baseline (`pypaperless`, CLI framework, test tools).
2. Implement argument parser supporting both flags and `key=value`.
3. Implement output/error envelope and exit code mapping.
4. Implement NDJSON mode and stdin ID ingestion primitives.
5. Set runtime baseline: Python `>=3.12,<3.15` (matches `pypaperless` compatibility).

## Phase 2 - Auth + Profile

1. Implement `auth` commands.
2. Implement profile/config resolution and env precedence.
3. Add secure credential file handling.

## Phase 3 - LLM Discovery Core

1. Implement `docs find`.
2. Implement `docs facets`.
3. Implement `docs peek`.
4. Implement `docs skim` with context windows.
5. Implement budget controls and resumable cursor metadata.

## Phase 4 - Deep Retrieval + Document Management

1. Implement `pcli get` + `docs get`.
2. Implement `pages` parser + `max_pages`.
3. Implement source strategy (`ocr/archive/original/auto`).
4. Implement metadata/suggestions/download/preview/thumbnail.
5. Implement notes add/list/delete, next ASN, email.
6. Implement create/update/delete document mutations.

## Phase 5 - Remaining Resources

1. Add generic adapters for CRUD/read-only resources from capability map.
2. Add permissions toggle support.

## Phase 6 - Quality Bar

1. Unit tests for parser, auth resolution, and command handlers.
2. Integration tests with mocked API responses.
3. Performance tests for large `find/peek/skim` workflows.
4. Minimal command cookbook focused on LLM invocation patterns.

## 12. Minimal User Instructions (target)

The tool should be understandable from this compact flow:

```bash
# 1) authenticate and store token
pcli auth <username> <password> url=https://paperless.example.com

# 2) find candidates
pcli docs find query="invoice acme" top=100

# 3) skim matches quickly with context
pcli docs skim query="late fee" max_docs=100 context_before=160 context_after=240 format=ndjson

# 4) open selected doc deeply
pcli get 123 pages=1-3 max_pages=2
```

---

If this contract looks right, next step is to lock decisions marked implicit (notably `find` ranking/snippet generation and cursor token encoding), then start Phase 1 implementation.
