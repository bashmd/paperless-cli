"""Document command group."""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import re
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any, cast

import typer

from pcli.adapters.client import create_client
from pcli.adapters.document_search import DocumentSearchAdapter
from pcli.adapters.resource_handler import (
    apply_mutation_fields,
    coerce_mutation_fields,
    mutation_error_details,
    require_confirmation,
    resolve_only_changed,
)
from pcli.cli.io import emit_success
from pcli.core.cursor import decode_cursor, encode_cursor
from pcli.core.errors import PcliError, UsageValidationError
from pcli.core.options import FormatMode, GlobalOptions, parse_bool, parse_scalar
from pcli.core.output import ndjson_item, ndjson_summary
from pcli.core.page_spec import normalize_page_selection
from pcli.core.parsing import parse_tokens
from pcli.core.retrieval_source import parse_retrieval_source, resolve_source_candidates
from pcli.core.validation import validate_raw_allowed
from pcli.models.discovery import DEFAULT_DISCOVERY_SORT, canonicalize_document_search

app = typer.Typer(help="Document discovery and management.", add_completion=False)
notes_app = typer.Typer(help="Document note operations.", add_completion=False)
app.add_typer(notes_app, name="notes")

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
    "max_pages_total",
    "max_chars_total",
    "stop_after_matches",
    "per_doc_max_chars",
    "max_chars",
    "max_hits_per_doc",
    "cursor",
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
_LIST_KNOWN_OPTION_KEYS = {
    "query",
    "custom_field_query",
    "page",
    "page_size",
    "sort",
    "url",
    "token",
    "profile",
    "timeout",
    "format",
    "raw",
    "verbose",
}
_SEARCH_KNOWN_OPTION_KEYS = _LIST_KNOWN_OPTION_KEYS - {"query"}
_MORE_LIKE_KNOWN_OPTION_KEYS = {
    "page",
    "page_size",
    "sort",
    "url",
    "token",
    "profile",
    "timeout",
    "format",
    "raw",
    "verbose",
}
_BINARY_KNOWN_OPTION_KEYS = {
    "original",
    "output",
    "url",
    "token",
    "profile",
    "timeout",
    "format",
    "raw",
    "verbose",
}
_METADATA_KNOWN_OPTION_KEYS = {
    "url",
    "token",
    "profile",
    "timeout",
    "format",
    "raw",
    "verbose",
}
_SUGGESTIONS_KNOWN_OPTION_KEYS = _METADATA_KNOWN_OPTION_KEYS
_NEXT_ASN_KNOWN_OPTION_KEYS = _METADATA_KNOWN_OPTION_KEYS
_EMAIL_KNOWN_OPTION_KEYS = {
    "docs",
    "to",
    "subject",
    "message",
    "use_archive_version",
    "url",
    "token",
    "profile",
    "timeout",
    "format",
    "raw",
    "verbose",
}
_NOTES_LIST_KNOWN_OPTION_KEYS = _METADATA_KNOWN_OPTION_KEYS
_NOTES_ADD_KNOWN_OPTION_KEYS = _METADATA_KNOWN_OPTION_KEYS | {"note"}
_NOTES_DELETE_KNOWN_OPTION_KEYS = _METADATA_KNOWN_OPTION_KEYS | {"yes"}
_CREATE_KNOWN_OPTION_KEYS = _METADATA_KNOWN_OPTION_KEYS | {"document", "filename"}
_UPDATE_KNOWN_OPTION_KEYS = _METADATA_KNOWN_OPTION_KEYS | {"only_changed"}
_DELETE_KNOWN_OPTION_KEYS = _METADATA_KNOWN_OPTION_KEYS | {"yes"}
_GET_KNOWN_OPTION_KEYS = {
    "pages",
    "max_pages",
    "source",
    "url",
    "token",
    "profile",
    "timeout",
    "format",
    "raw",
    "verbose",
}
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


def _parse_optional_positive_int(
    *,
    value: str | None,
    field_name: str,
    error_code: str,
) -> int | None:
    if value is None:
        return None
    return _parse_positive_int(
        value=value,
        default=1,
        field_name=field_name,
        error_code=error_code,
    )


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


def _document_page_cost(document: Any) -> int:
    page_count = getattr(document, "page_count", None)
    if isinstance(page_count, int) and page_count > 0:
        return page_count
    return 1


def _character_cost(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(_character_cost(item) for item in value)
    if isinstance(value, dict):
        return sum(_character_cost(item) for item in value.values())
    return 0


def _resolve_cursor_offset(
    updates: dict[str, str],
    *,
    command: str,
    signature: dict[str, Any],
    from_stdin: bool = False,
) -> int:
    token = updates.get("cursor")
    if token is None:
        return 0
    if "page" in updates:
        raise UsageValidationError(
            "cursor cannot be combined with explicit page.",
            error_code="CURSOR_WITH_PAGE",
        )
    if from_stdin:
        raise UsageValidationError(
            "cursor cannot be combined with from_stdin=true.",
            error_code="CURSOR_WITH_STDIN",
        )

    state = decode_cursor(token)
    if state.command != command or state.signature != signature:
        raise UsageValidationError(
            "Cursor does not match current query parameters.",
            error_code="CURSOR_MISMATCH",
        )
    return state.offset


def _paginate_with_cursor(
    items: list[dict[str, Any]],
    *,
    offset: int,
    page_size: int,
    command: str,
    signature: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    paged_items = items[offset : offset + page_size]
    next_offset = offset + len(paged_items)
    if next_offset < len(items):
        return paged_items, encode_cursor(command=command, signature=signature, offset=next_offset)
    return paged_items, None


def _cursor_search_signature(search: Any) -> dict[str, Any]:
    """Cursor signature payload excluding explicit page binding."""
    signature = cast(dict[str, Any], search.signature_payload())
    signature.pop("page", None)
    return signature


def _normalize_json_value(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_json_value(item) for key, item in value.items()}
    return value


def _serialize_document(document: Any) -> dict[str, Any]:
    raw_data = getattr(document, "_data", None)
    if isinstance(raw_data, dict):
        return {str(key): _normalize_json_value(item) for key, item in raw_data.items()}

    payload: dict[str, Any] = {}
    for field_name in (
        "id",
        "title",
        "content",
        "created",
        "modified",
        "added",
        "tags",
        "correspondent",
        "document_type",
        "storage_path",
        "archive_serial_number",
        "original_file_name",
        "archived_file_name",
        "page_count",
        "mime_type",
    ):
        payload[field_name] = _normalize_json_value(getattr(document, field_name, None))
    return payload


async def _fetch_document(client: Any, document_id: int) -> Any:
    if not getattr(client, "is_initialized", False) and hasattr(client, "initialize"):
        await client.initialize()
    return await client.documents(document_id)


def _fetch_document_sync(client: Any, document_id: int) -> Any:
    return asyncio.run(_fetch_document(client, document_id))


async def _fetch_document_metadata(client: Any, document_id: int) -> Any:
    if not getattr(client, "is_initialized", False) and hasattr(client, "initialize"):
        await client.initialize()
    return await client.documents.metadata(document_id)


def _fetch_document_metadata_sync(client: Any, document_id: int) -> Any:
    return asyncio.run(_fetch_document_metadata(client, document_id))


async def _fetch_document_suggestions(client: Any, document_id: int) -> Any:
    if not getattr(client, "is_initialized", False) and hasattr(client, "initialize"):
        await client.initialize()
    return await client.documents.suggestions(document_id)


def _fetch_document_suggestions_sync(client: Any, document_id: int) -> Any:
    return asyncio.run(_fetch_document_suggestions(client, document_id))


async def _fetch_next_asn(client: Any) -> int:
    if not getattr(client, "is_initialized", False) and hasattr(client, "initialize"):
        await client.initialize()
    value = await client.documents.get_next_asn()
    return int(value)


def _fetch_next_asn_sync(client: Any) -> int:
    return asyncio.run(_fetch_next_asn(client))


async def _send_document_email(
    client: Any,
    *,
    docs: int | list[int],
    addresses: str,
    subject: str,
    message: str,
    use_archive_version: bool,
) -> None:
    if not getattr(client, "is_initialized", False) and hasattr(client, "initialize"):
        await client.initialize()
    await client.documents.email(
        documents=docs,
        addresses=addresses,
        subject=subject,
        message=message,
        use_archive_version=use_archive_version,
    )


def _send_document_email_sync(
    client: Any,
    *,
    docs: int | list[int],
    addresses: str,
    subject: str,
    message: str,
    use_archive_version: bool,
) -> None:
    asyncio.run(
        _send_document_email(
            client,
            docs=docs,
            addresses=addresses,
            subject=subject,
            message=message,
            use_archive_version=use_archive_version,
        )
    )


async def _fetch_document_notes(client: Any, document_id: int) -> list[Any]:
    if not getattr(client, "is_initialized", False) and hasattr(client, "initialize"):
        await client.initialize()
    notes = await client.documents.notes(document_id)
    if not isinstance(notes, list):
        return []
    return notes


def _fetch_document_notes_sync(client: Any, document_id: int) -> list[Any]:
    return asyncio.run(_fetch_document_notes(client, document_id))


async def _add_document_note(client: Any, document_id: int, note: str) -> tuple[int, int]:
    if not getattr(client, "is_initialized", False) and hasattr(client, "initialize"):
        await client.initialize()
    draft = client.documents.notes.draft(document_id, note=note)
    result = await draft.save()
    if isinstance(result, tuple) and len(result) == 2:
        return int(result[0]), int(result[1])
    raise UsageValidationError(
        "Unexpected response while creating note.",
        details={"result": result},
        error_code="INVALID_NOTE_RESPONSE",
    )


def _add_document_note_sync(client: Any, document_id: int, note: str) -> tuple[int, int]:
    return asyncio.run(_add_document_note(client, document_id, note))


async def _delete_document_note(client: Any, document_id: int, note_id: int) -> bool:
    if not getattr(client, "is_initialized", False) and hasattr(client, "initialize"):
        await client.initialize()
    notes = await client.documents.notes(document_id)
    for note in notes:
        if getattr(note, "id", None) == note_id:
            deleted = await note.delete()
            return bool(deleted)
    return False


def _delete_document_note_sync(client: Any, document_id: int, note_id: int) -> bool:
    return asyncio.run(_delete_document_note(client, document_id, note_id))


def _mutation_error_details(exc: Exception) -> dict[str, Any]:
    return mutation_error_details(exc)


def _coerce_mutation_fields(raw_fields: dict[str, str]) -> dict[str, Any]:
    return coerce_mutation_fields(raw_fields)


def _read_document_bytes(path_value: str, filename_override: str | None) -> tuple[bytes, str]:
    path = Path(path_value).expanduser()
    if not path.exists() or not path.is_file():
        raise UsageValidationError(
            "document must point to an existing file.",
            details={"document": path_value},
            error_code="INVALID_DOCUMENT_FILE",
        )
    return path.read_bytes(), filename_override or path.name


async def _create_document(
    client: Any,
    *,
    document_bytes: bytes,
    filename: str,
    fields: dict[str, Any],
) -> int | str | tuple[int, int]:
    if not getattr(client, "is_initialized", False) and hasattr(client, "initialize"):
        await client.initialize()
    draft = client.documents.draft(document=document_bytes, filename=filename)
    apply_mutation_fields(draft, fields, error_code="INVALID_CREATE_FIELDS")
    result = await draft.save()
    return cast(int | str | tuple[int, int], result)


def _create_document_sync(
    client: Any,
    *,
    document_bytes: bytes,
    filename: str,
    fields: dict[str, Any],
) -> int | str | tuple[int, int]:
    return asyncio.run(
        _create_document(
            client,
            document_bytes=document_bytes,
            filename=filename,
            fields=fields,
        )
    )


async def _update_document(document: Any, *, only_changed: bool) -> bool:
    return bool(await document.update(only_changed=only_changed))


def _update_document_sync(document: Any, *, only_changed: bool) -> bool:
    return asyncio.run(_update_document(document, only_changed=only_changed))


async def _delete_document(document: Any) -> bool:
    return bool(await document.delete())


def _delete_document_sync(document: Any) -> bool:
    return asyncio.run(_delete_document(document))


async def _fetch_binary_document(
    client: Any,
    *,
    action: str,
    document_id: int,
    original: bool,
) -> Any:
    if not getattr(client, "is_initialized", False) and hasattr(client, "initialize"):
        await client.initialize()
    helper = getattr(client.documents, action, None)
    if helper is None:
        raise UsageValidationError(
            f"documents.{action} endpoint is not available.",
            details={"action": action},
            error_code="UNSUPPORTED_OPERATION",
        )
    return await helper(document_id, original=original)


def _fetch_binary_document_sync(
    client: Any,
    *,
    action: str,
    document_id: int,
    original: bool,
) -> Any:
    return asyncio.run(
        _fetch_binary_document(
            client,
            action=action,
            document_id=document_id,
            original=original,
        )
    )


def _available_retrieval_sources(document: Any) -> set[str]:
    sources: set[str] = {"ocr"}
    archive_name = getattr(document, "archived_file_name", None)
    if isinstance(archive_name, str) and archive_name.strip():
        sources.add("archive")
    original_name = getattr(document, "original_file_name", None)
    if isinstance(original_name, str) and original_name.strip():
        sources.add("original")
    return sources


def _serialize_document_list(documents: list[Any]) -> list[dict[str, Any]]:
    return [_serialize_document(document) for document in documents]


def _extract_binary_payload(downloaded: Any) -> tuple[bytes, str | None, str | None]:
    content = getattr(downloaded, "content", None)
    if not isinstance(content, bytes):
        raise UsageValidationError(
            "Binary endpoint did not return byte content.",
            error_code="INVALID_BINARY_RESPONSE",
        )
    content_type = getattr(downloaded, "content_type", None)
    filename = getattr(downloaded, "disposition_filename", None)
    normalized_type = content_type if isinstance(content_type, str) else None
    normalized_name = filename if isinstance(filename, str) else None
    return content, normalized_type, normalized_name


def _parse_binary_command_tokens(
    *,
    raw_tokens: list[str],
    command_label: str,
) -> dict[str, str]:
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=_BINARY_KNOWN_OPTION_KEYS,
        boolean_option_keys={"raw", "verbose", "original"},
        strict_boolean_values=True,
    )
    if parsed.positional or parsed.passthrough_tokens:
        raise UsageValidationError(
            (
                f"docs {command_label} accepts only key=value or --option "
                "arguments after <document-id>."
            ),
            details={"positional": parsed.positional, "tokens": parsed.passthrough_tokens},
            error_code="UNEXPECTED_ARGS",
        )
    return parsed.updates


def _run_binary_document_command(
    *,
    command_name: str,
    document_id: int,
    updates: dict[str, str],
) -> None:
    if document_id <= 0:
        raise UsageValidationError(
            "document-id must be a positive integer.",
            details={"document_id": document_id},
            error_code="INVALID_DOCUMENT_ID",
        )
    original = parse_bool(updates["original"]) if "original" in updates else False
    output_value = updates.get("output")

    global_options = GlobalOptions.from_updates(updates)
    validate_raw_allowed(raw=global_options.raw, command_path=f"docs {command_name}")
    client, runtime_context = create_client(global_options)
    downloaded = _fetch_binary_document_sync(
        client,
        action=command_name,
        document_id=document_id,
        original=original,
    )
    content, content_type, disposition_filename = _extract_binary_payload(downloaded)

    output_path: Path | None = None
    if output_value is not None:
        output_path = Path(output_value).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)

    if global_options.raw:
        if output_path is None:
            sys.stdout.buffer.write(content)
        return

    data: dict[str, Any] = {
        "size_bytes": len(content),
        "content_type": content_type,
        "filename": disposition_filename,
        "original": original,
    }
    if output_path is None:
        data["content_base64"] = base64.b64encode(content).decode("ascii")
    else:
        data["output"] = str(output_path)

    emit_success(
        resource="docs",
        action=command_name,
        data=data,
        meta={
            "id": document_id,
            "profile": runtime_context.profile,
        },
    )


def _parse_command_tokens(
    *,
    raw_tokens: list[str],
    known_option_keys: set[str],
    command_label: str,
    boolean_keys: set[str] | None = None,
    passthrough_filter_mode: bool = False,
) -> tuple[dict[str, str], dict[str, str]]:
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=known_option_keys,
        boolean_option_keys=boolean_keys or {"raw", "verbose"},
        strict_boolean_values=True,
        passthrough_filter_mode=passthrough_filter_mode,
    )
    if parsed.positional or parsed.passthrough_tokens:
        raise UsageValidationError(
            f"docs {command_label} accepts only key=value or --option arguments.",
            details={"positional": parsed.positional, "tokens": parsed.passthrough_tokens},
            error_code="UNEXPECTED_ARGS",
        )
    return parsed.updates, parsed.passthrough_filters


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
    "download",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_download(
    ctx: typer.Context,
    document_id: Annotated[
        int,
        typer.Argument(help="Document ID."),
    ],
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Binary options."),
    ] = None,
) -> None:
    """Download archived/original document bytes."""
    raw_tokens = [*(tokens or []), *ctx.args]
    updates = _parse_binary_command_tokens(raw_tokens=raw_tokens, command_label="download")
    _run_binary_document_command(command_name="download", document_id=document_id, updates=updates)


@app.command(
    "preview",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_preview(
    ctx: typer.Context,
    document_id: Annotated[
        int,
        typer.Argument(help="Document ID."),
    ],
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Binary options."),
    ] = None,
) -> None:
    """Fetch preview bytes for a document."""
    raw_tokens = [*(tokens or []), *ctx.args]
    updates = _parse_binary_command_tokens(raw_tokens=raw_tokens, command_label="preview")
    _run_binary_document_command(command_name="preview", document_id=document_id, updates=updates)


@app.command(
    "thumbnail",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_thumbnail(
    ctx: typer.Context,
    document_id: Annotated[
        int,
        typer.Argument(help="Document ID."),
    ],
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Binary options."),
    ] = None,
) -> None:
    """Fetch thumbnail bytes for a document."""
    raw_tokens = [*(tokens or []), *ctx.args]
    updates = _parse_binary_command_tokens(raw_tokens=raw_tokens, command_label="thumbnail")
    _run_binary_document_command(command_name="thumbnail", document_id=document_id, updates=updates)


@app.command(
    "metadata",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_metadata(
    ctx: typer.Context,
    document_id: Annotated[
        int,
        typer.Argument(help="Document ID."),
    ],
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Global options."),
    ] = None,
) -> None:
    """Fetch metadata for a document."""
    updates, _ = _parse_command_tokens(
        raw_tokens=[*(tokens or []), *ctx.args],
        known_option_keys=_METADATA_KNOWN_OPTION_KEYS,
        command_label="metadata",
    )
    if document_id <= 0:
        raise UsageValidationError(
            "document-id must be a positive integer.",
            details={"document_id": document_id},
            error_code="INVALID_DOCUMENT_ID",
        )

    global_options = GlobalOptions.from_updates(updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs metadata")
    client, runtime_context = create_client(global_options)
    metadata = _fetch_document_metadata_sync(client, document_id)

    emit_success(
        resource="docs",
        action="metadata",
        data={"metadata": _serialize_document(metadata)},
        meta={"id": document_id, "profile": runtime_context.profile},
    )


@app.command(
    "suggestions",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_suggestions(
    ctx: typer.Context,
    document_id: Annotated[
        int,
        typer.Argument(help="Document ID."),
    ],
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Global options."),
    ] = None,
) -> None:
    """Fetch suggestions for a document."""
    updates, _ = _parse_command_tokens(
        raw_tokens=[*(tokens or []), *ctx.args],
        known_option_keys=_SUGGESTIONS_KNOWN_OPTION_KEYS,
        command_label="suggestions",
    )
    if document_id <= 0:
        raise UsageValidationError(
            "document-id must be a positive integer.",
            details={"document_id": document_id},
            error_code="INVALID_DOCUMENT_ID",
        )

    global_options = GlobalOptions.from_updates(updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs suggestions")
    client, runtime_context = create_client(global_options)
    suggestions = _fetch_document_suggestions_sync(client, document_id)

    emit_success(
        resource="docs",
        action="suggestions",
        data={"suggestions": _serialize_document(suggestions)},
        meta={"id": document_id, "profile": runtime_context.profile},
    )


@app.command(
    "next-asn",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_next_asn(
    ctx: typer.Context,
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Global options."),
    ] = None,
) -> None:
    """Fetch next archive serial number."""
    updates, _ = _parse_command_tokens(
        raw_tokens=[*(tokens or []), *ctx.args],
        known_option_keys=_NEXT_ASN_KNOWN_OPTION_KEYS,
        command_label="next-asn",
    )

    global_options = GlobalOptions.from_updates(updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs next-asn")
    client, runtime_context = create_client(global_options)
    next_asn = _fetch_next_asn_sync(client)

    emit_success(
        resource="docs",
        action="next-asn",
        data={"next_asn": next_asn},
        meta={"profile": runtime_context.profile},
    )


@app.command(
    "email",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_email(
    ctx: typer.Context,
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Email options."),
    ] = None,
) -> None:
    """Send selected documents via email."""
    updates, _ = _parse_command_tokens(
        raw_tokens=[*(tokens or []), *ctx.args],
        known_option_keys=_EMAIL_KNOWN_OPTION_KEYS,
        command_label="email",
        boolean_keys={"raw", "verbose", "use_archive_version"},
    )

    docs_value = updates.get("docs")
    if docs_value is None:
        raise UsageValidationError(
            "docs email requires docs=<id-list>.",
            error_code="MISSING_EMAIL_DOCS",
        )
    doc_ids = _parse_ids(docs_value)
    if not doc_ids:
        raise UsageValidationError(
            "docs email requires at least one document id.",
            error_code="MISSING_EMAIL_DOCS",
        )

    addresses = updates.get("to")
    if addresses is None or not addresses.strip():
        raise UsageValidationError(
            "docs email requires to=<address-list>.",
            error_code="MISSING_EMAIL_TO",
        )
    subject = updates.get("subject")
    if subject is None or not subject.strip():
        raise UsageValidationError(
            "docs email requires subject=<text>.",
            error_code="MISSING_EMAIL_SUBJECT",
        )
    message = updates.get("message")
    if message is None:
        raise UsageValidationError(
            "docs email requires message=<text>.",
            error_code="MISSING_EMAIL_MESSAGE",
        )
    use_archive_version = (
        parse_bool(updates["use_archive_version"]) if "use_archive_version" in updates else True
    )

    global_options = GlobalOptions.from_updates(updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs email")
    client, runtime_context = create_client(global_options)
    _send_document_email_sync(
        client,
        docs=doc_ids if len(doc_ids) > 1 else doc_ids[0],
        addresses=addresses,
        subject=subject,
        message=message,
        use_archive_version=use_archive_version,
    )

    emit_success(
        resource="docs",
        action="email",
        data={
            "sent": True,
            "docs": doc_ids,
            "to": addresses,
            "use_archive_version": use_archive_version,
        },
        meta={"profile": runtime_context.profile},
    )


@notes_app.command(
    "list",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_notes_list(
    ctx: typer.Context,
    document_id: Annotated[
        int,
        typer.Argument(help="Document ID."),
    ],
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Global options."),
    ] = None,
) -> None:
    """List notes for a document."""
    updates, _ = _parse_command_tokens(
        raw_tokens=[*(tokens or []), *ctx.args],
        known_option_keys=_NOTES_LIST_KNOWN_OPTION_KEYS,
        command_label="notes list",
    )
    if document_id <= 0:
        raise UsageValidationError(
            "document-id must be a positive integer.",
            details={"document_id": document_id},
            error_code="INVALID_DOCUMENT_ID",
        )

    global_options = GlobalOptions.from_updates(updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs notes list")
    client, runtime_context = create_client(global_options)
    notes = _fetch_document_notes_sync(client, document_id)
    rows = _serialize_document_list(notes)

    emit_success(
        resource="docs",
        action="notes-list",
        data={"items": rows},
        meta={"document_id": document_id, "count": len(rows), "profile": runtime_context.profile},
    )


@notes_app.command(
    "add",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_notes_add(
    ctx: typer.Context,
    document_id: Annotated[
        int,
        typer.Argument(help="Document ID."),
    ],
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Options including note=<text>."),
    ] = None,
) -> None:
    """Add a note to a document."""
    updates, _ = _parse_command_tokens(
        raw_tokens=[*(tokens or []), *ctx.args],
        known_option_keys=_NOTES_ADD_KNOWN_OPTION_KEYS,
        command_label="notes add",
    )
    if document_id <= 0:
        raise UsageValidationError(
            "document-id must be a positive integer.",
            details={"document_id": document_id},
            error_code="INVALID_DOCUMENT_ID",
        )
    note_text = updates.get("note")
    if note_text is None or not note_text.strip():
        raise UsageValidationError(
            "docs notes add requires note=<text>.",
            error_code="MISSING_NOTE_TEXT",
        )

    global_options = GlobalOptions.from_updates(updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs notes add")
    client, runtime_context = create_client(global_options)
    note_id, linked_document_id = _add_document_note_sync(client, document_id, note_text)

    emit_success(
        resource="docs",
        action="notes-add",
        data={"note_id": note_id, "document_id": linked_document_id},
        meta={"profile": runtime_context.profile},
    )


@notes_app.command(
    "delete",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_notes_delete(
    ctx: typer.Context,
    document_id: Annotated[
        int,
        typer.Argument(help="Document ID."),
    ],
    note_id: Annotated[
        int,
        typer.Argument(help="Note ID."),
    ],
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Options including yes=true."),
    ] = None,
) -> None:
    """Delete a note from a document."""
    updates, _ = _parse_command_tokens(
        raw_tokens=[*(tokens or []), *ctx.args],
        known_option_keys=_NOTES_DELETE_KNOWN_OPTION_KEYS,
        command_label="notes delete",
        boolean_keys={"raw", "verbose", "yes"},
    )
    if document_id <= 0:
        raise UsageValidationError(
            "document-id must be a positive integer.",
            details={"document_id": document_id},
            error_code="INVALID_DOCUMENT_ID",
        )
    if note_id <= 0:
        raise UsageValidationError(
            "note-id must be a positive integer.",
            details={"note_id": note_id},
            error_code="INVALID_NOTE_ID",
        )
    require_confirmation(updates, command_path="docs notes delete")

    global_options = GlobalOptions.from_updates(updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs notes delete")
    client, runtime_context = create_client(global_options)
    deleted = _delete_document_note_sync(client, document_id, note_id)
    if not deleted:
        raise UsageValidationError(
            "Note not found for document.",
            details={"document_id": document_id, "note_id": note_id},
            error_code="NOTE_NOT_FOUND",
        )

    emit_success(
        resource="docs",
        action="notes-delete",
        data={"deleted": True, "document_id": document_id, "note_id": note_id},
        meta={"profile": runtime_context.profile},
    )


@app.command(
    "create",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_create(
    ctx: typer.Context,
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Create fields. Requires document=<path>."),
    ] = None,
) -> None:
    """Create a new document from a local file and metadata fields."""
    updates, passthrough_fields = _parse_command_tokens(
        raw_tokens=[*(tokens or []), *ctx.args],
        known_option_keys=_CREATE_KNOWN_OPTION_KEYS,
        command_label="create",
        passthrough_filter_mode=True,
    )

    document_value = updates.get("document")
    if document_value is None or not document_value.strip():
        raise UsageValidationError(
            "docs create requires document=<path>.",
            error_code="MISSING_DOCUMENT_FILE",
        )
    document_bytes, filename = _read_document_bytes(document_value, updates.get("filename"))
    fields = _coerce_mutation_fields(passthrough_fields)

    global_options = GlobalOptions.from_updates(updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs create")
    client, runtime_context = create_client(global_options)
    try:
        result = _create_document_sync(
            client,
            document_bytes=document_bytes,
            filename=filename,
            fields=fields,
        )
    except Exception as exc:  # pragma: no cover - defensive mapping
        raise PcliError(
            "Document create failed.",
            details=_mutation_error_details(exc),
            error_code="DOC_CREATE_FAILED",
        ) from exc

    emit_success(
        resource="docs",
        action="create",
        data={"result": result, "filename": filename},
        meta={"profile": runtime_context.profile},
    )


@app.command(
    "update",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_update(
    ctx: typer.Context,
    document_id: Annotated[
        int,
        typer.Argument(help="Document ID."),
    ],
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Update fields."),
    ] = None,
) -> None:
    """Update fields on an existing document."""
    updates, passthrough_fields = _parse_command_tokens(
        raw_tokens=[*(tokens or []), *ctx.args],
        known_option_keys=_UPDATE_KNOWN_OPTION_KEYS,
        command_label="update",
        passthrough_filter_mode=True,
    )
    if document_id <= 0:
        raise UsageValidationError(
            "document-id must be a positive integer.",
            details={"document_id": document_id},
            error_code="INVALID_DOCUMENT_ID",
        )
    if not passthrough_fields:
        raise UsageValidationError(
            "docs update requires at least one field=value assignment.",
            error_code="MISSING_UPDATE_FIELDS",
        )
    only_changed = resolve_only_changed(updates)
    fields = _coerce_mutation_fields(passthrough_fields)

    global_options = GlobalOptions.from_updates(updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs update")
    client, runtime_context = create_client(global_options)
    document = _fetch_document_sync(client, document_id)
    apply_mutation_fields(document, fields, error_code="INVALID_UPDATE_FIELDS")
    try:
        updated = _update_document_sync(document, only_changed=only_changed)
    except Exception as exc:  # pragma: no cover - defensive mapping
        raise PcliError(
            "Document update failed.",
            details=_mutation_error_details(exc),
            error_code="DOC_UPDATE_FAILED",
        ) from exc

    emit_success(
        resource="docs",
        action="update",
        data={
            "updated": updated,
            "document_id": document_id,
            "only_changed": only_changed,
        },
        meta={"profile": runtime_context.profile},
    )


@app.command(
    "delete",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_delete(
    ctx: typer.Context,
    document_id: Annotated[
        int,
        typer.Argument(help="Document ID."),
    ],
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Options including yes=true."),
    ] = None,
) -> None:
    """Delete a document with explicit confirmation."""
    updates, _ = _parse_command_tokens(
        raw_tokens=[*(tokens or []), *ctx.args],
        known_option_keys=_DELETE_KNOWN_OPTION_KEYS,
        command_label="delete",
        boolean_keys={"raw", "verbose", "yes"},
    )
    if document_id <= 0:
        raise UsageValidationError(
            "document-id must be a positive integer.",
            details={"document_id": document_id},
            error_code="INVALID_DOCUMENT_ID",
        )
    require_confirmation(updates, command_path="docs delete")

    global_options = GlobalOptions.from_updates(updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs delete")
    client, runtime_context = create_client(global_options)
    document = _fetch_document_sync(client, document_id)
    try:
        deleted = _delete_document_sync(document)
    except Exception as exc:  # pragma: no cover - defensive mapping
        raise PcliError(
            "Document delete failed.",
            details=_mutation_error_details(exc),
            error_code="DOC_DELETE_FAILED",
        ) from exc

    emit_success(
        resource="docs",
        action="delete",
        data={"deleted": deleted, "document_id": document_id},
        meta={"profile": runtime_context.profile},
    )


@app.command(
    "get",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_get(
    ctx: typer.Context,
    document_id: Annotated[
        int,
        typer.Argument(help="Document ID."),
    ],
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Global options."),
    ] = None,
) -> None:
    """Fetch one document with default OCR text retrieval."""
    raw_tokens = [*(tokens or []), *ctx.args]
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=_GET_KNOWN_OPTION_KEYS,
        boolean_option_keys={"raw", "verbose"},
        strict_boolean_values=True,
    )
    if parsed.positional or parsed.passthrough_tokens:
        raise UsageValidationError(
            "docs get accepts only key=value or --option arguments after <document-id>.",
            details={"positional": parsed.positional, "tokens": parsed.passthrough_tokens},
            error_code="UNEXPECTED_ARGS",
        )
    if document_id <= 0:
        raise UsageValidationError(
            "document-id must be a positive integer.",
            details={"document_id": document_id},
            error_code="INVALID_DOCUMENT_ID",
        )
    selected_pages = normalize_page_selection(
        pages=parsed.updates.get("pages"),
        max_pages=parsed.updates.get("max_pages"),
    )
    requested_source = parse_retrieval_source(parsed.updates.get("source"))
    if selected_pages is not None and requested_source == "ocr":
        raise UsageValidationError(
            "source=ocr cannot be combined with pages=...",
            details={"source": "ocr", "pages": selected_pages},
            error_code="INVALID_SOURCE_WITH_PAGES",
        )

    global_options = GlobalOptions.from_updates(parsed.updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs get")
    client, runtime_context = create_client(global_options)
    document = _fetch_document_sync(client, document_id)

    source_candidates = resolve_source_candidates(
        source=requested_source,
        has_page_filter=selected_pages is not None,
    )
    available_sources = _available_retrieval_sources(document)
    resolved_source: str | None = None
    for candidate in source_candidates:
        if candidate in available_sources:
            resolved_source = candidate
            break
    if resolved_source is None:
        raise UsageValidationError(
            "No usable retrieval source is available for this document.",
            details={
                "requested_source": requested_source,
                "candidates": source_candidates,
                "available_sources": sorted(available_sources),
            },
            error_code="SOURCE_UNAVAILABLE",
        )
    if resolved_source != "ocr":
        raise UsageValidationError(
            "File-based extraction is not available yet for this source.",
            details={
                "source": resolved_source,
                "pages": selected_pages,
                "candidates": source_candidates,
            },
            error_code=(
                "PAGE_EXTRACTION_UNAVAILABLE"
                if selected_pages is not None
                else "SOURCE_NOT_SUPPORTED"
            ),
        )

    text = getattr(document, "content", None)
    content_text = text if isinstance(text, str) else ""
    page_count = getattr(document, "page_count", None)

    emit_success(
        resource="docs",
        action="get",
        data={
            "document": _serialize_document(document),
            "text": content_text,
            "pages": selected_pages,
            "source": resolved_source,
            "truncated": False,
        },
        meta={
            "id": document_id,
            "page_count": page_count if isinstance(page_count, int) else None,
            "profile": runtime_context.profile,
        },
    )


@app.command(
    "list",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_list(
    ctx: typer.Context,
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Query/filter options."),
    ] = None,
) -> None:
    """List documents with passthrough query/filter pagination."""
    raw_tokens = [*(tokens or []), *ctx.args]
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=_LIST_KNOWN_OPTION_KEYS,
        passthrough_filter_mode=True,
        boolean_option_keys={"raw", "verbose"},
        strict_boolean_values=True,
    )
    if parsed.positional or parsed.passthrough_tokens:
        raise UsageValidationError(
            "docs list accepts only key=value or --option arguments.",
            details={"positional": parsed.positional, "tokens": parsed.passthrough_tokens},
            error_code="UNEXPECTED_ARGS",
        )

    search = canonicalize_document_search(
        query=parsed.updates.get("query"),
        custom_field_query=parsed.updates.get("custom_field_query"),
        page=parsed.updates.get("page"),
        page_size=parsed.updates.get("page_size"),
        max_docs=parsed.updates.get("page_size"),
        sort=parsed.updates.get("sort"),
        filters=parsed.passthrough_filters,
    )
    search = replace(search, max_docs=search.page_size)

    global_options = GlobalOptions.from_updates(parsed.updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs list")
    client, runtime_context = create_client(global_options)
    adapter = DocumentSearchAdapter()
    documents = adapter.collect_documents_sync(client, search)
    rows = _serialize_document_list(documents)

    emit_success(
        resource="docs",
        action="list",
        data={"items": rows},
        meta={
            "count": len(rows),
            "page": search.page,
            "page_size": search.page_size,
            "query": search.query,
            "custom_field_query": search.custom_field_query,
            "sort": search.sort,
            "profile": runtime_context.profile,
        },
    )


@app.command(
    "search",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_search(
    ctx: typer.Context,
    query: Annotated[
        str,
        typer.Argument(help="Search query string."),
    ],
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Query/filter options."),
    ] = None,
) -> None:
    """Search documents by positional query with passthrough filters."""
    raw_tokens = [*(tokens or []), *ctx.args]
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=_SEARCH_KNOWN_OPTION_KEYS,
        passthrough_filter_mode=True,
        boolean_option_keys={"raw", "verbose"},
        strict_boolean_values=True,
    )
    if parsed.positional or parsed.passthrough_tokens:
        raise UsageValidationError(
            "docs search accepts only <query> then key=value or --option arguments.",
            details={"positional": parsed.positional, "tokens": parsed.passthrough_tokens},
            error_code="UNEXPECTED_ARGS",
        )
    if not query.strip():
        raise UsageValidationError(
            "docs search requires a non-empty <query> argument.",
            error_code="MISSING_QUERY",
        )

    search = canonicalize_document_search(
        query=query,
        custom_field_query=parsed.updates.get("custom_field_query"),
        page=parsed.updates.get("page"),
        page_size=parsed.updates.get("page_size"),
        max_docs=parsed.updates.get("page_size"),
        sort=parsed.updates.get("sort"),
        filters=parsed.passthrough_filters,
    )
    search = replace(search, max_docs=search.page_size)

    global_options = GlobalOptions.from_updates(parsed.updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs search")
    client, runtime_context = create_client(global_options)
    adapter = DocumentSearchAdapter()
    documents = adapter.collect_documents_sync(client, search)
    rows = _serialize_document_list(documents)

    emit_success(
        resource="docs",
        action="search",
        data={"items": rows},
        meta={
            "count": len(rows),
            "page": search.page,
            "page_size": search.page_size,
            "query": search.query,
            "custom_field_query": search.custom_field_query,
            "sort": search.sort,
            "profile": runtime_context.profile,
        },
    )


@app.command(
    "more-like",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def docs_more_like(
    ctx: typer.Context,
    document_id: Annotated[
        int,
        typer.Argument(help="Reference document ID."),
    ],
    tokens: Annotated[
        list[str] | None,
        typer.Argument(help="Pagination/filter options."),
    ] = None,
) -> None:
    """Find similar documents for a given document ID."""
    raw_tokens = [*(tokens or []), *ctx.args]
    parsed = parse_tokens(
        raw_tokens,
        known_option_keys=_MORE_LIKE_KNOWN_OPTION_KEYS,
        passthrough_filter_mode=True,
        boolean_option_keys={"raw", "verbose"},
        strict_boolean_values=True,
    )
    if parsed.positional or parsed.passthrough_tokens:
        raise UsageValidationError(
            "docs more-like accepts only key=value or --option arguments after <document-id>.",
            details={"positional": parsed.positional, "tokens": parsed.passthrough_tokens},
            error_code="UNEXPECTED_ARGS",
        )
    if document_id <= 0:
        raise UsageValidationError(
            "document-id must be a positive integer.",
            details={"document_id": document_id},
            error_code="INVALID_DOCUMENT_ID",
        )

    filters: dict[str, Any] = dict(parsed.passthrough_filters)
    filters["more_like_id"] = document_id
    search = canonicalize_document_search(
        page=parsed.updates.get("page"),
        page_size=parsed.updates.get("page_size"),
        max_docs=parsed.updates.get("page_size"),
        sort=parsed.updates.get("sort"),
        filters=filters,
    )
    search = replace(search, max_docs=search.page_size)

    global_options = GlobalOptions.from_updates(parsed.updates)
    validate_raw_allowed(raw=global_options.raw, command_path="docs more-like")
    client, runtime_context = create_client(global_options)
    adapter = DocumentSearchAdapter()
    documents = adapter.collect_documents_sync(client, search)
    rows = _serialize_document_list(documents)

    emit_success(
        resource="docs",
        action="more-like",
        data={"items": rows},
        meta={
            "count": len(rows),
            "document_id": document_id,
            "page": search.page,
            "page_size": search.page_size,
            "sort": search.sort,
            "profile": runtime_context.profile,
        },
    )


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
    max_pages_total = _parse_optional_positive_int(
        value=parsed.updates.get("max_pages_total"),
        field_name="max_pages_total",
        error_code="INVALID_MAX_PAGES_TOTAL",
    )
    max_chars_total = _parse_optional_positive_int(
        value=parsed.updates.get("max_chars_total"),
        field_name="max_chars_total",
        error_code="INVALID_MAX_CHARS_TOTAL",
    )
    stop_after_matches = _parse_optional_positive_int(
        value=parsed.updates.get("stop_after_matches"),
        field_name="stop_after_matches",
        error_code="INVALID_STOP_AFTER_MATCHES",
    )
    explicit_page = "page" in parsed.updates
    cursor_signature = {
        "search": _cursor_search_signature(search),
        "fields": fields,
        "ids_only": ids_only,
        "max_pages_total": max_pages_total,
        "max_chars_total": max_chars_total,
        "stop_after_matches": stop_after_matches,
    }
    cursor_offset = _resolve_cursor_offset(
        parsed.updates,
        command="docs.find",
        signature=cursor_signature,
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

    rows: list[dict[str, Any]] = []
    pages_used = 0
    chars_used = 0
    matches = 0
    for document in sorted_documents:
        page_cost = _document_page_cost(document)
        if max_pages_total is not None and pages_used + page_cost > max_pages_total:
            break

        row = (
            {"id": getattr(document, "id", None)}
            if ids_only
            else _project_find_document(document, fields)
        )
        row_chars = _character_cost(row)
        if max_chars_total is not None and chars_used + row_chars > max_chars_total:
            break
        if stop_after_matches is not None and matches + 1 > stop_after_matches:
            break

        rows.append(row)
        matches += 1
        pages_used += page_cost
        chars_used += row_chars

    paged_rows, next_cursor = _paginate_with_cursor(
        rows,
        offset=cursor_offset,
        page_size=search.page_size,
        command="docs.find",
        signature=cursor_signature,
    )
    if explicit_page:
        next_cursor = None

    if global_options.format_mode is FormatMode.NDJSON:
        for row in paged_rows:
            typer.echo(ndjson_item(row))
        typer.echo(ndjson_summary(next_cursor=next_cursor))
        return

    emit_success(
        resource="docs",
        action="find",
        data={"items": paged_rows},
        meta={
            "count": len(paged_rows),
            "total_matches": len(rows),
            "page": search.page,
            "page_size": search.page_size,
            "max_docs": search.max_docs,
            "query": search.query,
            "sort": search.sort,
            "ids_only": ids_only,
            "pages_used": pages_used,
            "chars_used": chars_used,
            "matches": matches,
            "next_cursor": next_cursor,
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
    max_pages_total = _parse_optional_positive_int(
        value=parsed.updates.get("max_pages_total"),
        field_name="max_pages_total",
        error_code="INVALID_MAX_PAGES_TOTAL",
    )
    max_chars_total = _parse_optional_positive_int(
        value=parsed.updates.get("max_chars_total"),
        field_name="max_chars_total",
        error_code="INVALID_MAX_CHARS_TOTAL",
    )
    stop_after_matches = _parse_optional_positive_int(
        value=parsed.updates.get("stop_after_matches"),
        field_name="stop_after_matches",
        error_code="INVALID_STOP_AFTER_MATCHES",
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
    explicit_page = "page" in parsed.updates
    cursor_signature = {
        "search": _cursor_search_signature(search),
        "fields": fields,
        "per_doc_max_chars": per_doc_max_chars,
        "max_pages_total": max_pages_total,
        "max_chars_total": max_chars_total,
        "stop_after_matches": stop_after_matches,
    }
    cursor_offset = _resolve_cursor_offset(
        parsed.updates,
        command="docs.peek",
        signature=cursor_signature,
        from_stdin=from_stdin,
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
                "pages_used": 0,
                "chars_used": 0,
                "matches": 0,
                "from_stdin": True,
                "query": search.query,
                "next_cursor": None,
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

    rows: list[dict[str, Any]] = []
    pages_used = 0
    chars_used = 0
    matches = 0
    for document in documents:
        page_cost = _document_page_cost(document)
        if max_pages_total is not None and pages_used + page_cost > max_pages_total:
            break

        row = _project_peek_document(document, fields, max_chars=per_doc_max_chars)
        row_chars = int(row.get("chars", 0))
        if max_chars_total is not None and chars_used + row_chars > max_chars_total:
            break
        if stop_after_matches is not None and matches + 1 > stop_after_matches:
            break

        rows.append(row)
        pages_used += page_cost
        chars_used += row_chars
        matches += 1

    paged_rows, next_cursor = _paginate_with_cursor(
        rows,
        offset=cursor_offset,
        page_size=search.page_size,
        command="docs.peek",
        signature=cursor_signature,
    )
    if explicit_page:
        next_cursor = None

    emit_success(
        resource="docs",
        action="peek",
        data={"items": paged_rows},
        meta={
            "count": len(paged_rows),
            "total_matches": len(rows),
            "max_docs": search.max_docs,
            "per_doc_max_chars": per_doc_max_chars,
            "pages_used": pages_used,
            "chars_used": chars_used,
            "matches": matches,
            "from_stdin": from_stdin,
            "query": search.query,
            "next_cursor": next_cursor,
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
    max_pages_total = _parse_optional_positive_int(
        value=parsed.updates.get("max_pages_total"),
        field_name="max_pages_total",
        error_code="INVALID_MAX_PAGES_TOTAL",
    )
    max_chars_total = _parse_optional_positive_int(
        value=parsed.updates.get("max_chars_total"),
        field_name="max_chars_total",
        error_code="INVALID_MAX_CHARS_TOTAL",
    )
    stop_after_matches = _parse_optional_positive_int(
        value=parsed.updates.get("stop_after_matches"),
        field_name="stop_after_matches",
        error_code="INVALID_STOP_AFTER_MATCHES",
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
    explicit_page = "page" in parsed.updates
    cursor_signature = {
        "search": _cursor_search_signature(search),
        "context_before": context_before,
        "context_after": context_after,
        "max_hits_per_doc": max_hits_per_doc,
        "max_pages_total": max_pages_total,
        "max_chars_total": max_chars_total,
        "stop_after_matches": stop_after_matches,
    }
    cursor_offset = _resolve_cursor_offset(
        parsed.updates,
        command="docs.skim",
        signature=cursor_signature,
        from_stdin=from_stdin,
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
                "pages_used": 0,
                "chars_used": 0,
                "matches": 0,
                "query": search.query,
                "from_stdin": True,
                "next_cursor": None,
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
    docs_scanned = 0
    pages_used = 0
    chars_used = 0
    stop_scan = False
    for document in documents:
        page_cost = _document_page_cost(document)
        if max_pages_total is not None and pages_used + page_cost > max_pages_total:
            break
        pages_used += page_cost
        docs_scanned += 1

        doc_hits = _extract_skim_hits(
            document,
            query=normalized_query,
            context_before=context_before,
            context_after=context_after,
            max_hits_per_doc=max_hits_per_doc,
        )
        emitted_for_doc = 0
        for hit in doc_hits:
            hit_chars = len(str(hit.get("text", "")))
            if max_chars_total is not None and chars_used + hit_chars > max_chars_total:
                stop_scan = True
                break
            if stop_after_matches is not None and len(items) + 1 > stop_after_matches:
                stop_scan = True
                break
            items.append(hit)
            chars_used += hit_chars
            emitted_for_doc += 1
        if emitted_for_doc > 0:
            docs_with_hits += 1
        if stop_scan:
            break

    paged_items, next_cursor = _paginate_with_cursor(
        items,
        offset=cursor_offset,
        page_size=search.page_size,
        command="docs.skim",
        signature=cursor_signature,
    )
    if explicit_page:
        next_cursor = None

    emit_success(
        resource="docs",
        action="skim",
        data={"items": paged_items},
        meta={
            "count": len(paged_items),
            "total_matches": len(items),
            "docs_scanned": docs_scanned,
            "docs_with_hits": docs_with_hits,
            "max_docs": search.max_docs,
            "max_hits_per_doc": max_hits_per_doc,
            "context_before": context_before,
            "context_after": context_after,
            "pages_used": pages_used,
            "chars_used": chars_used,
            "matches": len(items),
            "query": search.query,
            "from_stdin": from_stdin,
            "next_cursor": next_cursor,
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
