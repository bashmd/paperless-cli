"""OCR evidence is not HTML, even when it contains angle brackets."""

from types import SimpleNamespace

from pcli.cli.docs import _project_find_document, _rg_peek_line, _rg_skim_lines


def test_rg_keeps_literal_comparisons_and_markup() -> None:
    text = "Value < 5 and > 2; literal <span>example</span>"
    assert text in _rg_peek_line({"id": 1, "excerpt": text})
    assert text in _rg_skim_lines({"doc_id": 1, "hit": "Value", "text": text})[1]
    document = SimpleNamespace(content=text)
    assert _project_find_document(document, ["snippet"])["snippet"] == text


def test_only_known_search_highlighting_is_removed() -> None:
    document = SimpleNamespace(
        search_hit=SimpleNamespace(
            highlights='Value <span class="match">5</span> and < 9 and > 2',
        )
    )
    assert _project_find_document(document, ["snippet"])["snippet"] == "Value 5 and < 9 and > 2"
