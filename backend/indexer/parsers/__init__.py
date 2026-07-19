"""Common parser contracts and registry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from backend.models import DatasetProfile


SupportedKind = str
ParseStatus = str

SUPPORTED_FILE_TYPES: tuple[SupportedKind, ...] = (
    "pdf",
    "pptx",
    "docx",
    "md",
    "txt",
    "csv",
)


@dataclass(frozen=True)
class DiscoveredFile:
    path: Path
    relative_path: str
    display_name: str
    size_bytes: int
    kind: SupportedKind


@dataclass(frozen=True)
class ContentSegment:
    locator: str
    text: str


@dataclass(frozen=True)
class ParsedContent:
    text: str | None = None
    table_rows: list[list[str]] | None = None
    segments: list[ContentSegment] | None = None
    dataset_profile: DatasetProfile | None = None


@dataclass(frozen=True)
class ParsedFile:
    path: Path
    relative_path: str
    display_name: str
    size_bytes: int
    kind: SupportedKind
    parse_status: ParseStatus
    content: ParsedContent | None
    error_message: str | None = None


class Parser(Protocol):
    def __call__(self, file: DiscoveredFile) -> ParsedContent:
        """Parse raw content from a discovered file."""


from .csv import parse_csv  # noqa: E402
from .docx import parse_docx  # noqa: E402
from .pdf import parse_pdf  # noqa: E402
from .pptx import parse_pptx  # noqa: E402
from .text import parse_text  # noqa: E402

PARSER_REGISTRY: dict[SupportedKind, Parser] = {
    "pdf": parse_pdf,
    "pptx": parse_pptx,
    "docx": parse_docx,
    "md": parse_text,
    "txt": parse_text,
    "csv": parse_csv,
}
