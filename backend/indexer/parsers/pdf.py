"""PDF raw-content parser."""

from __future__ import annotations

import fitz

from backend.indexer.parsers import ContentSegment, DiscoveredFile, ParsedContent


def parse_pdf(file: DiscoveredFile) -> ParsedContent:
    """Extract raw page text from a PDF."""

    document = fitz.open(file.path)
    try:
        pages = [page.get_text("text") for page in document]
    finally:
        document.close()

    segments = [
        ContentSegment(locator=f"p{index}", text=page_text)
        for index, page_text in enumerate(pages, start=1)
    ]
    return ParsedContent(text="\n\f\n".join(pages), segments=segments)
