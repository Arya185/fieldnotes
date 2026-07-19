"""Text and Markdown raw-content parser."""

from __future__ import annotations

from backend.indexer.parsers import ContentSegment, DiscoveredFile, ParsedContent


def parse_text(file: DiscoveredFile) -> ParsedContent:
    """Read raw UTF-8 text from plain-text files."""

    text = file.path.read_text(encoding="utf-8")
    blocks = [block.strip() for block in text.split("\n\n")]
    segments = [
        ContentSegment(locator=f"block{index}", text=block)
        for index, block in enumerate(blocks, start=1)
        if block
    ]
    return ParsedContent(text=text, segments=segments)
