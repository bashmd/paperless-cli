# pcli Command Cookbook

## 1. Quick Start

Authenticate and persist a reusable profile/token:

```bash
pcli auth <username> <password> url=https://paperless.example.com
pcli auth status
```

Switch profiles when you manage multiple Paperless instances:

```bash
pcli auth list
pcli auth switch default
```

## 2. LLM Discovery Pipelines

Find candidates and stream ID-only output:

```bash
pcli docs find query="invoice acme" ids_only=true max_docs=200 format=ndjson
```

Chain into `peek` from stdin:

```bash
pcli docs find query="invoice acme" ids_only=true format=ndjson \
  | pcli docs peek from_stdin=true allow_partial=true fields=id,title,excerpt max_docs=50
```

Chain into `skim` for context-rich matches:

```bash
pcli docs find query="late fee" ids_only=true format=ndjson \
  | pcli docs skim from_stdin=true allow_partial=true query="late fee" context_before=160 context_after=240
```

Resume paged discovery with cursors:

```bash
pcli docs find query="contracts" page_size=100
pcli docs find query="contracts" page_size=100 cursor=<next_cursor_token>
```

## 3. Deep Retrieval

Get bounded OCR text (20,000 characters by default):

```bash
pcli get 123
pcli get 123 format=text max_chars=5000
pcli get 123 format=text start_char=5000 max_chars=5000
```

Restrict to specific pages with a max page cap:

```bash
pcli get 123 pages=1-3,5 max_pages=2
pcli get 123 max_pages=5 format=text
```

Force retrieval source:

```bash
pcli docs get 123 source=archive pages=2-4
```

PDF page text and OCR text have different character offsets. JSON `next_start`
resumes within the same source and page selection; `page_spans` locates selected
pages in that text. `pages_truncated` reports page caps independently of character
truncation. `empty_pages` can indicate blank or image-only pages; extraction does
not run OCR. Invalid pages and unsupported files fail instead of being omitted.

Use size hints before full retrieval:

```bash
pcli docs find query="insurance" fields=id,title,page_count,chars_total
pcli docs peek ids=123,456 per_doc_max_chars=500
```

Count across the query, not just the first result page:

```bash
pcli docs facets query="invoice" by=tags,year facet_scope=all
pcli docs facets query="invoice" by=tags facet_scope=all max_docs=1000
```

Check `corpus_complete` before treating counts as corpus totals. `complete` describes
the requested facet scope, and `values_truncated` describes the top-value list cap.
Do not add partial top-value lists to estimate full totals. For exact defaults and
continuation rules, use `pcli docs skim --help` or `pcli get --help`.

## 4. Document Operations

List and search:

```bash
pcli docs list query="invoice" page=1 page_size=50
pcli docs search "supplier payment" page=1 page_size=50
```

Binary payloads:

```bash
pcli docs download 123 output=./out/doc-123.pdf
pcli docs preview 123 output=./out/doc-123-preview.pdf
pcli docs thumbnail 123 output=./out/doc-123-thumb.webp
```

Notes:

```bash
pcli docs notes list 123
pcli docs notes add 123 note="needs follow-up"
pcli docs notes delete 123 45 yes=true
```

Mutations:

```bash
pcli docs create document=./in/invoice.pdf title="Invoice 2026-001" correspondent=7 tags=1,2
pcli docs update 123 title="Invoice 2026-001 (paid)" only_changed=true
pcli docs delete 123 yes=true
```

## 5. Generic Resource Operations

CRUD resources (`tags`, `correspondents`, `doc-types`, `storage-paths`, `custom-fields`, `share-links`):

```bash
pcli tags list page=1 page_size=100
pcli tags get 7
pcli tags create name="urgent"
pcli tags update 7 name="urgent-high" only_changed=true
pcli tags delete 7 yes=true
```

Read-only resources:

```bash
pcli users list
pcli users get 4
pcli workflows list
pcli workflow-actions get 12
```

Singleton resources:

```bash
pcli status get
pcli stats get
pcli config get          # defaults to id=1
pcli config get id=2
pcli remote-version get
```

Tasks:

```bash
pcli tasks list
pcli tasks get 42
pcli tasks get 2d8ef9d7-2d8a-45ff-9f97-6d0ab6e8f402
```

## 6. Permissions Expansion

For resources that support permission expansion, request full permission tables:

```bash
pcli tags get 7 full_perms=true
pcli users list full_perms=true
```
