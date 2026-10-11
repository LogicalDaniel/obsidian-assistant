"""A fresh context for one piece of work.

The parent keeps its own messages. The subtask starts empty, writes only inside
the directory it was given, and leaves a progress section next to that directory.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from agent.agent import Agent
from tools.registry import Tool
from vault.vault import Vault

_ANSWER_LIMIT = 800


class SubtaskHost:
    """Filled with the parent agent after the registry has been built."""

    def __init__(self) -> None:
        self.agent: Agent | None = None


class RunSubtaskTool(Tool):
    name = "run_subtask"
    description = (
        "Run one task in a fresh context. The parent conversation is not visible there. "
        "Pass a workspace directory as scope. write_file inside the task can only use that directory. "
        "The result is a status, the files in that directory, and a short answer. "
        "A progress section is written beside the directory."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "What the fresh context should do.",
            },
            "scope": {
                "type": "string",
                "description": "Workspace directory this task may write, for example jobs/reading-1.",
            },
        },
        "required": ["task", "scope"],
    }

    def __init__(self, vault: Vault, workspace: Vault, host: SubtaskHost):
        self.vault = vault
        self.workspace = workspace
        self.host = host

    def execute(self, task: str, scope: str) -> str:
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")
        from tools.vault_tools import _writable, subtask_tools

        _writable(scope)
        parent = self.host.agent
        if parent is None:
            raise RuntimeError("run_subtask is not attached to an agent")
        child = Agent(
            parent.model,
            subtask_tools(self.vault, self.workspace, scope),
            skills=[],
            max_steps=parent.subtask_steps,
            compactor=parent.compactor,
        )
        spill = uuid.uuid4().hex
        try:
            # Child tools share the parent's notice, marked one level down for the live list.
            state = child.run(task, spill_id=spill, on_tool=_deeper(parent.on_tool))
        except Exception as exc:
            status = "failed"
            answer = f"{type(exc).__name__}: {exc}"
        else:
            answer = state.answer or ""
            if state.waiting is not None or answer.startswith("stopped:"):
                status = "partial" if answer.startswith("stopped: max steps") else "failed"
            else:
                status = "ready"
        finally:
            if child.compactor is not None:
                directory = child.compactor.root / spill
                if directory.exists():
                    shutil.rmtree(directory)
        files = _markdown_under(self.workspace, scope)
        _write_progress(self.workspace, scope, status, files)
        return _receipt(status, scope, files, answer)


def _deeper(notice):
    """Return a notice that tags child tool calls as nested. None stays none."""
    if notice is None:
        return None

    def nested(call: dict, result: str) -> None:
        noted = dict(call)
        noted["depth"] = int(call.get("depth") or 0) + 1
        notice(noted, result)

    return nested


def _markdown_under(workspace: Vault, scope: str) -> list[str]:
    prefix = scope.strip("/") + "/"
    return [path for path in workspace.list_notes() if path.startswith(prefix)]


def _progress_path(scope: str) -> str:
    parent = Path(scope.replace("\\", "/")).parent.as_posix()
    if parent == ".":
        return "progress.md"
    return f"{parent}/progress.md"


def _write_progress(workspace: Vault, scope: str, status: str, files: list[str]) -> None:
    path = _progress_path(scope)
    try:
        current = workspace.read_note(path).content
    except FileNotFoundError:
        current = ""
    section = _section(scope, status, files)
    updated = _replace_section(current, scope, section)
    if current == "":
        workspace.create_note(path, updated)
    else:
        workspace.update_note(path, updated)


def _section(scope: str, status: str, files: list[str]) -> str:
    lines = [f"## {scope}", "", f"scope: {scope}", f"status: {status}", "files: " + ", ".join(files)]
    return "\n".join(lines)


def _replace_section(current: str, scope: str, section: str) -> str:
    kept: list[tuple[str, list[str]]] = []
    name: str | None = None
    body: list[str] = []
    for line in current.splitlines():
        if line.startswith("## "):
            if name is not None:
                kept.append((name, body))
            name = line[3:].strip()
            body = []
            continue
        if name is not None:
            body.append(line)
    if name is not None:
        kept.append((name, body))
    replaced = False
    blocks: list[str] = []
    for found, _lines in kept:
        if found == scope:
            blocks.append(section)
            replaced = True
        else:
            blocks.append("## " + found + ("\n" + "\n".join(_lines).strip("\n") if any(line.strip() for line in _lines) else ""))
    if not replaced:
        blocks.append(section)
    return "\n\n".join(block.strip("\n") for block in blocks if block.strip()) + "\n"


def _receipt(status: str, scope: str, files: list[str], answer: str) -> str:
    lines = [f"status: {status}", f"scope: {scope}", "files: " + ", ".join(files), "", answer[:_ANSWER_LIMIT]]
    return "\n".join(lines).rstrip() + "\n"
