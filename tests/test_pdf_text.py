"""Real PDF text layers, explicit boundaries, and actionable failures."""

import pytest
from pdf_fixtures import make_pdf

from pcli.core.errors import PcliError, UsageValidationError
from pcli.core.pdf_text import PAGE_SEPARATOR, extract_pdf_text


def test_selected_pages_preserve_text_and_offsets() -> None:
    result = extract_pdf_text(
        make_pdf(["Erste Seite", "Nicht ausgewaehlt", "Geb\u00fchr < 5"]),
        pages=[1, 3],
        max_pages=None,
    )
    assert result.text == "Erste Seite" + PAGE_SEPARATOR + "Geb\u00fchr < 5"
    assert result.pages == [1, 3] and result.page_count == 3
    assert result.empty_pages == []
    for span, expected in zip(result.page_spans, ["Erste Seite", "Geb\u00fchr < 5"], strict=True):
        assert result.text[span["start_char"] : span["end_char"]] == expected


def test_max_pages_alone_and_empty_text_are_reported() -> None:
    result = extract_pdf_text(make_pdf(["", "Second", "Third"]), pages=None, max_pages=2)
    assert result.pages == [1, 2]
    assert result.empty_pages == [1]
    assert result.pages_truncated is True and result.next_page == 3


@pytest.mark.parametrize(
    "payload,code",
    [
        (b"not a PDF", "UNSUPPORTED_DOCUMENT_FORMAT"),
        (b"%PDF-1.7\ninvalid\n%%EOF", "PDF_EXTRACTION_FAILED"),
        (make_pdf(["secret"], password="secret"), "PDF_ENCRYPTED"),
    ],
)
def test_invalid_or_unsupported_pdf_is_not_empty_success(payload: bytes, code: str) -> None:
    with pytest.raises(PcliError) as exc:
        extract_pdf_text(payload, pages=None, max_pages=None)
    assert exc.value.payload.code == code


def test_page_out_of_range_is_not_silently_dropped() -> None:
    with pytest.raises(UsageValidationError) as exc:
        extract_pdf_text(make_pdf(["Only"]), pages=[1, 2], max_pages=None)
    assert exc.value.payload.code == "PAGE_OUT_OF_RANGE"
