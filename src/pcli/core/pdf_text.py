"""PDF text-layer extraction. No OCR, guessed page boundaries, or global imports."""

from dataclasses import dataclass
from io import BytesIO

from pcli.core.errors import PcliError, UsageValidationError

PAGE_SEPARATOR = "\n\f\n"


@dataclass
class PdfText:
    text: str
    pages: list[int]
    page_count: int
    page_spans: list[dict[str, int]]
    empty_pages: list[int]
    pages_truncated: bool
    next_page: int | None


def extract_pdf_text(
    payload: bytes,
    *,
    pages: list[int] | None,
    max_pages: int | None,
    pages_truncated: bool = False,
    next_page: int | None = None,
) -> PdfText:
    # Do not infer format from a filename or a frequently generic HTTP content type.
    if b"%PDF-" not in payload[:1024]:
        raise UsageValidationError(
            "Page extraction requires a PDF file; try its archive or source=ocr without pages.",
            error_code="UNSUPPORTED_DOCUMENT_FORMAT",
        )
    from pypdf import PdfReader

    try:
        with PdfReader(BytesIO(payload)) as reader:
            if reader.is_encrypted:
                raise UsageValidationError(
                    "Encrypted PDF extraction is not supported; use source=ocr without pages.",
                    error_code="PDF_ENCRYPTED",
                )
            count = len(reader.pages)
            selected = pages
            if selected is None:
                limit = min(count, max_pages) if max_pages is not None else count
                selected = list(range(1, limit + 1))
                pages_truncated = limit < count
                next_page = limit + 1 if pages_truncated else None
            if any(page < 1 or page > count for page in selected):
                raise UsageValidationError(
                    "Requested page is outside the PDF page range.",
                    details={"page_count": count, "pages": selected},
                    error_code="PAGE_OUT_OF_RANGE",
                )
            texts: list[str] = []
            spans: list[dict[str, int]] = []
            empty: list[int] = []
            offset = 0
            for number in selected:
                text = reader.pages[number - 1].extract_text() or ""
                if not text.strip():
                    empty.append(number)
                if texts:
                    offset += len(PAGE_SEPARATOR)
                spans.append({"page": number, "start_char": offset, "end_char": offset + len(text)})
                texts.append(text)
                offset += len(text)
            return PdfText(
                PAGE_SEPARATOR.join(texts),
                selected,
                count,
                spans,
                empty,
                pages_truncated,
                next_page,
            )
    except PcliError:
        raise
    except Exception as exc:
        raise PcliError(
            "PDF text extraction failed. Try source=ocr without page bounds.",
            details={"cause": type(exc).__name__},
            error_code="PDF_EXTRACTION_FAILED",
        ) from exc
