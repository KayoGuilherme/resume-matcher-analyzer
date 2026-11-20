"""PDF to text, read the way a simple ATS reads it (no column-aware reordering)."""

import io
from collections.abc import Mapping, Sequence
from importlib.metadata import version
from typing import Any

import pdfplumber

from app.ai.parsing.models import ParsedDocument, UnreadableDocumentError

# Layout thresholds. They are heuristics: tune them against real resumes.
MARGIN_BAND = 0.07  # top/bottom share of the page height treated as header/footer
LINE_TOLERANCE = 3.0  # words whose tops differ by less than this are on the same line (points)
GUTTER_MIN_WIDTH = 0.03  # a horizontal gap this wide (share of page width) can be a gutter
GUTTER_MIN_LINES = 5  # lines that must share the same gutter...
GUTTER_MIN_LINE_SHARE = 0.4  # ...and at least this share of the page's lines

Word = Mapping[str, Any]


def _has_margin_text(words: Sequence[Word], height: float) -> bool:
    return any(
        word["top"] < height * MARGIN_BAND or word["bottom"] > height * (1 - MARGIN_BAND)
        for word in words
    )


def _lines(words: Sequence[Word]) -> list[list[Word]]:
    lines: list[list[Word]] = []
    top = 0.0
    for word in sorted(words, key=lambda w: w["top"]):
        if lines and abs(word["top"] - top) <= LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
            top = word["top"]
    return lines


def _gaps(line: Sequence[Word], min_width: float) -> list[tuple[float, float]]:
    ordered = sorted(line, key=lambda w: w["x0"])
    return [
        (left["x1"], right["x0"])
        for left, right in zip(ordered, ordered[1:], strict=False)
        if right["x0"] - left["x1"] >= min_width
    ]


def _has_gutter(words: Sequence[Word], width: float) -> bool:
    """True when many lines share one wide vertical gap: text in side-by-side columns.

    Right-aligned dates leave gaps too, but only on a few lines, so they do not add up.
    """
    lines = _lines(words)
    if len(lines) < GUTTER_MIN_LINES:
        return False
    gaps_per_line = [_gaps(line, width * GUTTER_MIN_WIDTH) for line in lines]
    candidates = [(start + end) / 2 for gaps in gaps_per_line for start, end in gaps]
    needed = max(GUTTER_MIN_LINES, GUTTER_MIN_LINE_SHARE * len(lines))
    return any(
        sum(any(start <= x <= end for start, end in gaps) for gaps in gaps_per_line) >= needed
        for x in candidates
    )


def parse_pdf(data: bytes) -> ParsedDocument:
    """Extract text and layout facts. Any library failure becomes `UnreadableDocumentError`."""
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            texts: list[str] = []
            images = tables = 0
            header_footer = multi_column = False
            for page in pdf.pages:
                words = page.extract_words()
                texts.append(page.extract_text() or "")
                images += len(page.images)
                tables += len(page.find_tables())
                header_footer = header_footer or _has_margin_text(words, float(page.height))
                multi_column = multi_column or _has_gutter(words, float(page.width))
            page_count = len(pdf.pages)
    except Exception:
        # `from None`: library messages can quote document content.
        raise UnreadableDocumentError() from None
    if page_count == 0:
        raise UnreadableDocumentError()
    return ParsedDocument(
        file_type="pdf",
        text="\n".join(texts),
        page_count=page_count,
        parser=f"pdfplumber {version('pdfplumber')}",
        image_count=images,
        table_count=tables,
        multi_column=multi_column,
        header_footer_text=header_footer,
    )
