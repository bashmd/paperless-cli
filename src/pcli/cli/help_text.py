"""Plain, copyable usage contracts for token-based retrieval commands."""


def _plain(value: str) -> str:
    # Click's no-reflow marker applies to one paragraph, not the entire epilog.
    return "\n\n".join("\b\n" + part for part in value.strip().split("\n\n"))


_GLOBAL = """
Connection: profile=NAME url=URL token=TOKEN timeout=SECONDS
Stored auth is picked up automatically; see pcli auth --help.
"""

_DISCOVERY = """
Shared options (key=value or --key value):
  page_size=150            Maximum output rows per call, including skim hits.
  page=1                   Initial result page; omit when resuming a cursor.
  sort=-created            Optional server ordering; default: server relevance.
  max_pages_total=N        Scanned document-page budget (unknown counts cost 1).
  max_chars_total=N        Emitted text budget, not download size.
  stop_after_matches=N     Stop after N output rows. Budgets default to unset.
  cursor=TOKEN             Resume using the same query, fields and page_size.
  format=rg                Default; json buffers, ndjson streams, text aliases rg.
  doc_type=ID              Filter alias; other API filters pass through unchanged.
  custom_field_query=JSON  Paperless custom-field query expression.

Check complete, stop_reason, next_cursor in the final summary. Zero hits do not
prove exhaustion. Budgets may change on resume; query/output shape may not.
Streaming rows are provisional until the summary and exit status are known.
Sizes: page_count is server metadata; chars_total counts raw OCR characters.
Unknown sizes are null/-; zero means empty OCR. Neither measures token count.
"""

_SELECTORS = """
Selectors:
  ids=9,2,7                Restrict to IDs, preserving first-occurrence order.
  from_stdin=true          Read raw IDs or NDJSON items; cannot combine with ids.
  allow_partial=false      Set true only to accept an incomplete shortlist.
Stdin completion is validated before fetching. Upstream errors always fail.
cursor and from_stdin cannot be combined. Use set -o pipefail in shell pipelines.
"""

FIND_HELP = _plain(
    """Examples:
  pcli docs find query="health insurance" max_docs=100
  pcli docs find query="invoice" sort=-created fields=id,title,page_count,chars_total
  pcli docs find query="invoice" ids_only=true format=ndjson

Options:
  query=TEXT               Required Paperless full-text query.
  max_docs=200             Document scan cap; top is an alias.
  ids_only=false           true emits only IDs, overriding fields.
  fields=LIST              Comma-separated output fields. Defaults:
                           id,title,created,page_count,chars_total,score,snippet
Snippets prefer server highlights, then a short OCR preview; they are not evidence
of every occurrence. Use peek to preview or skim to find literal hits.
"""
    + _DISCOVERY
    + _GLOBAL
)

PEEK_HELP = _plain(
    """Examples:
  pcli docs peek ids=42,17 per_doc_max_chars=500
  pcli docs peek query="insurance" max_docs=30
  pcli docs find query="insurance" ids_only=true format=ndjson |
    pcli docs peek from_stdin=true allow_partial=true

Options:
  query=TEXT               Paperless query; optional with ids or from_stdin.
  max_docs=20              Query scan cap; selected IDs default to selection size.
  per_doc_max_chars=1200   Preview character limit; max_chars is an alias.
  fields=LIST              Defaults:
                           id,title,created,page_count,chars_total,tags,excerpt
Peek previews the beginning, not matches with context. chars measures the returned
excerpt; chars_total measures the full raw OCR. truncated describes the excerpt.
"""
    + _SELECTORS
    + _DISCOVERY
    + _GLOBAL
)

SKIM_HELP = _plain(
    """Examples:
  pcli docs skim query="late fee" stop_after_matches=10
  pcli docs skim ids=42,17 query="premium" context_before=80 context_after=160
  pcli docs find query="insurance" ids_only=true format=ndjson |
    pcli docs skim from_stdin=true allow_partial=true query="premium"

Options:
  query=TEXT               Required: Paperless query AND local literal needle.
  max_docs=200             Query scan cap; selected IDs default to selection size.
  context_before=200       Characters before each hit (not lines).
  context_after=300        Characters after each hit (not lines).
  max_hits_per_doc=3       Intentional per-document hit cap, not all occurrences.
Matching is case-insensitive literal search, NOT regex, in whitespace-normalized
OCR (or highlight fallback). query also filters server candidates, even with IDs.
start/end are zero-based normalized character offsets, not raw get offsets.
page is unknown for OCR hits; page_count describes the whole document.
"""
    + _SELECTORS
    + _DISCOVERY
    + _GLOBAL
)

GET_HELP = _plain(
    """Examples:
  pcli get 42
  pcli get 42 format=text max_chars=5000 start_char=5000
  pcli get 42 pages=1,3-5 max_pages=3
  pcli get 42 max_pages=5 format=text
  pcli get 42 source=original pages=2-3

Options (key=value or --key value):
  source=auto              OCR by default; page bounds prefer archive then original.
  source=ocr               Paperless OCR text; cannot take page bounds.
  source=archive|original  Extract PDF text; explicit sources never fall back.
  pages=SPEC               1-based page numbers/ranges; sorted and deduplicated.
  max_pages=N              Cap selected pages; alone selects first N PDF pages.
  max_chars=20000          Maximum returned Unicode characters (must be positive).
  start_char=0             Zero-based offset; resume using JSON meta.next_start.
  format=json             Default; text emits only text, notices on stderr.

PDF output has text once, plus page_spans/empty_pages metadata. Text pages are
separated by newline/form-feed/newline. Empty text does not prove a page is blank.
No new OCR pass; encrypted PDFs and non-PDF files fail explicitly.
pages_truncated/next_page report page caps, separately from character truncation.
next_page is a hint, not a continuation token for a noncontiguous selection.
OCR offsets, selected-PDF offsets and normalized skim offsets are different.
Resume with the same source and page selection. Bounds limit output, not download
bytes or parser memory; selected PDF pages are extracted before slicing text.
"""
    + _GLOBAL
)

FACETS_HELP = _plain(
    """Examples:
  pcli docs facets query="invoice" by=tags,year facet_scope=all
  pcli docs facets query="insurance" by=correspondent max_docs=100 facet_scope=all

Options (key=value or --key value):
  query=TEXT               Required Paperless query.
  by=LIST                  Required: tags,doc_type,document_type,correspondent,year.
  facet_scope=page         Default: count one result page; all scans from page 1.
  page=1 page_size=150     Page scope; all ignores page and uses bounded fetching.
  max_docs=N               Page scope defaults to min(200,page_size); all is uncapped.
  top_values=20            Most common values per dimension; ties sort by value text.
  sort=FIELD              Optional ordering; API filters also pass through.
  format=json             Facets always emit a JSON envelope after aggregation.

complete means the requested scope was counted. corpus_complete means all matching
documents were counted from the beginning. A cap can make counts partial.
values_truncated reports top_values truncation separately. Counters are streamed;
document bodies are not retained. No cursor; do not add partial top-value lists
to estimate corpus totals. A request failure emits no successful counts.
"""
    + _GLOBAL
)
