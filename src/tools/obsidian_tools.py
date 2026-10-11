"""Wikilink lookup over a Markdown vault.

Links are read from the files on each call. The vault does not store them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tools.registry import Tool
from vault.vault import Vault

_FENCE = re.compile(r"^(```+|~~~+)")
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_WIKILINK = re.compile(r"(?<!!)\[\[([^\]]+)\]\]")
_DIRECTIONS = ("outgoing", "backlinks", "unresolved")


@dataclass(frozen=True)
class _Link:
    raw: str
    source: str
    target: str
    heading: str


class NoteLinksTool(Tool):
    name = "note_links"
    description = (
        "List Obsidian wikilinks. direction outgoing lists [[targets]] in one note, "
        "resolved to vault paths. direction backlinks lists notes that link to that path. "
        "direction unresolved lists links whose target note does not exist; "
        "omit path to scan the whole vault. "
        "A #heading is reported when the link has one. "
        "The written alias is display text only. "
        "Embeds and links inside code are skipped. Each call reads the files again."
    )
    parameters = {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": list(_DIRECTIONS),
                "description": "outgoing, backlinks, or unresolved.",
            },
            "path": {
                "type": "string",
                "description": (
                    "Note path relative to the vault, for example RL/mcts.md. "
                    "Required for outgoing and backlinks. "
                    "For unresolved, omit it to scan every note."
                ),
            },
        },
        "required": ["direction"],
    }

    def __init__(self, vault: Vault):
        self.vault = vault

    def execute(self, direction: str, path: str | None = None) -> str:
        if direction not in _DIRECTIONS:
            raise ValueError("direction must be outgoing, backlinks, or unresolved")
        if direction != "unresolved" and not path:
            raise ValueError("path is required")
        paths, by_stem = _index(self.vault)
        focus = ""
        if path:
            focus = paths.get(self.vault.read_note(path).path.casefold(), "")
        scan_all = direction == "backlinks" or (direction == "unresolved" and not path)
        sources = list(paths.values()) if scan_all else [focus]
        found = _collect(self.vault, sources, paths, by_stem)
        if direction == "backlinks":
            chosen = [link for link in found if link.target == focus]
        elif direction == "unresolved":
            chosen = [link for link in found if link.target == ""]
        else:
            chosen = found
        return _format(focus, chosen, direction)


def _index(vault: Vault) -> tuple[dict[str, str], dict[str, list[str]]]:
    paths: dict[str, str] = {}
    by_stem: dict[str, list[str]] = {}
    for note in vault.list_notes():
        paths[note.casefold()] = note
        by_stem.setdefault(Path(note).stem.casefold(), []).append(note)
    return paths, by_stem


def _collect(
    vault: Vault,
    sources: list[str],
    paths: dict[str, str],
    by_stem: dict[str, list[str]],
) -> list[_Link]:
    found: list[_Link] = []
    for source in sources:
        note = vault.read_note(source)
        for raw in _wikilinks(note.content):
            name, heading = _parse(raw)
            if name == "" and heading == "":
                continue
            found.append(
                _Link(raw, note.path, _resolve(name, note.path, paths, by_stem), heading)
            )
    return found


def _wikilinks(content: str) -> list[str]:
    found: list[str] = []
    fenced = False
    fence = ""
    for line in content.splitlines():
        marker = _FENCE.match(line.strip())
        if marker:
            char = marker.group(1)[0]
            if not fenced:
                fenced = True
                fence = char
            elif char == fence:
                fenced = False
            continue
        if fenced:
            continue
        visible = _INLINE_CODE.sub("", line)
        found.extend(match.group(0) for match in _WIKILINK.finditer(visible))
    return found


def _parse(raw: str) -> tuple[str, str]:
    target = raw[2:-2].split("|", 1)[0].strip()
    if "#" not in target:
        return target, ""
    name, heading = target.split("#", 1)
    return name.strip(), heading.strip()


def _resolve(name: str, source: str, paths: dict[str, str], by_stem: dict[str, list[str]]) -> str:
    name = name.replace("\\", "/").strip()
    if name == "":
        return source
    exact = name if name.endswith(".md") else f"{name}.md"
    found = paths.get(exact.casefold())
    if found:
        return found
    if "/" in name:
        return ""
    stem = Path(name).stem if name.endswith(".md") else Path(name).name
    matches = by_stem.get(stem.casefold(), [])
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return "ambiguous: " + ", ".join(matches)
    return ""


def _format(path: str, links: list[_Link], direction: str) -> str:
    blocks: list[str] = []
    if path:
        blocks.append(f"path: {path}")
    for link in links:
        fields: list[str] = []
        if direction == "backlinks":
            fields.append(f"from: {link.source}")
        elif not path:
            fields.append(f"path: {link.source}")
        fields.append(f"link: {link.raw}")
        fields.append(f"target: {link.target or 'not created'}")
        if link.heading:
            fields.append(f"heading: {link.heading}")
        blocks.append("\n".join(fields))
    return "\n\n".join(blocks)
