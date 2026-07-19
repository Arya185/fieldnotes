"""DOCX raw-content parser."""

from __future__ import annotations

from docx import Document

from backend.indexer.parsers import ContentSegment, DiscoveredFile, ParsedContent


def parse_docx(file: DiscoveredFile) -> ParsedContent:
    """Extract raw paragraph text from a DOCX."""

    document = Document(file.path)
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    segments = [
        ContentSegment(locator=f"para{index}", text=paragraph_text)
        for index, paragraph_text in enumerate(paragraphs, start=1)
    ]
    return ParsedContent(text="\n".join(paragraphs), segments=segments)
