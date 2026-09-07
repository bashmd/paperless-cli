---
name: paperless-cli
description: Find and read Paperless documents with pcli using efficient grep-like discovery, bounded previews, and targeted OCR or PDF retrieval.
---

# pcli Discovery Skill (rg-first)

Use this when your goal is: find relevant documents fast, skim massive corpora, then deep-read only the best IDs.

## 1. Startup Checklist

1. Confirm auth/profile is valid:
   - `pcli auth status`
2. Prefer one profile per target instance; switch explicitly if needed:
   - `pcli auth switch <profile>`
3. Discovery commands are rg-style by default (`docs find|peek|skim`), so you usually do not need `format=rg`.

## 2. Core Loop (Do This By Default)

1. Broad shortlist:
   - `pcli docs find query="<topic>" max_docs=300`
2. Cheap preview:
   - `pcli docs find query="<topic>" ids_only=true max_docs=300 format=ndjson | pcli docs peek from_stdin=true allow_partial=true max_docs=80 per_doc_max_chars=500`
3. Grep-like hit extraction with context:
   - `pcli docs find query="<topic>" ids_only=true max_docs=300 format=ndjson | pcli docs skim from_stdin=true allow_partial=true query="<needle>" context_before=120 context_after=220 max_hits_per_doc=2`
4. Deep retrieval only for selected docs:
   - `pcli get <doc-id> format=text max_chars=5000`

For the next raw OCR chunk, use `start_char=5000 max_chars=5000`. JSON mode gives
`next_start` explicitly; text mode warns on stderr when more text remains. The
default bound is 20,000 OCR characters. Do not use skim's normalized hit offsets as
raw `get` offsets. For actual PDF pages use `pcli get <id> pages=1,3-5` or
`max_pages=5`. Auto prefers the archive, then the original PDF. PDF offsets refer
to the selected pages joined with newline/form-feed/newline, not Paperless OCR.
Keep source/selection unchanged on chunk resumes; JSON `page_spans` gives page bounds.
`empty_pages` means no extracted text, not proof of blank pages. No new OCR is run.

## 3. Efficient Knobs

Use these early to control cost:

1. `max_docs`: hard cap on docs scanned.
2. `ids_only=true` (`find`): smallest shortlist payload.
3. `per_doc_max_chars` (`peek`): clamp excerpt size.
4. `max_hits_per_doc` (`skim`): prevent hit explosion.
5. `max_chars_total`, `max_pages_total`: global budget caps.
6. `stop_after_matches`: stop once enough evidence is found.

Use default `page_count` and raw OCR `chars_total` hints to decide whether to read
fully. Unknown sizes are null/-; peek `chars` is only excerpt size. Skim performs
case-insensitive literal matching, not regex; context bounds count characters,
not lines. Its query also filters candidates on the server, even with selected IDs.

## 4. Pipelining Rules

1. Use `format=ndjson` on producer commands when chaining into `from_stdin=true`.
2. `from_stdin=true` and `ids=...` are mutually exclusive.
3. `cursor` cannot be combined with `from_stdin=true` or explicit `page=...`.
4. NDJSON input can be either raw doc IDs or `type=item` records with `id`/`doc_id`.

## 5. rg Output Shape (Mental Model)

1. `find`: one line per doc, then `# summary ...`
2. `peek`: one line per doc + excerpt, then `# summary ...`
3. `skim`: header line `doc_id:page:start-end <hit>`, indented context line, optional `--`, then `# summary ...`

Treat `# summary` as end-of-batch metadata (`next_cursor`, counts, budgets consumed).
Rows stream before completion; a missing summary or failed exit means the result
cannot be treated as a successfully completed batch.

Check `complete` and `stop_reason`: limits do not mean exhaustion. Resume with the
same query/fields/page size and `cursor=...` (without `page`); per-call budgets can
change. The shortlist examples deliberately use `allow_partial=true` on consumers.
Without that opt-in, incomplete input fails instead of silently dropping coverage.
Upstream error records always fail the consumer, even with `allow_partial=true`.
Use `set -o pipefail` in shell pipelines as well: a process killed before emitting
anything cannot supply an error record.

## 6. Fast Triage Heuristics

1. Start broad with `find`, then narrow with `query` refinements or filters.
2. Use `peek` when deciding which docs are worth full retrieval.
3. Use `skim` when you need exact evidence snippets across many docs.
4. Only call `get` once you already have high-confidence IDs.

For corpus counts use `docs facets query=... by=tags,year facet_scope=all` and check
`corpus_complete`. Its default scope is only one page; `values_truncated` reports
top-value caps. Partial top-value lists cannot be summed into reliable corpus totals.

## 7. Safety Notes

1. Keep discovery mostly read-only (`find`, `peek`, `skim`, `get`).
2. Mutation commands (`create`, `update`, `delete`) are separate workflows; avoid mixing them into retrieval loops.
