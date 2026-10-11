"""A Markdown directory as a vault of notes.

The files under the vault root are the source of truth. A Note is only the
in-memory view of one file: path, raw text, and a title.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

_HEADING = re.compile(r"^#\s+(.+?)\s*$")


@dataclass(frozen=True)
class Note:
    path: str
    content: str
    title: str


class Vault:
    def __init__(self, directory: str | Path):
        self.root = Path(directory).resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"vault root is not a directory: {self.root}")

    def list_notes(self) -> list[str]:
        notes: list[str] = []
        for path in self.root.rglob("*.md"):
            if not path.is_file() or _is_hidden(path, self.root):
                continue
            notes.append(path.relative_to(self.root).as_posix())
        return sorted(notes)

    def read_note(self, path: str) -> Note:
        file = self._resolve(path)
        if not file.is_file():
            raise FileNotFoundError(path)
        content = file.read_text(encoding="utf-8")
        return Note(path=self._relative(file), content=content, title=_title(file, content))

    def create_note(self, path: str, content: str) -> Note:
        file = self._resolve(path)
        if file.exists():
            raise FileExistsError(path)
        file.parent.mkdir(parents=True, exist_ok=True)
        _replace(file, content)
        return self.read_note(self._relative(file))

    def update_note(self, path: str, content: str) -> Note:
        file = self._resolve(path)
        if not file.is_file():
            raise FileNotFoundError(path)
        _replace(file, content)
        return self.read_note(self._relative(file))

    def delete_note(self, path: str) -> None:
        file = self._resolve(path)
        if not file.is_file():
            raise FileNotFoundError(path)
        file.unlink()

    def _resolve(self, path: str) -> Path:
        relative = Path(path)
        if relative.is_absolute():
            raise ValueError(f"path must stay inside the vault: {path}")
        full = (self.root / relative).resolve()
        if not full.is_relative_to(self.root):
            raise ValueError(f"path must stay inside the vault: {path}")
        if full.suffix.lower() != ".md":
            raise ValueError(f"not a markdown note: {path}")
        return full

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def _replace(file: Path, content: str) -> None:
    """Write `content` to a sibling temp file, then replace `file`."""
    fd, name = tempfile.mkstemp(prefix=f".{file.name}.", suffix=".tmp", dir=file.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, file)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _is_hidden(path: Path, root: Path) -> bool:
    return any(part.startswith(".") or part == "__pycache__" for part in path.relative_to(root).parts)


def _title(path: Path, content: str) -> str:
    for line in content.splitlines():
        match = _HEADING.match(line)
        if match:
            return match.group(1)
    return path.stem
