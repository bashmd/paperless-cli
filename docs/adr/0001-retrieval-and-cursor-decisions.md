# ADR 0001: Retrieval Ranking, Snippets, and Cursor Encoding

Status: accepted  
Date: 2026-03-12

## Context

The CLI contract in `plan.md` requires deterministic shortlist behavior for `docs find` and resumable scans via cursor tokens.

Two implementation choices must be locked before feature work:

1. How ranking and snippets are produced for `docs find`.
2. How cursor tokens are encoded and validated across resumptions.

## Decision

1. `docs find` ranking:
   - Primary sort key: server-provided search score, descending.
   - Tie-breaker: document id, ascending.
   - If score is unavailable, fallback to id ascending.

2. `docs find` snippet source:
   - Prefer search-hit snippet data when exposed by server responses.
   - Otherwise synthesize from OCR `content` with deterministic truncation.

3. Cursor encoding:
   - Opaque URL-safe base64 JSON payload with version field (`v`).
   - Includes normalized scan inputs and current scan position.
   - Cursor is rejected with `CURSOR_MISMATCH` when normalized inputs differ.

4. Compatibility:
   - Cursor format is internal; decoding is not part of public contract.
   - Backward compatibility is only guaranteed within same major `pcli` version.

## Consequences

1. Results remain stable and deterministic for repeated queries.
2. Cursor behavior can be validated reliably across pipelines.
3. Future ranking changes require a new ADR and corresponding tests.
