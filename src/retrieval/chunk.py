"""Split a Markdown note into retrieval chunks.

Chunks come from `MarkdownSplitter` in `semantic-text-splitter`. It keeps
Markdown boundaries such as headings and code blocks, and merges neighboring
sections until a chunk reaches the character limit.
"""

from __future__ import annotations

import re

from semantic_text_splitter import MarkdownSplitter

_CHUNK_CHARACTERS = 1500
_SPLITTER = MarkdownSplitter(_CHUNK_CHARACTERS)
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")


def split_markdown(text: str) -> list[tuple[int, str]]:
    """Return each chunk as a 1-based start line and its text."""
    if not text.strip():
        return []
    chunks: list[tuple[int, str]] = []
    for offset, chunk in _SPLITTER.chunk_indices(text):
        if not chunk.strip():
            continue
        chunks.append((text.count("\n", 0, offset) + 1, chunk))
    return chunks


def section_title(note_title: str, chunk: str) -> str:
    for line in chunk.splitlines():
        match = _HEADING.match(line)
        if match is None:
            continue
        heading = match.group(1)
        if heading == note_title:
            return note_title
        return f"{note_title} / {heading}"
    return note_title
