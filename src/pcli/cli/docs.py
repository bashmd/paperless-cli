"""Document command group."""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from collections import Counter
from dataclasses import replace
from typing import Annotated, Any

import typer

from pcli.adapters.client import create_client
from pcli.adapters.document_search import DocumentSearchAdapter
from pcli.cli.io import emit_success
from pcli.core.errors import UsageValidationError
from pcli.core.options import FormatMode, GlobalOptions, parse_bool, parse_scalar
from pcli.core.output import ndjson_item, ndjson_summary
from pcli.core.parsing import parse_tokens
from pcli.core.validation import validate_raw_allowed
from pcli.models.discovery import DEFAULT_DISCOVERY_SORT, canonicalize_document_search

app = typer.Typer(help="Document discovery and management.", add_completion=False)

_FIND_KNOWN_OPTION_KEYS = {
    "query",
    "custom_field_query",
    "page",
    "page_size",
    "max_docs",
    "top",
    "fields",
    "ids_only",
    "sort",
    "url",
    "token",
    "profile",
    "timeout",
    "format",
    "raw",
    "verbose",
}
_DEFAULT_FIND_FIELDS = ["id", "title", "created", "score", "snippet"]
_SNIPPET_MAX_CHARS = 240
_PEEK_KNOWN_OPTION_KEYS = _FIND_KNOWN_OPTION_KEYS | {
    "ids",
    "from_stdin",
    "per_doc_max_chars",
    "max_chars",
}
_DEFAULT_PEEK_FIELDS = ["id", "title", "created", "tags", "excerpt"]
_DEFAULT_PEEK_MAX_DOCS = 20
_DEFAULT_PEEK_MAX_CHARS = 1200
_SKIM_KNOWN_OPTION_KEYS = _PEEK_KNOWN_OPTION_KEYS | {
    "context_before",
    "context_after",
    "max_hits_per_doc",
}
_DEFAULT_CONTEXT_BEFORE = 200
_DEFAULT_CONTEXT_AFTER = 300
_DEFAULT_MAX_HITS_PER_DOC = 3
_FACETS_KNOWN_OPTION_KEYS = _FIND_KNOWN_OPTION_KEYS | {"by", "facet_scope", "top_values"}
_DEFAULT_FACET_SCOPE = "page"
_DEFAULT_TOP_VALUES = 20
_FACETS_ALL_MAX_DOCS = 2_147_483_647
_SUPPORTED_FACET_FIELDS = {"tags", "doc_type", "document_type", "correspondent", "year"}
_FACET_FIELD_MAP = {
    "tags": "tags",
    "doc_type": "document_type",
    "document_type": "document_type",
    "correspondent": "correspondent",
    "year": "year",
}


def _parse_fields(value: str | None, *, default_fields: list[str]) -> list[str]:
    if value is None:
        return list(default_fields)
    parsed = parse_scalar(value)
    raw_items: list[Any]
    if isinstance(parsed, list):
        raw_items = parsed
    else:
        raw_items = [part for part in value.split(",")]

    fields: list[str] = []
    for raw_item in raw_items:
        field_name = str(raw_item).strip()
        if field_name:
            fields.append(field_name)
    if not fields:
        raise UsageValidationError(
            "fields must contain at least one field name.",
            details={"value": value},
            error_code="INVALID_FIELDS",
        )
    return fields


def _parse_positive_int(
    *,
    value: str | None,
    default: int,
    field_name: str,
    error_code: str,
) -> int:
    if value is None:
        return default
    parsed = parse_scalar(value)
    if not isinstance(parsed, int) or isinstance(parsed, bool) or parsed <= 0:
        raise UsageValidationError(
            f"{field_name} must be a positive integer.",
            details={"value": value},
            error_code=error_code,
        )
    return parsed


def _parse_non_negative_int(
    *,
    value: str | None,
    default: int,
    field_name: str,
    error_code: str,
) -> int:
    if value is None:
        return default
    parsed = parse_scalar(value)
    if not isinstance(parsed, int) or isinstance(parsed, bool) or parsed < 0:
        raise UsageValidationError(
            f"{field_name} must be a non-negative integer.",
            details={"value": value},
            error_code=error_code,
        )
    return parsed


def _normalize_scalar_output(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def _document_score(document: Any) -> float | None:
    search_hit = getattr(document, "search_hit", None)
    if search_hit is None:
        return None
    score = getattr(search_hit, "score", None)
    if score is None:
        return None
    try:
        return float(score)
    except (TypeError, ValueError):
        return None


def _synthesize_snippet(document: Any) -> str | None:
    search_hit = getattr(document, "search_hit", None)
    highlights = []
    if search_hit is not None:
        highlights = [
            getattr(search_hit, "highlights", None),
            getattr(search_hit, "note_highlights", None),
        ]
    for highlight in highlights:
        if isinstance(highlight, str) and highlight.strip():
            normalized = re.sub(r"\s+", " ", highlight).strip()
            if len(normalized) <= _SNIPPET_MAX_CHARS:
                return normalized
            return normalized[: _SNIPPET_MAX_CHARS - 3].rstrip() + "..."

    content = getattr(document, "content", None)
    if not isinstance(content, str):
        return None
    normalized_content = re.sub(r"\s+", " ", content).strip()
    if not normalized_content:
        return None
    if len(normalized_content) <= _SNIPPET_MAX_CHARS:
        return normalized_content
    return normalized_content[: _SNIPPET_MAX_CHARS - 3].rstrip() + "..."


def _sorted_find_documents(documents: list[Any]) -> list[Any]:
    def _sort_key(document: Any) -> tuple[int, float, int]:
        score = _document_score(document)
        doc_id = getattr(document, "id", None)
        normalized_id = int(doc_id) if isinstance(doc_id, int) else 0
        if score is None:
            return (1, 0.0, normalized_id)
        return (0, -score, normalized_id)

    return sorted(documents, key=_sort_key)


def _project_find_document(document: Any, fields: list[str]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for field_name in fields:
        if field_name == "score":
            projected[field_name] = _document_score(document)
            continue
        if field_name == "snippet":
            projected[field_name] = _synthesize_snippet(document)
            continue
        projected[field_name] = _normalize_scalar_output(getattr(document, field_name, None))
    return projected


def _parse_ids(value: str | None) -> list[int]:
    if value is None:
        return []
    parsed = parse_scalar(value)
    raw_items: list[Any]
    if isinstance(parsed, list):
        raw_items = parsed
    else:
        raw_items = [part for part in value.split(",")]

    ids: list[int] = []
    for raw_item in raw_items:
        try:
            item_id = int(str(raw_item).strip())
        except ValueError as exc:
            raise UsageValidationError(
                "ids must contain integers.",
                details={"value": raw_item},
                error_code="INVALID_IDS",
            ) from exc
        if item_id <= 0:
            raise UsageValidationError(
                "ids must contain positive integers.",
                details={"value": raw_item},
                error_code="INVALID_IDS",
            )
        ids.append(item_id)
    return ids


def _read_stdin_ids() -> list[int]:
    def _coerce_stdin_id(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized.isdigit():
                return None
            parsed = int(normalized)
            return parsed if parsed > 0 else None
        return None

    payload = sys.stdin.read()
    if not payload.strip():
        return []
    ids: list[int] = []
    for line in payload.splitlines():
        token = line.strip()
        if not token:
            continue
        parsed_line_id = _coerce_stdin_id(token)
        if parsed_line_id is not None:
            ids.append(parsed_line_id)
            continue
        try:
            obj = json.loads(token)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") != "item":
            continue
        candidate = _coerce_stdin_id(obj.get("id"))
        if candidate is None:
            candidate = _coerce_stdin_id(obj.get("doc_id"))
        if candidate is not None:
            ids.append(candidate)
    return ids


def _peek_source_text(document: Any) -> str:
    content = getattr(document, "content", None)
    if isinstance(content, str):
        normalized = re.sub(r"\s+", " ", content).strip()
        if normalized:
            return normalized

    search_hit = getattr(document, "search_hit", None)
    highlights = []
    if search_hit is not None:
        highlights = [
            getattr(search_hit, "highlights", None),
            getattr(search_hit, "note_highlights", None),
        ]
    for highlight in highlights:
        if isinstance(highlight, str):
            normalized = re.sub(r"\s+", " ", highlight).strip()
            if normalized:
                return normalized
    return ""


def _build_peek_excerpt(document: Any, *, max_chars: int) -> tuple[str, int, bool]:
    source = _peek_source_text(document)
    if len(source) <= max_chars:
        return source, len(source), False
    if max_chars <= 3:
        excerpt = source[:max_chars]
        return excerpt, len(excerpt), True
    excerpt = source[: max_chars - 3].rstrip() + "..."
    return excerpt, len(excerpt), True


def _project_peek_document(
    document: Any,
    fields: list[str],
    *,
    max_chars: int,
) -> dict[str, Any]:
    excerpt, char_count, truncated = _build_peek_excerpt(document, max_chars=max_chars)
    projected: dict[str, Any] = {}
    for field_name in fields:
        if field_name == "excerpt":
            projected[field_name] = excerpt
            continue
        projected[field_name] = _normalize_scalar_output(getattr(document, field_name, None))
    projected["chars"] = char_count
    projected["truncated"] = truncated
    return projected


def _extract_skim_hits(
    document: Any,
    *,
    query: str,
    context_before: int,
    context_after: int,
    max_hits_per_doc: int,
) -> list[dict[str, Any]]:
    source = _peek_source_text(document)
    if not source:
        return []

    pattern = re.compile(re.escape(query), re.IGNORECASE)
    hits: list[dict[str, Any]] = []
    for match in pattern.finditer(source):
        start, end = match.span()
        excerpt_start = max(0, start - context_before)
        excerpt_end = min(len(source), end + context_after)
        hits.append(
            {
                "doc_id": getattr(document, "id", None),
                "page": None,
                "hit": source[start:end],
                "start": start,
                "end": end,
                "text": source[excerpt_start:excerpt_end],
                "score": 1.0,
            }
        )
        if len(hits) >= max_hits_per_doc:
            break
    return hits


def _parse_by_fields(value: str | None) -> list[str]:
    if value is None:
        raise UsageValidationError(
            "docs facets requires by=<facet-list>.",
            error_code="MISSING_FACETS_BY",
        )
    parsed = parse_scalar(value)
    raw_items: list[Any]
    if isinstance(parsed, list):
        raw_items = parsed
    else:
        raw_items = [part for part in value.split(",")]

    by_fields: list[str] = []
    for raw_item in raw_items:
        name = str(raw_item).strip().lower()
        if not name:
            continue
        if name not in _SUPPORTED_FACET_FIELDS:
            raise UsageValidationError(
                "Unsupported facet field.",
                details={"field": name, "allowed": sorted(_SUPPORTED_FACET_FIELDS)},
                error_code="INVALID_FACET_FIELD",
            )
        by_fields.append(name)
    if not by_fields:
        raise UsageValidationError(
            "docs facets requires by=<facet-list>.",
            error_code="MISSING_FACETS_BY",
        )
    return by_fields


def _parse_facet_scope(value: str | None) -> str:
    if value is None:
        return _DEFAULT_FACET_SCOPE
    normalized = value.strip().lower()
    if normalized not in {"page", "all"}:
        raise UsageValidationError(
            "facet_scope must be one of: page, all.",
            details={"value": value},
            error_code="INVALID_FACET_SCOPE",
        )
    return normalized


def _parse_top_values(value: str | None) -> int:
    if value is None:
        return _DEFAULT_TOP_VALUES
    parsed = parse_scalar(value)
    if not isinstance(parsed, int) or isinstance(parsed, bool) or parsed <= 0:
        raise UsageValidationError(
            "top_values must be a positive integer.",
            details={"value": value},
            error_code="INVALID_TOP_VALUES",
        )
    return parsed


def _extract_facet_values(document: Any, internal_field: str) -> list[Any]:
    if internal_field == "tags":
        tags = getattr(document, "tags", None)
        if not isinstance(tags, list):
            return []
        return [tag for tag in tags if tag is not None]
    if internal_field == "year":
        created = getattr(document, "created", None)
        if isinstance(created, dt.datetime):
            return [created.year]
        if isinstance(created, dt.date):
            return [created.year]
        if isinstance(created, str):
            try:
                return [dt.datetime.fromisoformat(created).year]
            except ValueError:
                return []
        return []

    value = getattr(document, internal_field, None)
    if value is None:
        return []
    return [value]


def _build_facets(
    documents: list[Any],
    by_fields: list[str],
    *,
    top_values: int,
) -> dict[str, list[dict[str, Any]]]:
    facets: dict[str, list[dict[str, Any]]] = {}
    for output_field in by_fields:
        internal_field = _FACET_FIELD_MAP[output_field]
        counter: Counter[Any] = Counter()
        for document in documents:
            for value in _extract_facet_values(document, internal_field):
                counter[value] += 1
        ranked = sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))
        facets[output_field] = [
            {"value": _normalize_scalar_output(value), "count": count}
            for value, count in ranked[:top_values]
        ]
    return facets


@app.command(
    "find",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_find(
    ctx: typer.Context,
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Query/filter options."),
    ] = None,
) -> None:
    """Find candidate documents for LLM shortlist workflows."""
    raw_tokens = [*(tokens or []), *ctx.args]
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=_FIND_KNOWN_OPTION_KEYS,
        passthrough_filter_mode=True,
        boolean_option_keys={"raw", "verbose"},
        strict_boolean_values=True,
    )
    if parsed.positional or parsed.passthrough_tokens:
        raise UsageValidationError(
            "docs find accepts only key=value or --option arguments.",
            details={"positional": parsed.positional, "tokens": parsed.passthrough_tokens},
            error_code="UNEXPECTED_ARGS",
        )

    query = parsed.updates.get("query")
    if query is None or not str(query).strip():
        raise UsageValidationError(
            "docs find requires query=<search terms>.",
            error_code="MISSING_QUERY",
        )

    search = canonicalize_document_search(
        query=query,
        custom_field_query=parsed.updates.get("custom_field_query"),
        page=parsed.updates.get("page"),
        page_size=parsed.updates.get("page_size"),
        max_docs=parsed.updates.get("max_docs"),
        top=parsed.updates.get("top"),
        sort=parsed.updates.get("sort"),
        filters=parsed.passthrough_filters,
    )
    ids_only = False
    if "ids_only" in parsed.updates:
        ids_only = parse_bool(parsed.updates["ids_only"])
    fields = (
        ["id"]
        if ids_only
        else _parse_fields(parsed.updates.get("fields"), default_fields=_DEFAULT_FIND_FIELDS)
    )

    global_options = GlobalOptions.from_updates(parsed.updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs find")

    client, runtime_context = create_client(global_options)
    adapter = DocumentSearchAdapter()
    documents = adapter.collect_documents_sync(client, search)
    sorted_documents = (
        _sorted_find_documents(documents)
        if search.sort == DEFAULT_DISCOVERY_SORT
        else documents
    )
    rows = (
        [{"id": getattr(doc, "id", None)} for doc in sorted_documents]
        if ids_only
        else [_project_find_document(doc, fields) for doc in sorted_documents]
    )

    if global_options.format_mode is FormatMode.NDJSON:
        for row in rows:
            typer.echo(ndjson_item(row))
        typer.echo(ndjson_summary(next_cursor=None))
        return

    emit_success(
        resource="docs",
        action="find",
        data={"items": rows},
        meta={
            "count": len(rows),
            "page": search.page,
            "page_size": search.page_size,
            "max_docs": search.max_docs,
            "query": search.query,
            "sort": search.sort,
            "ids_only": ids_only,
            "profile": runtime_context.profile,
        },
    )


@app.command(
    "peek",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_peek(
    ctx: typer.Context,
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Selector/query/filter options."),
    ] = None,
) -> None:
    """Return one lightweight excerpt per selected document."""
    raw_tokens = [*(tokens or []), *ctx.args]
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=_PEEK_KNOWN_OPTION_KEYS,
        passthrough_filter_mode=True,
        boolean_option_keys={"raw", "verbose", "from_stdin"},
        strict_boolean_values=True,
    )
    if parsed.positional or parsed.passthrough_tokens:
        raise UsageValidationError(
            "docs peek accepts only key=value or --option arguments.",
            details={"positional": parsed.positional, "tokens": parsed.passthrough_tokens},
            error_code="UNEXPECTED_ARGS",
        )

    from_stdin = False
    if "from_stdin" in parsed.updates:
        from_stdin = parse_bool(parsed.updates["from_stdin"])

    explicit_ids = _parse_ids(parsed.updates.get("ids"))
    if from_stdin and explicit_ids:
        raise UsageValidationError(
            "from_stdin=true cannot be combined with ids=...",
            error_code="MUTUALLY_EXCLUSIVE_SELECTORS",
        )
    stdin_ids = _read_stdin_ids() if from_stdin else []
    selected_ids = explicit_ids or stdin_ids
    query = parsed.updates.get("query")
    has_query = query is not None and bool(str(query).strip())
    if not has_query and not selected_ids and not from_stdin:
        raise UsageValidationError(
            "docs peek requires one selector: ids=..., query=..., or from_stdin=true.",
            error_code="MISSING_SELECTOR",
        )

    max_chars_value = parsed.updates.get("per_doc_max_chars", parsed.updates.get("max_chars"))
    per_doc_max_chars = _parse_positive_int(
        value=max_chars_value,
        default=_DEFAULT_PEEK_MAX_CHARS,
        field_name="per_doc_max_chars",
        error_code="INVALID_PER_DOC_MAX_CHARS",
    )
    fields = _parse_fields(parsed.updates.get("fields"), default_fields=_DEFAULT_PEEK_FIELDS)

    filters: dict[str, Any] = dict(parsed.passthrough_filters)
    if selected_ids:
        filters["id__in"] = selected_ids

    max_docs_value = parsed.updates.get("max_docs")
    top_value = parsed.updates.get("top")
    if max_docs_value is None and top_value is None:
        max_docs_value = str(len(selected_ids) if selected_ids else _DEFAULT_PEEK_MAX_DOCS)

    search = canonicalize_document_search(
        query=query,
        custom_field_query=parsed.updates.get("custom_field_query"),
        page=parsed.updates.get("page"),
        page_size=parsed.updates.get("page_size"),
        max_docs=max_docs_value,
        top=top_value,
        sort=parsed.updates.get("sort"),
        filters=filters,
    )

    global_options = GlobalOptions.from_updates(parsed.updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs peek")

    if from_stdin and not selected_ids:
        emit_success(
            resource="docs",
            action="peek",
            data={"items": []},
            meta={
                "count": 0,
                "max_docs": 0,
                "per_doc_max_chars": per_doc_max_chars,
                "from_stdin": True,
                "query": search.query,
                "profile": global_options.profile or "default",
            },
        )
        return

    client, runtime_context = create_client(global_options)
    adapter = DocumentSearchAdapter()
    documents = adapter.collect_documents_sync(client, search)

    if selected_ids:
        rank = {doc_id: index for index, doc_id in enumerate(selected_ids)}
        fallback_rank = len(rank)

        def _selector_rank(document: Any) -> int:
            doc_id = getattr(document, "id", None)
            if not isinstance(doc_id, int):
                return fallback_rank
            return rank.get(doc_id, fallback_rank)

        documents = sorted(
            documents,
            key=_selector_rank,
        )

    rows = [
        _project_peek_document(document, fields, max_chars=per_doc_max_chars)
        for document in documents
    ]
    emit_success(
        resource="docs",
        action="peek",
        data={"items": rows},
        meta={
            "count": len(rows),
            "max_docs": search.max_docs,
            "per_doc_max_chars": per_doc_max_chars,
            "from_stdin": from_stdin,
            "query": search.query,
            "profile": runtime_context.profile,
        },
    )


@app.command(
    "skim",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_skim(
    ctx: typer.Context,
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Selector/query/filter options."),
    ] = None,
) -> None:
    """Extract query hits with context windows across many documents."""
    raw_tokens = [*(tokens or []), *ctx.args]
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=_SKIM_KNOWN_OPTION_KEYS,
        passthrough_filter_mode=True,
        boolean_option_keys={"raw", "verbose", "from_stdin"},
        strict_boolean_values=True,
    )
    if parsed.positional or parsed.passthrough_tokens:
        raise UsageValidationError(
            "docs skim accepts only key=value or --option arguments.",
            details={"positional": parsed.positional, "tokens": parsed.passthrough_tokens},
            error_code="UNEXPECTED_ARGS",
        )

    query = parsed.updates.get("query")
    if query is None or not str(query).strip():
        raise UsageValidationError(
            "docs skim requires query=<search terms>.",
            error_code="MISSING_QUERY",
        )

    from_stdin = False
    if "from_stdin" in parsed.updates:
        from_stdin = parse_bool(parsed.updates["from_stdin"])
    explicit_ids = _parse_ids(parsed.updates.get("ids"))
    if from_stdin and explicit_ids:
        raise UsageValidationError(
            "from_stdin=true cannot be combined with ids=...",
            error_code="MUTUALLY_EXCLUSIVE_SELECTORS",
        )
    stdin_ids = _read_stdin_ids() if from_stdin else []
    selected_ids = explicit_ids or stdin_ids

    context_before = _parse_non_negative_int(
        value=parsed.updates.get("context_before"),
        default=_DEFAULT_CONTEXT_BEFORE,
        field_name="context_before",
        error_code="INVALID_CONTEXT_BEFORE",
    )
    context_after = _parse_non_negative_int(
        value=parsed.updates.get("context_after"),
        default=_DEFAULT_CONTEXT_AFTER,
        field_name="context_after",
        error_code="INVALID_CONTEXT_AFTER",
    )
    max_hits_per_doc = _parse_positive_int(
        value=parsed.updates.get("max_hits_per_doc"),
        default=_DEFAULT_MAX_HITS_PER_DOC,
        field_name="max_hits_per_doc",
        error_code="INVALID_MAX_HITS_PER_DOC",
    )

    filters: dict[str, Any] = dict(parsed.passthrough_filters)
    if selected_ids:
        filters["id__in"] = selected_ids

    max_docs_value = parsed.updates.get("max_docs")
    top_value = parsed.updates.get("top")
    if max_docs_value is None and top_value is None and selected_ids:
        max_docs_value = str(len(selected_ids))

    search = canonicalize_document_search(
        query=query,
        custom_field_query=parsed.updates.get("custom_field_query"),
        page=parsed.updates.get("page"),
        page_size=parsed.updates.get("page_size"),
        max_docs=max_docs_value,
        top=top_value,
        sort=parsed.updates.get("sort"),
        filters=filters,
    )

    global_options = GlobalOptions.from_updates(parsed.updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs skim")

    if from_stdin and not selected_ids:
        emit_success(
            resource="docs",
            action="skim",
            data={"items": []},
            meta={
                "count": 0,
                "docs_scanned": 0,
                "docs_with_hits": 0,
                "max_docs": search.max_docs,
                "max_hits_per_doc": max_hits_per_doc,
                "context_before": context_before,
                "context_after": context_after,
                "query": search.query,
                "from_stdin": True,
                "profile": global_options.profile or "default",
            },
        )
        return

    client, runtime_context = create_client(global_options)
    adapter = DocumentSearchAdapter()
    documents = adapter.collect_documents_sync(client, search)

    normalized_query = search.query or ""
    items: list[dict[str, Any]] = []
    docs_with_hits = 0
    for document in documents:
        doc_hits = _extract_skim_hits(
            document,
            query=normalized_query,
            context_before=context_before,
            context_after=context_after,
            max_hits_per_doc=max_hits_per_doc,
        )
        if doc_hits:
            docs_with_hits += 1
            items.extend(doc_hits)

    emit_success(
        resource="docs",
        action="skim",
        data={"items": items},
        meta={
            "count": len(items),
            "docs_scanned": len(documents),
            "docs_with_hits": docs_with_hits,
            "max_docs": search.max_docs,
            "max_hits_per_doc": max_hits_per_doc,
            "context_before": context_before,
            "context_after": context_after,
            "query": search.query,
            "from_stdin": from_stdin,
            "profile": runtime_context.profile,
        },
    )


@app.command(
    "facets",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_facets(
    ctx: typer.Context,
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Query/facet/filter options."),
    ] = None,
) -> None:
    """Aggregate facet counts over matching documents."""
    raw_tokens = [*(tokens or []), *ctx.args]
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=_FACETS_KNOWN_OPTION_KEYS,
        passthrough_filter_mode=True,
        boolean_option_keys={"raw", "verbose"},
        strict_boolean_values=True,
    )
    if parsed.positional or parsed.passthrough_tokens:
        raise UsageValidationError(
            "docs facets accepts only key=value or --option arguments.",
            details={"positional": parsed.positional, "tokens": parsed.passthrough_tokens},
            error_code="UNEXPECTED_ARGS",
        )

    query = parsed.updates.get("query")
    if query is None or not str(query).strip():
        raise UsageValidationError(
            "docs facets requires query=<search terms>.",
            error_code="MISSING_QUERY",
        )
    by_fields = _parse_by_fields(parsed.updates.get("by"))
    facet_scope = _parse_facet_scope(parsed.updates.get("facet_scope"))
    top_values = _parse_top_values(parsed.updates.get("top_values"))

    search = canonicalize_document_search(
        query=query,
        custom_field_query=parsed.updates.get("custom_field_query"),
        page=parsed.updates.get("page"),
        page_size=parsed.updates.get("page_size"),
        max_docs=parsed.updates.get("max_docs"),
        top=parsed.updates.get("top"),
        sort=parsed.updates.get("sort"),
        filters=parsed.passthrough_filters,
    )
    has_explicit_doc_limit = "max_docs" in parsed.updates or "top" in parsed.updates
    if facet_scope == "page":
        search = replace(search, max_docs=min(search.max_docs, search.page_size))
    else:
        search = replace(search, page=1)
        if not has_explicit_doc_limit:
            search = replace(search, max_docs=_FACETS_ALL_MAX_DOCS)

    global_options = GlobalOptions.from_updates(parsed.updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs facets")
    client, runtime_context = create_client(global_options)
    adapter = DocumentSearchAdapter()
    documents = adapter.collect_documents_sync(client, search)
    facets = _build_facets(documents, by_fields, top_values=top_values)

    emit_success(
        resource="docs",
        action="facets",
        data={"facets": facets},
        meta={
            "query": search.query,
            "facet_scope": facet_scope,
            "top_values": top_values,
            "scanned_docs": len(documents),
            "profile": runtime_context.profile,
            "max_docs": (
                None
                if facet_scope == "all" and not has_explicit_doc_limit
                else search.max_docs
            ),
        },
    )
