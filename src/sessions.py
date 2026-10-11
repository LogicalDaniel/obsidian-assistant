"""Saved conversations for the UI.

Each session is ``<id>/session.json`` under the store directory. `create`,
`send`, and `approve` rewrite that one file. `switch` only changes which id
this process has selected. `send` compacts the saved turns, runs the agent with
them as prior context, then stores that run's trace. A run that stops on a
write keeps the unanswered call in `turns`; `waiting` reads it back and
`approve` finishes it. The skill catalog is added when prompting.
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agent.agent import Agent, AgentState
from compact import Compactor
from config import load_settings
from observe import record

_FILE = "session.json"
_TITLE = "新对话"
_TITLE_LEN = 32


@dataclass
class Session:
    id: str
    title: str
    turns: list[dict] = field(default_factory=list)
    prompt_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


class SessionStore:
    def __init__(self, directory: str | Path, agent: Agent | None = None):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.agent = agent
        settings = load_settings()
        self.compactor = Compactor(self.root, light=settings.compact_light, heavy=settings.compact_heavy)
        if agent is not None:
            agent.compactor = self.compactor
        self._sessions = _load(self.root)
        self.current_id: str | None = None

    def create(self) -> Session:
        session = Session(id=uuid.uuid4().hex, title=_TITLE)
        self._sessions.append(session)
        self.current_id = session.id
        _write(self.root, session)
        return session

    def list(self) -> list[Session]:
        return list(self._sessions)

    def current(self) -> Session | None:
        if self.current_id is None:
            return None
        return self._get(self.current_id)

    def switch(self, session_id: str) -> Session:
        session = self._get(session_id)
        self.current_id = session.id
        return session

    def send(
        self,
        session_id: str,
        question: str,
        on_tool: Callable[[dict, str], None] | None = None,
    ) -> Session:
        text = question.strip()
        if text == "":
            raise ValueError("question must be a non-empty string")
        agent = self._agent()
        session = self._get(session_id)
        if agent.waiting(session.turns) is not None:
            raise RuntimeError("a tool call is waiting for approval")
        session.turns = self.compactor.compact(session.id, session.turns, session.prompt_tokens)
        return self._save_run(session, agent.run(text, session.turns, session.id, on_tool=on_tool))

    def discard(self, session_id: str) -> None:
        """Remove one session from memory and delete its directory."""
        directory = self.root / session_id
        if directory.exists():
            shutil.rmtree(directory)
        self._sessions = [session for session in self._sessions if session.id != session_id]
        if self.current_id == session_id:
            self.current_id = None

    def waiting(self, session_id: str) -> tuple[dict, str] | None:
        """The tool call this session is waiting on, with its preview."""
        return self._agent().waiting(self._get(session_id).turns)

    def approve(
        self,
        session_id: str,
        approved: bool,
        on_tool: Callable[[dict, str], None] | None = None,
    ) -> Session:
        session = self._get(session_id)
        state = self._agent().resume(
            session.turns,
            approved,
            session.prompt_tokens,
            session.input_tokens,
            session.output_tokens,
            session.cached_tokens,
            session.id,
            on_tool=on_tool,
        )
        return self._save_run(session, state)

    def _save_run(self, session: Session, state: AgentState) -> Session:
        trace = state.trace
        if trace is None:
            raise RuntimeError("agent finished without a trace")
        session.turns = [dict(message) for message in trace.messages]
        session.prompt_tokens = trace.prompt_tokens
        session.input_tokens = trace.input_tokens
        session.output_tokens = trace.output_tokens
        session.cached_tokens = trace.cached_tokens
        if session.title == _TITLE:
            session.title = _one_line(_first_question(session.turns))
        _write(self.root, session)
        if state.waiting is None:
            model = getattr(self._agent().model, "model", None)
            record(_last_question(session.turns), trace, session.id, model if isinstance(model, str) else None)
        return session

    def _agent(self) -> Agent:
        if self.agent is None:
            raise RuntimeError("session store has no agent")
        return self.agent

    def _get(self, session_id: str) -> Session:
        for session in self._sessions:
            if session.id == session_id:
                return session
        raise KeyError(session_id)


def _one_line(text: str) -> str:
    line = text.splitlines()[0].strip()
    if len(line) <= _TITLE_LEN:
        return line
    return line[:_TITLE_LEN] + "…"


def _first_question(turns: list[dict]) -> str:
    for message in turns:
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""


def _last_question(turns: list[dict]) -> str:
    for message in reversed(turns):
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""


def _load(root: Path) -> list[Session]:
    files = [path / _FILE for path in root.iterdir() if (path / _FILE).is_file()]
    files.sort(key=lambda path: (path.stat().st_mtime, path.parent.name))
    sessions = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("id") != path.parent.name:
            continue
        sessions.append(
            Session(
                data["id"],
                data["title"],
                list(data.get("turns") or []),
                int(data.get("prompt_tokens") or 0),
                int(data.get("input_tokens") or 0),
                int(data.get("output_tokens") or 0),
                int(data.get("cached_tokens") or 0),
            )
        )
    return sessions


def _write(root: Path, session: Session) -> None:
    directory = root / session.id
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": session.id,
        "title": session.title,
        "turns": session.turns,
        "prompt_tokens": session.prompt_tokens,
        "input_tokens": session.input_tokens,
        "output_tokens": session.output_tokens,
        "cached_tokens": session.cached_tokens,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    (directory / _FILE).write_text(text, encoding="utf-8")
