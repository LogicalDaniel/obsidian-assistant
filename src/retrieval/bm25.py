"""BM25 retrieval over a vault.

This layer reads notes from a Vault and owns the disposable index. Vault stays
unaware of scoring. Tools call `search`. The agent does not retrieve by itself.
"""

from __future__ import annotations

import logging
import math
import warnings
from collections import Counter
from dataclasses import dataclass

warnings.filterwarnings("ignore", category=SyntaxWarning, module="jieba")
import jieba

jieba.setLogLevel(logging.ERROR)

from retrieval.chunk import section_title, split_markdown
from vault.vault import Vault

# k1 saturates term frequency: the first occurrences add more than later ones.
# b is how strongly a note longer than average is penalized.
_K1 = 1.2
_B = 0.75
_SNIPPET_RADIUS = 80


@dataclass(frozen=True)
class Hit:
    path: str
    title: str
    score: float
    line: int
    snippet: str


@dataclass(frozen=True)
class _Doc:
    path: str
    title: str
    content: str
    length: int
    start_line: int


class BM25Index:
    """An index rebuilt from the vault's notes. Discard and construct again after edits."""

    def __init__(self, vault: Vault):
        self.vault = vault
        self._docs: list[_Doc] = []
        self._postings: dict[str, list[tuple[int, int]]] = {}
        self._avgdl = 0.0
        self._build()

    def search(self, query: str, limit: int = 10) -> list[Hit]:
        terms = list(dict.fromkeys(tokenize(query)))
        if limit < 1 or not terms or not self._docs or self._avgdl == 0:
            return []
        # score(d, q) = sum over query terms of IDF(t) * tf_weight(t, d)
        scores = [0.0] * len(self._docs)
        for term in terms:
            postings = self._postings.get(term)
            if not postings:
                continue
            idf = _idf(len(self._docs), len(postings))
            for doc_index, tf in postings:
                weight = _tf_weight(tf, self._docs[doc_index].length, self._avgdl)
                scores[doc_index] += idf * weight
        ranked = sorted(
            ((score, doc) for score, doc in zip(scores, self._docs, strict=True) if score > 0),
            key=lambda item: (-item[0], item[1].path),
        )
        return [
            Hit(
                doc.path,
                doc.title,
                score,
                *_locate(doc.content, doc.title, terms, doc.start_line),
            )
            for score, doc in ranked[:limit]
        ]

    def _build(self) -> None:
        total = 0
        for path in self.vault.list_notes():
            note = self.vault.read_note(path)
            for start_line, chunk in split_markdown(note.content):
                tokens = tokenize(f"{note.title}\n{chunk}")
                doc_index = len(self._docs)
                self._docs.append(
                    _Doc(
                        note.path,
                        section_title(note.title, chunk),
                        chunk,
                        len(tokens),
                        start_line,
                    )
                )
                total += len(tokens)
                for term, tf in Counter(tokens).items():
                    self._postings.setdefault(term, []).append((doc_index, tf))
        if self._docs:
            self._avgdl = total / len(self._docs)


def _idf(n_docs: int, n_term: int) -> float:
    # IDF(t) = ln(1 + (N - n_t + 0.5) / (n_t + 0.5))
    # N is the number of chunks. n_t is how many chunks contain t.
    # The added 1 keeps this positive when t is common.
    return math.log(1 + (n_docs - n_term + 0.5) / (n_term + 0.5))


def _tf_weight(tf: int, length: int, avgdl: float) -> float:
    # (f * (k1 + 1)) / (f + k1 * (1 - b + b * |d| / avgdl))
    # f is how often t occurs in this chunk. |d| is the chunk's token count.
    # avgdl is the mean token count across chunks.
    norm = 1 - _B + _B * length / avgdl
    return tf * (_K1 + 1) / (tf + _K1 * norm)


def tokenize(text: str) -> list[str]:
    """Split Chinese-English text into the terms BM25 counts.

    The whole string goes to jieba once. It cuts Chinese into words and leaves
    English words whole, so ``lora`` is not found inside ``exploration``.
    Spaces and punctuation come back as their own pieces and are dropped.
    English tokens are casefolded.
    """
    tokens: list[str] = []
    for piece in jieba.lcut(text):
        if any(char.isascii() and char.isalnum() or _is_chn(char) for char in piece):
            tokens.append(piece.casefold())
    return tokens


def _is_chn(char: str) -> bool:
    code = ord(char)
    return 0x4E00 <= code <= 0x9FFF


def _locate(content: str, title: str, terms: list[str], start_line: int) -> tuple[int, str]:
    folded = content.casefold()
    found_at: int | None = None
    found_term = ""
    for term in terms:
        at = folded.find(term)
        if at >= 0 and (found_at is None or at < found_at):
            found_at = at
            found_term = term
    if found_at is None:
        text = content.strip() or title
        return start_line, " ".join(text.split())[: _SNIPPET_RADIUS * 2]
    line = start_line + content.count("\n", 0, found_at)
    start = max(0, found_at - _SNIPPET_RADIUS)
    end = min(len(content), found_at + len(found_term) + _SNIPPET_RADIUS)
    return line, " ".join(content[start:end].split())
