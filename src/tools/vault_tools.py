"""Tools over a Markdown vault and the workspace."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from pypdf import PdfReader

from retrieval.bm25 import BM25Index
from skills.skill import declared_tools
from tools.obsidian_tools import NoteLinksTool
from tools.registry import Tool, ToolRegistry
from vault.vault import Note, Vault, _is_hidden

_PAGE_LINES = 80
_PDF_PAGES = 4
_PREVIEW_LINES = 2


class ListNotesTool(Tool):
    name = "list_notes"
    description = "List the markdown notes in the vault. Each line is a path relative to the vault root."
    parameters = {"type": "object", "properties": {}}

    def __init__(self, vault: Vault):
        self.vault = vault

    def execute(self, **arguments) -> str:
        if arguments:
            raise TypeError("list_notes takes no arguments")
        return "\n".join(self.vault.list_notes())


class GlobTool(Tool):
    name = "glob"
    description = (
        "List files in the vault whose relative path matches a glob pattern. "
        "Each line is a path. Examples: **/*.pdf, Papers/*.md."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob relative to the vault root, for example **/*.pdf.",
            }
        },
        "required": ["pattern"],
    }

    def __init__(self, vault: Vault):
        self.vault = vault

    def execute(self, pattern: str) -> str:
        return "\n".join(_glob(self.vault, pattern))


class ReadNoteTool(Tool):
    name = "read_note"
    description = (
        "Read one markdown note in the notes vault, starting at offset. "
        "Vault paths such as Other/bench-pad.md and RL/mcts.md use this tool, "
        "including to find a line before insert_text or delete_lines. "
        "Workspace files such as skills/research.md are read_file. "
        f"Returns at most {_PAGE_LINES} lines. "
        "Use the line number from search_notes as offset. Blank lines count. "
        "If the page says the value is later, or the result says the note continues, "
        "call again with that offset before answering. Do not ask the user whether to continue."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path relative to the notes vault, for example Other/bench-pad.md. Not a workspace path.",
            },
            "offset": {
                "type": "integer",
                "description": "1-based line to start from. Use the line number from search_notes.",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum number of lines to return. Defaults to {_PAGE_LINES}.",
            },
        },
        "required": ["path"],
    }

    def __init__(self, vault: Vault):
        self.vault = vault

    def execute(self, path: str, offset: int = 1, limit: int = _PAGE_LINES) -> str:
        return _page(self.vault.read_note(path), offset, limit, "read_note")


class SearchNotesTool(Tool):
    name = "search_notes"
    description = (
        "Search notes with BM25. Better matches come first. "
        "Each hit includes the relative path, title, the 1-based line of the first match, "
        "and a short snippet. The snippet is not the answer. "
        "Call read_note with that path and line before answering."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Words to look for. Notes are ranked by how well they match.",
            }
        },
        "required": ["query"],
    }

    def __init__(self, vault: Vault):
        self.vault = vault

    def execute(self, query: str) -> str:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        hits = BM25Index(self.vault).search(query)
        return "\n\n".join(
            "\n".join(
                [
                    f"path: {hit.path}",
                    f"title: {hit.title}",
                    f"line: {hit.line}",
                    f"snippet: {hit.snippet}",
                ]
            )
            for hit in hits
        )


def _page(note: Note, offset: int, limit: int, tool_name: str) -> str:
    offset = _line_count(offset, "offset")
    limit = _line_count(limit, "limit")
    if offset < 1:
        raise ValueError("offset must be at least 1")
    if limit < 1 or limit > _PAGE_LINES:
        raise ValueError(f"limit must be from 1 to {_PAGE_LINES}")
    lines = note.content.splitlines()
    if not lines and offset == 1:
        return f"path: {note.path}\ntitle: {note.title}\nlines: 0 of 0\n"
    if offset > len(lines):
        raise ValueError(f"offset {offset} is past the end ({len(lines)} lines)")
    start = offset - 1
    end = min(start + limit, len(lines))
    body = "\n".join(lines[start:end])
    result = f"path: {note.path}\ntitle: {note.title}\nlines: {offset}-{end} of {len(lines)}\n\n{body}"
    if end < len(lines):
        result += f"\n\nPartial view. Call {tool_name} with offset {end + 1} to continue."
    return result


def _line_count(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


class InsertTextTool(Tool):
    name = "insert_text"
    description = (
        "Insert text into one note before a 1-based line. "
        "Find that line with read_note, not read_file. "
        "The user confirms before the file changes."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path of the note relative to the vault root.",
            },
            "line": {
                "type": "integer",
                "description": "1-based line where the text will start. The existing line shifts down.",
            },
            "text": {
                "type": "string",
                "description": "Markdown to insert. Line breaks are kept.",
            },
        },
        "required": ["path", "line", "text"],
    }

    needs_approval = True

    def __init__(self, vault: Vault):
        self.vault = vault
        self._expected: dict[tuple, str] = {}

    def preview(self, path: str, line: int, text: str) -> str:
        preview, _apply, digest = self._plan(path, line, text)
        self._expected[(path, line, text)] = digest
        return preview

    def execute(self, path: str, line: int, text: str) -> str:
        _require_same(self.vault, path, self._expected.pop((path, line, text), None))
        return self._plan(path, line, text)[1]()

    def _plan(self, path: str, line: int, text: str) -> tuple[str, Callable[[], str], str]:
        line = _line_count(line, "line")
        if not isinstance(text, str) or text == "":
            raise ValueError("text must be a non-empty string")
        note = self.vault.read_note(path)
        lines = note.content.splitlines()
        if line < 1 or line > len(lines) + 1:
            count = len(lines)
            span = "1 line" if count == 1 else f"{count} lines"
            raise ValueError(f"line {line} is outside the note ({span})")
        inserted = _inserted_lines(text)
        preview = _preview(
            note.path,
            f"insert before line {line}",
            lines,
            line - 1,
            [f"+ {piece}" for piece in inserted],
            line - 1,
        )

        def apply() -> str:
            _save(self.vault, path, note.content, lines[: line - 1] + inserted + lines[line - 1 :])
            count = len(inserted)
            span = "1 line" if count == 1 else f"{count} lines"
            return f"path: {note.path}\ninserted {span} at line {line}"

        return preview, apply, _digest(note.content)


class DeleteLinesTool(Tool):
    name = "delete_lines"
    description = (
        "Delete a run of lines from one note, starting at a 1-based line. "
        "Find that line with read_note, not read_file. "
        "The user confirms before the file changes."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path of the note relative to the vault root.",
            },
            "line": {
                "type": "integer",
                "description": "1-based file line from read_note. Blank lines count. The text to delete must be on this line.",
            },
            "count": {
                "type": "integer",
                "description": "Number of lines to delete, at least 1.",
            },
        },
        "required": ["path", "line", "count"],
    }

    needs_approval = True

    def __init__(self, vault: Vault):
        self.vault = vault
        self._expected: dict[tuple, str] = {}

    def preview(self, path: str, line: int, count: int) -> str:
        preview, _apply, digest = self._plan(path, line, count)
        self._expected[(path, line, count)] = digest
        return preview

    def execute(self, path: str, line: int, count: int) -> str:
        _require_same(self.vault, path, self._expected.pop((path, line, count), None))
        return self._plan(path, line, count)[1]()

    def _plan(self, path: str, line: int, count: int) -> tuple[str, Callable[[], str], str]:
        line = _line_count(line, "line")
        count = _line_count(count, "count")
        if count < 1:
            raise ValueError("count must be at least 1")
        note = self.vault.read_note(path)
        lines = note.content.splitlines()
        if line < 1 or line > len(lines) or line + count - 1 > len(lines):
            span = "1 line" if len(lines) == 1 else f"{len(lines)} lines"
            raise ValueError(f"line {line} count {count} is outside the note ({span})")
        span = "1 line" if count == 1 else f"{count} lines"
        preview = _preview(
            note.path,
            f"delete {span} at line {line}",
            lines,
            line - 1,
            [f"- {lines[number - 1]}" for number in range(line, line + count)],
            line - 1 + count,
        )

        def apply() -> str:
            _save(self.vault, path, note.content, lines[: line - 1] + lines[line - 1 + count :])
            return f"path: {note.path}\ndeleted {span} at line {line}"

        return preview, apply, _digest(note.content)


class CreateNoteTool(Tool):
    name = "create_note"
    description = (
        "Create one new markdown note in the vault. "
        "The user confirms before the file is written. "
        "Refuses when the path already exists. Pick a different path; do not overwrite."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path of the new note relative to the vault root, for example Papers/ppo.md.",
            },
            "text": {
                "type": "string",
                "description": "Full markdown of the new note. Line breaks are kept.",
            },
        },
        "required": ["path", "text"],
    }

    needs_approval = True

    def __init__(self, vault: Vault):
        self.vault = vault

    def preview(self, path: str, text: str) -> str:
        return self._plan(path, text)[0]

    def execute(self, path: str, text: str) -> str:
        return self._plan(path, text)[1]()

    def _plan(self, path: str, text: str) -> tuple[str, Callable[[], str]]:
        if not isinstance(text, str) or text == "":
            raise ValueError("text must be a non-empty string")
        try:
            self.vault.read_note(path)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(
                f"{path} already exists. Call create_note with a different path. Do not overwrite."
            )
        inserted = _inserted_lines(text)
        preview = _preview(path, "create note", [], 0, [f"+ {piece}" for piece in inserted], 0)

        def apply() -> str:
            note = self.vault.create_note(path, "\n".join(inserted) + "\n")
            count = len(inserted)
            span = "1 line" if count == 1 else f"{count} lines"
            return f"path: {note.path}\ncreated {span}"

        return preview, apply


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Write one markdown file in the workspace. "
        "Use it for a summary or evidence during a long task, for example evidence/summary.md. "
        "Notes in the vault are create_note, insert_text, or delete_lines. "
        "skills/ and sessions/ stay read-only. "
        "The file is written immediately. An existing file at that path is replaced."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path relative to the workspace, for example evidence/summary.md. Not a vault note, and not under skills/ or sessions/.",
            },
            "text": {
                "type": "string",
                "description": "Full markdown to write. Line breaks are kept.",
            },
        },
        "required": ["path", "text"],
    }

    def __init__(self, workspace: Vault, scope: str | None = None):
        self.workspace = workspace
        self.scope = scope

    def preview(self, path: str, text: str) -> str:
        return self._plan(path, text)[0]

    def execute(self, path: str, text: str) -> str:
        return self._plan(path, text)[1]()

    def _plan(self, path: str, text: str) -> tuple[str, Callable[[], str]]:
        if not isinstance(text, str) or text == "":
            raise ValueError("text must be a non-empty string")
        _writable(path)
        if self.scope is not None and not _inside(path, self.scope):
            raise ValueError(f"{path} is outside the subtask scope {self.scope}")
        inserted = _inserted_lines(text)
        content = "\n".join(inserted) + "\n"
        try:
            current = self.workspace.read_note(path)
        except FileNotFoundError:
            current = None
        header = "replace file" if current is not None else "create file"
        preview = _preview(path, header, [], 0, [f"+ {piece}" for piece in inserted], 0)

        def apply() -> str:
            if current is None:
                note = self.workspace.create_note(path, content)
                verb = "created"
            else:
                note = self.workspace.update_note(path, content)
                verb = "replaced"
            count = len(inserted)
            span = "1 line" if count == 1 else f"{count} lines"
            return f"path: {note.path}\n{verb} {span}"

        return preview, apply


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Read one markdown file in the workspace, starting at offset. "
        "Skills such as skills/research.md, archived tool results under sessions/.../tools/, "
        "and files written with write_file. "
        "Do not use this for a notes-vault path; those are read_note. PDFs in the vault are read_pdf. "
        f"Returns at most {_PAGE_LINES} lines. "
        "If the result says the file continues, call again with a later offset."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path relative to the workspace, for example skills/research.md. A vault note such as Other/bench-pad.md is read_note.",
            },
            "offset": {
                "type": "integer",
                "description": "1-based line to start from. Defaults to 1.",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum number of lines to return. Defaults to {_PAGE_LINES}.",
            },
        },
        "required": ["path"],
    }

    def __init__(self, workspace: Vault):
        self.workspace = workspace

    def execute(self, path: str, offset: int = 1, limit: int = _PAGE_LINES) -> str:
        try:
            note = self.workspace.read_note(path)
        except FileNotFoundError:
            raise ValueError(
                f"{path} does not exist. "
                "If this is a vault note, use read_note. "
                "A workspace file that is not written yet is created with write_file."
            )
        return _page(note, offset, limit, "read_file")

    def revealed(self, arguments: dict, result: str) -> list[str]:
        path = arguments.get("path")
        if not isinstance(path, str) or Path(path).parent.as_posix() != "skills":
            return []
        return declared_tools(result)


class ReadPdfTool(Tool):
    name = "read_pdf"
    deferred = True
    description = (
        "Read text from one PDF in the vault, starting at a 1-based page. "
        f"Returns at most {_PDF_PAGES} pages. "
        "If the result says the file continues, call again with a later offset."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path of the PDF relative to the vault root, for example Papers/ppo.pdf.",
            },
            "offset": {
                "type": "integer",
                "description": "1-based page to start from. Defaults to 1.",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum number of pages to return. Defaults to 1, at most {_PDF_PAGES}.",
            },
        },
        "required": ["path"],
    }

    def __init__(self, vault: Vault):
        self.vault = vault

    def execute(self, path: str, offset: int = 1, limit: int = 1) -> str:
        offset = _line_count(offset, "offset")
        limit = _line_count(limit, "limit")
        if offset < 1:
            raise ValueError("offset must be at least 1")
        if limit < 1 or limit > _PDF_PAGES:
            raise ValueError(f"limit must be from 1 to {_PDF_PAGES}")
        file = _pdf_file(self.vault, path)
        shown = file.relative_to(self.vault.root).as_posix()
        reader = PdfReader(file)
        if reader.is_encrypted:
            raise ValueError("pdf is encrypted")
        total = len(reader.pages)
        if offset > total:
            span = "1 page" if total == 1 else f"{total} pages"
            raise ValueError(f"offset {offset} is past the end ({span})")
        start = offset - 1
        end = min(start + limit, total)
        chunks = [_page_text(reader.pages[number], number + 1) for number in range(start, end)]
        result = f"path: {shown}\npages: {offset}-{end} of {total}\n\n" + "\n\n".join(chunks)
        if end < total:
            result += (
                f"\n\nPartial view. Call read_pdf with offset {end + 1} and limit 4 to continue."
            )
        return result


class ToolDescribeTool(Tool):
    name = "tool_describe"
    description = (
        "Load one deferred tool so its schema is available on the next step. "
        "Pass a name from the system message."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Deferred tool to load, for example read_pdf.",
            }
        },
        "required": ["name"],
    }

    def __init__(self, names: list[str]):
        self._names = set(names)

    def execute(self, name: str) -> str:
        if not isinstance(name, str) or name not in self._names:
            raise ValueError(f"unknown deferred tool: {name}")
        return f"{name} is available on the next step"

    def revealed(self, arguments: dict, result: str) -> list[str]:
        name = arguments.get("name")
        if isinstance(name, str) and name in self._names:
            return [name]
        return []


def read_tools(
    vault: Vault,
    workspace: Vault | None = None,
    subtask: object | None = None,
) -> ToolRegistry:
    tools: list[Tool] = [
        ListNotesTool(vault),
        GlobTool(vault),
        ReadNoteTool(vault),
        SearchNotesTool(vault),
        NoteLinksTool(vault),
        InsertTextTool(vault),
        DeleteLinesTool(vault),
        CreateNoteTool(vault),
        ReadPdfTool(vault),
    ]
    if workspace is not None:
        tools.append(WriteFileTool(workspace))
        tools.append(ReadFileTool(workspace))
        if subtask is not None:
            from tools.subtask import RunSubtaskTool

            tools.append(RunSubtaskTool(vault, workspace, subtask))
    deferred = [tool.name for tool in tools if tool.deferred]
    tools.append(ToolDescribeTool(deferred))
    return ToolRegistry(tools)


def subtask_tools(vault: Vault, workspace: Vault, scope: str) -> ToolRegistry:
    """Read tools plus a write_file limited to `scope`. No vault edits, no nested subtask."""
    tools: list[Tool] = [
        ListNotesTool(vault),
        GlobTool(vault),
        ReadNoteTool(vault),
        SearchNotesTool(vault),
        NoteLinksTool(vault),
        ReadPdfTool(vault),
        WriteFileTool(workspace, scope=scope),
        ReadFileTool(workspace),
    ]
    deferred = [tool.name for tool in tools if tool.deferred]
    tools.append(ToolDescribeTool(deferred))
    return ToolRegistry(tools)


def _inside(path: str, scope: str) -> bool:
    relative = Path(path.replace("\\", "/")).as_posix().strip("/")
    root = Path(scope.replace("\\", "/")).as_posix().strip("/")
    return relative == root or relative.startswith(root + "/")


def _writable(path: str) -> None:
    relative = Path(path.replace("\\", "/"))
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"path must stay inside the workspace: {path}")
    if relative.parts[0].casefold() in {"skills", "sessions"}:
        raise ValueError(
            f"{path} is reserved. write_file stores summaries and evidence, not skills or archived tool results."
        )


def _glob(vault: Vault, pattern: str) -> list[str]:
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("pattern must be a non-empty string")
    relative = Path(pattern)
    if relative.is_absolute() or any(part == ".." for part in relative.parts):
        raise ValueError(f"pattern must stay inside the vault: {pattern}")
    try:
        matches = vault.root.glob(pattern)
    except (ValueError, NotImplementedError) as exc:
        raise ValueError(f"invalid glob pattern: {pattern}") from exc
    found: list[str] = []
    for path in matches:
        if not path.is_file():
            continue
        full = path.resolve()
        if not full.is_relative_to(vault.root) or _is_hidden(full, vault.root):
            continue
        found.append(full.relative_to(vault.root).as_posix())
    return sorted(found)


def _pdf_file(vault: Vault, path: str) -> Path:
    relative = Path(path)
    if relative.is_absolute():
        raise ValueError(f"path must stay inside the vault: {path}")
    full = (vault.root / relative).resolve()
    if not full.is_relative_to(vault.root):
        raise ValueError(f"path must stay inside the vault: {path}")
    if full.suffix.lower() != ".pdf":
        raise ValueError(f"not a pdf: {path}")
    if any(part.startswith(".") or part == "__pycache__" for part in full.relative_to(vault.root).parts):
        raise ValueError(f"path must stay inside the vault: {path}")
    if not full.is_file():
        raise FileNotFoundError(path)
    return full


def _page_text(page, number: int) -> str:
    text = (page.extract_text() or "").strip()
    return f"page {number}\n{text or '(no extractable text)'}"


def _inserted_lines(text: str) -> list[str]:
    if text.endswith("\n"):
        text = text[:-1]
    return text.split("\n")


def _preview(
    path: str,
    header: str,
    lines: list[str],
    index: int,
    marked: list[str],
    resume: int,
) -> str:
    before_from = max(0, index - _PREVIEW_LINES)
    shown = [f"{number}| {lines[number - 1]}" for number in range(before_from + 1, index + 1)]
    shown.extend(marked)
    after_until = min(len(lines), resume + _PREVIEW_LINES)
    shown.extend(f"{number}| {lines[number - 1]}" for number in range(resume + 1, after_until + 1))
    return f"path: {path}\n{header}:\n\n" + "\n".join(shown)


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _require_same(vault: Vault, path: str, expected: str | None) -> None:
    if expected is None:
        return
    current = _digest(vault.read_note(path).content)
    if current != expected:
        raise ValueError(
            f"{path} changed after the preview. The edit was not applied. "
            "Do not retry this edit. Tell the user the note changed."
        )


def _save(vault: Vault, path: str, original: str, updated: list[str]) -> None:
    if not updated:
        content = ""
    else:
        content = "\n".join(updated)
        if original.endswith("\n") or original == "":
            content += "\n"
    vault.update_note(path, content)

