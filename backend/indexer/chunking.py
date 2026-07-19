"""Deterministic text chunking and stable anchor generation."""

from __future__ import annotations

from dataclasses import dataclass

from backend.indexer.parsers import ParsedFile


MAX_CHUNK_CHARS = 1200


@dataclass(frozen=True)
class ChunkCandidate:
    ordinal: int
    anchor: str
    text: str


def build_chunks(parsed_file: ParsedFile) -> list[ChunkCandidate]:
    """Build deterministic chunks from parsed text segments."""

    if parsed_file.content is None or not parsed_file.content.segments:
        return []

    chunks: list[ChunkCandidate] = []
    ordinal = 0
    for segment in parsed_file.content.segments:
        segment_chunks = split_segment_text(segment.text)
        for chunk_index, chunk_text in enumerate(segment_chunks, start=1):
            ordinal += 1
            chunks.append(
                ChunkCandidate(
                    ordinal=ordinal,
                    anchor=f"{segment.locator}/b{chunk_index}",
                    text=chunk_text,
                )
            )

    return chunks


def split_segment_text(text: str, max_chunk_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split text deterministically on paragraph boundaries, then sentence fallback."""

    normalized = text.strip()
    if not normalized:
        return []

    paragraphs = [paragraph.strip() for paragraph in normalized.split("\n\n") if paragraph.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs or [normalized]:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chunk_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(paragraph) <= max_chunk_chars:
            current = paragraph
            continue

        chunks.extend(split_long_text(paragraph, max_chunk_chars))

    if current:
        chunks.append(current)

    return chunks


def split_long_text(text: str, max_chunk_chars: int) -> list[str]:
    """Fallback splitter for very long paragraphs."""

    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    current_words: list[str] = []
    current_length = 0

    for word in words:
        extra = len(word) if not current_words else len(word) + 1
        if current_length + extra > max_chunk_chars and current_words:
            chunks.append(" ".join(current_words))
            current_words = [word]
            current_length = len(word)
        else:
            current_words.append(word)
            current_length += extra

    if current_words:
        chunks.append(" ".join(current_words))

    return chunks
