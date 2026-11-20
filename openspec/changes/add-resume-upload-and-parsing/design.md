# Design

## Context

See proposal.md for motivation and the specs for behavior. Observed current state:

- `src/app/` has `core/` (`config`, `db`, `errors`, `logging`, `normalization`), `health/` and `profile/` (the reference for router -> service -> repository, `DomainError` subclasses, Pydantic in/out schemas, a repository that upserts and commits). `get_session` yields one `AsyncSession` per request; engines are created lazily. `Settings` is frozen, read only from the environment, and `.env.example` lists every variable.
- `core/errors.py` maps `DomainError` and `RequestValidationError` to `{"error": {"code", "message"}}`; anything else is a generic 500 that logs only the exception type.
- `core/logging.py` writes JSON logs and copies `extra` fields into them. `configure_logging(level)` sets the root logger, so third-party loggers inherit it (including DEBUG).
- Migrations `0001` (pgvector) and `0002` (candidate profile) exist; `alembic/env.py` imports each model module. CI runs unit tests without a database (coverage >= 80%), plus `alembic upgrade head`, `alembic check` and `pytest -m integration` against a real PostgreSQL.
- The image runs as the non-root user `app` (`/app` is root-owned; only `/app/.venv` is owned by `app`); `docker-compose.yml` has `api` and `db` with a named volume for the database only.
- `pdfplumber`, `python-docx` and `python-multipart` all ship `py.typed`, so `mypy` strict applies to them. `lxml` (pulled by python-docx) has no stubs and is only reached through python-docx.

## Goals / Non-Goals

**Goals:**
- Accept only real PDF/DOCX files, keep the original, extract text the way a simple ATS would, and report layout problems with stable codes.
- Keep the parsing code pure and testable on generated fixtures; keep the event loop free.
- No resume text or file name in logs, errors or on-disk file names, even at DEBUG.

**Non-Goals:**
- OCR, LLM extraction, embeddings, analysis, re-parsing, pagination, authentication, antivirus scanning.
- Detecting every ATS hazard (text boxes, borderless tables, fonts without a text layer beyond the listed checks).
- Per-document parse timeouts or page caps (see Risks).

## Decisions

**1. Parsing lives in `ai/parsing/`, split into extract (impure-looking, pure in practice) and check (pure).**
Files: `models.py` (`ParsedDocument`, `ParsingIssue`, `Severity`, `UnreadableDocumentError`), `detect.py` (`detect_file_type(data) -> "pdf" | "docx" | None`), `pdf.py` and `docx.py` (`parse_pdf(data)`, `parse_docx(data) -> ParsedDocument`), `quality.py` (`check_quality(ParsedDocument) -> list[ParsingIssue]`), and `__init__.py` with `parse_document(data, file_type)`. `ParsedDocument` is a frozen Pydantic model: `file_type`, `text`, `page_count` (None when unknown), `image_count`, `table_count`, `multi_column`, `header_footer_text`, `parser` (name + version). The extractors compute the layout facts that need the file (columns, tables, images, header/footer); `check_quality` turns facts and text into issues and does the text-only checks (glyph bullets, headings, density, page count). This keeps almost all rules unit-testable without files. Issue messages are plain code constants (they are not LLM prompts, so the "prompts as .md" rule does not apply), in English.

**2. File type detection with the standard library only.**
PDF: the bytes start with `%PDF-`. DOCX: starts with `PK\x03\x04`, opens with `zipfile`, and contains `[Content_Types].xml` and `word/document.xml`. Extension and content type are ignored. Any other ZIP, text or image is `None` -> `unsupported_file_type` (415). Before handing a DOCX to python-docx, the sum of uncompressed member sizes is checked against a fixed cap (50 MB); over the cap is treated as `unreadable_file` (zip-bomb guard; the 5 MB upload limit alone does not bound decompression).

**2b. PDF extraction mirrors a naive ATS.**
`pdfplumber.open(BytesIO(data))`; per page `extract_text()` and the pages joined with a line break. No column-aware reordering: a two-column PDF reads line by line across both columns, which is exactly what makes it a problem. Any exception while opening or reading (corrupt, truncated, encrypted) becomes `UnreadableDocumentError`, raised `from None` so no library message (which may quote content) is kept. `page_count` is `len(pdf.pages)`.

**3. Layout checks (PDF).**
- Images: `sum(len(page.images))`. `image_only_pdf` when there is no text and at least one image.
- Tables: `page.find_tables()` with the default (ruled-lines) strategy. Borderless "tables" are not detected (known limit).
- Header/footer: any word whose box lies in the top or bottom 7% of the page height.
- Multi-column: per page, words are grouped into lines by their `top`; for each line the horizontal gaps wider than 3% of page width are noted. A gutter exists at an x position when at least 5 lines, and at least 40% of the page's lines, have such a gap covering it, with words on both sides. Right-aligned dates leave gaps at varying x, so they do not line up into a gutter; the clean fixture contains such dates to guard against that false positive. The thresholds are named constants tuned against the fixtures and are expected to need adjusting on real resumes.
**Layout checks (DOCX).** Tables: `document.tables` (any). Header/footer: any section with a non-empty header, footer, first-page or even-page header/footer paragraph. Multi-column: any section whose `w:cols` has `w:num` > 1. Text: iterate the body children in order and read paragraphs and table cells (cells joined by tab, rows by line break); text boxes are not visible to python-docx (known limit). Page count: regex on `docProps/app.xml` for `<Pages>n</Pages>` (the first 64 KB only, no XML parser on untrusted input); absent -> None, and the page-based checks (`low_text_ratio`, `too_many_pages`) are skipped.

**4. Text-only checks.**
- `special_glyph_bullets`: a line whose first non-space character has Unicode category `So` or `Co`. `•` (`Po`), `-`, `–`, `*` are not flagged.
- Missing sections: each line is folded (trim, lowercase, accents removed, trailing `:` removed) and compared with a set of recognized headings per section in English and Portuguese. This needs an accent-insensitive fold, so `core/normalization.py` exposes a small public `fold_text()` (the existing private helpers composed); no change to the behavior of the name functions.
- `low_text_ratio`: page count known and `0 < characters / pages < 500`. `too_many_pages`: page count known and > 3.
- Severities: `image_only_pdf` critical; `info` only for `too_many_pages`; everything else `warning`. Ordering: severity, then code.

**5. Upload flow in `resumes/service.py` (business rules), in this order.**
1. Reject `len(data) > max` -> `FileTooLargeError` (413). The router reads at most `max + 1` bytes from the upload, so memory is bounded.
2. Reject `len(data) == 0` -> `EmptyFileError` (422).
3. `detect_file_type` -> `UnsupportedFileTypeError` (415).
4. `sha256` and look up an existing resume; if found, return it (200) without parsing or storing.
5. `parse_document` in the threadpool (`starlette.concurrency.run_in_threadpool`; CPU-bound work off the event loop) -> `UnreadableDocumentError` becomes `UnreadableFileError` (422).
6. Empty text (after strip) -> `NoExtractableTextError` (422); the message explains the ATS problem and adds the scanned/image-only sentence when the document had images.
7. `check_quality`, then `storage.save(key, data)`, then `repository.add(...)`. If `add` reports a conflict (concurrent identical upload), the existing row is read and returned as 200, and the stored file is left in place (same bytes, same key). If `add` fails for another reason, the file is deleted and the error propagates. A storage failure raises before any row exists, so a failed upload never leaves a record (generic 500).
Error messages never include the file name or any content; the 413 message states the limit (`5 MB`).

**6. Persistence: table `resume`, one row per distinct content.**
Columns: `id` (UUID, generated in Python), `sha256` (text, unique, not null), `original_filename` (text), `file_type` (text), `size_bytes` (integer), `page_count` (integer, nullable), `text` (text), `parsing_metadata` (JSONB: parser, character/word/table/image counts), `issues` (JSONB list), `created_at` (timestamptz, set in Python). Dedupe is enforced by the unique constraint: `INSERT ... ON CONFLICT (sha256) DO NOTHING RETURNING id` is atomic and avoids catching `IntegrityError`. `original_filename` is stored (directory part removed, 255 characters max) so the candidate recognizes the resume in a list; it is never logged and never used in a path. Alternative: not store it (rejected: the list would only show opaque ids). `DELETE ... WHERE id = :id RETURNING sha256, file_type` then commit, then the stored file is deleted best-effort (an orphan file is harmless; a row pointing to a missing file is not). The repository only does this DB access and maps rows to Pydantic models; the same commit-inside-repository style as the profile feature is used.

**7. `FileStorage` in `core/storage.py` (infrastructure shared by features).**
A `Protocol` with async `save(key, data)`, `read(key)`, `delete(key)` and `exists(key)`; `LocalFileStorage(root)` is the only implementation. File I/O runs through `asyncio.to_thread`; writes go to a temporary file in the same directory and are moved into place with `os.replace` (no partial files); the directory is created on first write, never at import time. Keys must be a single path segment (no separators, no `..`, not empty); anything else raises `ValueError`, so a key can never escape the root. The key is `<sha256>.<pdf|docx>`, so on-disk names contain no personal data. The dependency `get_file_storage(settings)` builds it per request. Placing it in `core/` (like `normalization.py`) rather than in the feature folder keeps the feature folder structure unchanged; this is a judgment call that can be revisited.

**8. HTTP layer.**
`POST /resumes` takes `file: UploadFile`, reads `max + 1` bytes and calls the service; the response status is set to 201 for a new resume and 200 for an existing one (`Response` parameter). `GET /resumes` returns `list[ResumeSummary]` newest first; `GET /resumes/{id}` (`UUID` path parameter, so a malformed id is a standard validation 422) returns `ResumeDetail`; `DELETE` returns 204 or 404. Starlette stores the whole multipart body before the handler runs, so a dependency on `POST /resumes` also rejects, before the body is read, requests whose `Content-Length` header exceeds `max` plus a fixed multipart overhead (64 KiB) with the same 413 error. This is a cheap first line of defense; requests without the header, or lying about it, are still bounded by the `max + 1` read. A reverse-proxy body limit is the real protection in production and is noted in the README.

**9. Logging and privacy.**
The service logs one `resume uploaded` / `resume deleted` event with the resume id, size, file type, `created`, and the list of issue codes; never text or file names. Third-party libraries can print document content at DEBUG (pdfminer logs parsed tokens), so `configure_logging` caps the `pdfminer`, `pdfplumber` and `PIL` loggers at WARNING regardless of the application log level; a test uploads a PDF with DEBUG enabled and asserts the text is absent from all captured logs. Rejections keep the exception-type-only logging of `core/errors.py`.

**10. Configuration, Docker and ignores.**
`Settings` gains `resume_max_upload_bytes: int` (default 5 242 880, must be > 0) and `resume_storage_dir: Path` (default `data/resumes`). `.env.example` lists both. In Docker, `RESUME_STORAGE_DIR` is set in `docker-compose.yml` under `environment` (it wins over `env_file`) to `/data/resumes`, backed by a new named volume; the Dockerfile creates `/data/resumes` owned by `app` before `USER app`, so a fresh named volume inherits that ownership. `data/` is added to `.gitignore` and `.dockerignore` (local runs write there).

**11. Test fixtures are generated, not committed binaries.**
`tests/fixtures/documents.py` builds: a clean one-column PDF (sections, `•` bullets, right-aligned dates), a two-column PDF, a PDF with a ruled table, a PDF with header/footer text, a scanned PDF (a page that is a single image), a fake PDF (text with a `.pdf` name), and DOCX files (python-docx: clean, table, header, two-column section, with/without app properties). PDFs come from a minimal writer (Helvetica standard font, WinAnsi encoding, text positioned with `Td`, lines drawn for tables, one image XObject) of about 60 lines, so no PDF-writing library is added. Each builder has a test showing the file parses as intended, so a broken fixture fails visibly. Alternative: `reportlab` as a dev dependency (more realistic PDFs, but one more dependency and a heavier tree).

**12. Testing strategy.** Parsing and quality: pure unit tests on fixtures and constructed `ParsedDocument`s (one test per issue code and per spec scenario, including false-positive guards). Service: fake repository and storage, real parsing on fixtures. Repository: fake session (statement compiled and checked, as for the profile). Router: service/storage dependency overrides plus end-to-end HTTP tests of the five acceptance fixtures on the real app with fakes. Storage: `tmp_path`. `integration` tests (real PostgreSQL, real temp directory): upload -> duplicate -> list -> get -> delete, file present then gone. Migration test as in `0002`, plus real `alembic upgrade/check/downgrade` during implementation.

## Risks / Trade-offs

- [Hand-made fixtures may not behave like PDFs from Word, Canva or Chrome (embedded fonts, ToUnicode maps, different text positioning)] -> detection thresholds are named constants and the layout checks are tested on both sides; acceptance on a few real resumes is recommended after this change but not required here.
- [Multi-column heuristic false positives/negatives (sidebars, centered headers, right-aligned dates)] -> the gutter must line up across many lines; documented limits; issues are warnings, never rejections.
- [Borderless tables and text boxes are not detected] -> accepted limit, listed in the README; they can be added as new codes later without changing existing ones.
- [Pathological PDFs (thousands of pages, deep object trees) can make parsing slow within 5 MB] -> parsing runs in a threadpool so other requests are not blocked; no timeout or page cap in this change (a later change can add one if needed).
- [Large uploads are spooled by Starlette before the size check] -> early `Content-Length` rejection plus a documented reverse-proxy limit.
- [Zip bombs in DOCX] -> uncompressed-size cap before python-docx opens the file.
- [A crash between storing the file and inserting the row leaves an orphan file] -> harmless and content-addressed (re-upload reuses the same key); the reverse (a row without a file) cannot happen because the file is written first.
- [`lxml`/python-docx internals may not satisfy `mypy` strict] -> only the public python-docx API plus `qn()` is used; a narrow `type: ignore` or a mypy override for `lxml` is acceptable if needed, never a blanket ignore.
- [The stored file name can contain personal data] -> stored in the database only, returned to the single user who uploaded it, never logged and never used for the on-disk name.
- [Stored full text is personal data in the database] -> single user, no new exposure; deletion removes row and file.
- [`low_text_ratio` can flag legitimately short resumes] -> warning only, with a message that says how to read it.
