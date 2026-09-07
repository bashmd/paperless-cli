"""Size hints describe the whole raw OCR document, not the normalized excerpt."""

from types import SimpleNamespace

import pytest

from pcli.cli.docs import (
    _DEFAULT_FIND_FIELDS,
    _DEFAULT_PEEK_FIELDS,
    _extract_skim_hits,
    _project_find_document,
    _project_peek_document,
    _rg_find_line,
    _rg_peek_line,
)


@pytest.mark.parametrize("content,total", [("a\t\t\nb \u00fc", 7), ("", 0), (None, None)])
def test_sizes_preserve_raw_length_and_unknown(content: str | None, total: int | None) -> None:
    doc = SimpleNamespace(id=1, content=content, page_count=3)
    find = _project_find_document(doc, _DEFAULT_FIND_FIELDS)
    peek = _project_peek_document(doc, _DEFAULT_PEEK_FIELDS, max_chars=2)
    for row in [find, peek]:
        assert row["page_count"] == 3
        assert row["chars_total"] == total
    assert peek["chars"] <= 2
    assert "p=3" in _rg_find_line(find, ids_only=False)
    assert f"chars_total={total if total is not None else '-'}" in _rg_peek_line(peek)
    assert _project_find_document(doc, ["id"]) == {"id": 1}
    assert "chars_total" not in _project_peek_document(doc, ["id"], max_chars=2)


def test_skim_sizes_do_not_change_normalized_hit_offsets() -> None:
    doc = SimpleNamespace(id=2, content="x\t\tneedle\n", page_count=None)
    rows = _extract_skim_hits(
        doc, query="needle", context_before=2, context_after=2, max_hits_per_doc=1
    )
    assert rows[0]["chars_total"] == len(doc.content)
    assert rows[0]["page_count"] is None
    assert rows[0]["start"] == 2
