"""A skill catalog entry. The markdown file in the workspace is the source of truth.

A skill opens with a name and description, then the instructions:

    ---
    name: research
    description: When the question should be answered from the notes.
    ---

    Instructions follow.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vault.vault import Vault

_SKILLS = "skills"
_DEFAULTS = Path(__file__).resolve().parent / "default"


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: str


def ensure_default_skills(workspace: Vault) -> list[str]:
    """Copy packaged skills into ``skills/`` when that file is not there yet.

    ``src/skills/default`` ships with the repo. The workspace copy is what the
    agent reads, so a file that is already present is left unchanged.
    """
    if not _DEFAULTS.is_dir():
        raise FileNotFoundError(f"packaged skills are not in {_DEFAULTS}")
    present = set(workspace.list_notes())
    copied: list[str] = []
    for source in sorted(_DEFAULTS.glob("*.md")):
        path = f"{_SKILLS}/{source.name}"
        if path in present:
            continue
        workspace.create_note(path, source.read_text(encoding="utf-8"))
        copied.append(path)
    return copied


def load_skills(workspace: Vault) -> list[Skill]:
    """Load markdown skills from ``skills/``. The catalog uses only the header."""
    skills = []
    for path in workspace.list_notes():
        if Path(path).parent.as_posix() != _SKILLS:
            continue
        note = workspace.read_note(path)
        name, description = _header(note.content, note.path)
        skills.append(Skill(name, description, note.path))
    return skills


def catalog(skills: list[Skill]) -> str:
    if not skills:
        return ""
    lines = ["可用技能。描述符合当前问题时，先用 read_file 读取对应 file，读到之前不要回答，也不要调用别的工具。"]
    for skill in skills:
        lines.append(f"- name: {skill.name}")
        lines.append(f"  description: {skill.description}")
        lines.append(f"  file: {skill.path}")
    return "\n".join(lines)


def declared_tools(content: str) -> list[str]:
    """Tool names from a skill header. The header may sit under a read_file page."""
    lines = content.splitlines()
    start = next((index for index, line in enumerate(lines) if line.strip() == "---"), None)
    if start is None:
        return []
    fields: dict[str, str] = {}
    closed = False
    for line in lines[start + 1 :]:
        if line.strip() == "---":
            closed = True
            break
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    if not closed:
        return []
    return fields.get("tools", "").split()


def _header(content: str, path: str) -> tuple[str, str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path}: a skill must open with name and description")
    fields: dict[str, str] = {}
    closed = False
    for line in lines[1:]:
        if line.strip() == "---":
            closed = True
            break
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    if not closed:
        raise ValueError(f"{path}: the skill header is not closed")
    name = fields.get("name", "")
    description = fields.get("description", "")
    if not name or not description:
        raise ValueError(f"{path}: the skill header needs name and description")
    return name, description
