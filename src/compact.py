"""Shrink a session before the next run, and inside a run before the next call.

`compact` runs before `Agent.run`. Below `light` tokens the turns stay as they
are. From `light` upward, tool results from earlier questions are written under
the session directory and replaced with a short stub. From `heavy` upward, and
only if that is still not enough, tool results from the latest question are
truncated the same way.

`compact_step` uses the same files and stubs. It runs before a later model call
in the same question. From `light` upward it spills tool results before the
latest tool batch. From `heavy` upward it spills that batch too.
"""

from __future__ import annotations

from pathlib import Path

from config import DEFAULT_COMPACT_HEAVY, DEFAULT_COMPACT_LIGHT

_PREVIEW = 200
_MARKER = "完整结果："


class Compactor:
    def __init__(
        self,
        directory: str | Path,
        light: int = DEFAULT_COMPACT_LIGHT,
        heavy: int = DEFAULT_COMPACT_HEAVY,
    ):
        self.root = Path(directory)
        self.light = light
        self.heavy = heavy

    def compact(self, session_id: str, turns: list[dict], prompt_tokens: int) -> list[dict]:
        if prompt_tokens < self.light:
            return turns
        spilled = self._spill(session_id, turns, _last_user(turns))
        if not _still_heavy(turns, spilled, prompt_tokens, self.heavy):
            return spilled
        return self._spill(session_id, spilled, len(spilled))

    def compact_step(
        self,
        session_id: str,
        turns: list[dict],
        prompt_tokens: int,
        prompt_chars: int = 0,
    ) -> list[dict]:
        estimated = _estimate(turns, prompt_tokens, prompt_chars)
        if estimated < self.light:
            return turns
        spilled = self._spill(session_id, turns, _latest_batch(turns))
        if not _still_heavy(turns, spilled, estimated, self.heavy):
            return spilled
        return self._spill(session_id, spilled, len(spilled))

    def _spill(self, session_id: str, turns: list[dict], before: int | None) -> list[dict]:
        if before is None:
            return turns
        spilled: list[dict] = []
        changed = False
        for index, message in enumerate(turns):
            if index < before and _can_spill(message):
                spilled.append(self._spill_one(session_id, message))
                changed = True
            else:
                spilled.append(message)
        return spilled if changed else turns

    def _spill_one(self, session_id: str, message: dict) -> dict:
        call_id = _file_name(str(message.get("tool_call_id") or "tool"))
        directory = self.root / session_id / "tools"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{call_id}.md"
        content = message.get("content") or ""
        path.write_text(content, encoding="utf-8")
        stored = dict(message)
        stored["content"] = _stub(content, f"sessions/{session_id}/tools/{call_id}.md")
        return stored


def _still_heavy(before: list[dict], after: list[dict], prompt_tokens: int, heavy: int) -> bool:
    if prompt_tokens < heavy:
        return False
    before_chars = _chars(before)
    if before_chars == 0:
        return True
    return prompt_tokens * _chars(after) // before_chars >= heavy


def _estimate(turns: list[dict], prompt_tokens: int, prompt_chars: int) -> int:
    if prompt_chars <= 0:
        return prompt_tokens
    return prompt_tokens * _chars(turns) // prompt_chars


def _last_user(turns: list[dict]) -> int | None:
    for index in range(len(turns) - 1, -1, -1):
        if turns[index].get("role") == "user":
            return index
    return None


def _latest_batch(turns: list[dict]) -> int | None:
    for index in range(len(turns) - 1, -1, -1):
        if turns[index].get("role") == "assistant" and turns[index].get("tool_calls"):
            return index
    return _last_user(turns)


def _can_spill(message: dict) -> bool:
    if message.get("role") != "tool":
        return False
    content = message.get("content") or ""
    return len(content) > _PREVIEW and _MARKER not in content


def _stub(content: str, path: str) -> str:
    head = content[:_PREVIEW]
    if len(content) > _PREVIEW:
        head += "…"
    return f"{head}\n{_MARKER}{path}"


def _chars(turns: list[dict]) -> int:
    return sum(len(message.get("content") or "") for message in turns)


def _file_name(call_id: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in call_id)
    return safe or "tool"
