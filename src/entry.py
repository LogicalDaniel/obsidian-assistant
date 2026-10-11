"""The process entry.

One process builds the agent, then accepts questions until a blank line or
``quit``. Each question is its own run. A one-shot script uses the same agent.
"""

from __future__ import annotations

import getpass
import sys
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path

from agent.agent import Agent, AgentState
from agent.openai_model import OpenAIModel, api_key_from_env, save_api_key
from config import assistant_dir, load_settings, load_vault, save_vault
from observe import record
from skills.skill import ensure_default_skills, load_skills
from tools.subtask import SubtaskHost
from tools.vault_tools import read_tools
from vault.vault import Vault

def build_agent(vault: str | Path | None = None) -> Agent:
    """Build an agent over `vault`. The default is the notes vault chosen last time."""
    root = Path(vault) if vault is not None else load_vault()
    if root is None or not root.is_dir():
        raise FileNotFoundError("choose a notes vault before starting")
    workspace_path = assistant_dir(root)
    workspace_path.mkdir(parents=True, exist_ok=True)
    workspace = Vault(workspace_path)
    ensure_default_skills(workspace)
    host = SubtaskHost()
    settings = load_settings()
    agent = Agent(
        OpenAIModel(),
        read_tools(Vault(root), workspace, subtask=host),
        skills=load_skills(workspace),
        max_steps=settings.max_steps,
        subtask_steps=settings.subtask_steps,
    )
    host.agent = agent
    return agent


def pick_directory(title: str = "选择笔记库") -> Path | None:
    """Open the system folder dialog. Cancel, or a missing dialog, returns None."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None
    window = tk.Tk()
    window.withdraw()
    try:
        window.attributes("-topmost", True)
        chosen = filedialog.askdirectory(title=title, mustexist=True)
    finally:
        window.destroy()
    if not chosen:
        return None
    path = Path(chosen)
    return path if path.is_dir() else None


def choose_vault(argv: list[str] | None = None) -> Path:
    """Use the remembered vault, or ask for one. ``--vault`` asks again."""
    force = "--vault" in (sys.argv if argv is None else argv)
    current = None if force else load_vault()
    if current is not None:
        return current
    print("选择笔记库文件夹。", flush=True)
    chosen = pick_directory()
    if chosen is None:
        typed = input("笔记库路径: ").strip().strip('"')
        chosen = Path(typed) if typed else None
    if chosen is None or not chosen.is_dir():
        raise SystemExit("没有选择笔记库")
    return save_vault(chosen)


def take_question(line: str) -> str | None:
    """Return the question, or None when the line ends the loop."""
    question = line.strip()
    if question == "" or question.casefold() == "quit":
        return None
    return question


def iter_turns(agent: Agent, lines: Iterable[str], decide: Callable[[str], bool] | None = None):
    """Run each question. A write the agent stops on is decided by `decide(preview)`."""
    decide = decide or _ask
    for line in lines:
        question = take_question(line)
        if question is None:
            break
        state = agent.run(question)
        while state.waiting is not None:
            _call, preview = agent.waiting(state.context.messages)
            state = agent.resume(
                state.context.messages,
                decide(preview),
                state.prompt_tokens,
                state.input_tokens,
                state.output_tokens,
                state.cached_tokens,
            )
        yield question, state


def show(question: str, state: AgentState) -> None:
    trace = state.trace
    assert trace is not None
    print(f"question: {question}\n")
    for message in trace.messages:
        if message["role"] == "assistant" and message.get("tool_calls"):
            for call in message["tool_calls"]:
                print(f"tool: {call['name']} {call['arguments']}")
        elif message["role"] == "tool":
            print(f"  -> {_preview(message['content'])}")
    print(f"\nanswer ({trace.steps} steps):\n{trace.answer}")


def repl() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ensure_api_key()
    vault = choose_vault()
    print(f"笔记库: {vault}", flush=True)
    agent = build_agent(vault)
    session_id = uuid.uuid4().hex
    announced = False
    for question, state in iter_turns(agent, _prompt_lines()):
        show(question, state)
        if _record(question, state, session_id, agent) and not announced:
            print(f"langfuse session: {session_id}")
            announced = True
        print()


def publish(question: str, state: AgentState, session_id: str, agent: Agent) -> None:
    show(question, state)
    if _record(question, state, session_id, agent):
        print(f"\nlangfuse session: {session_id}")


def _record(question: str, state: AgentState, session_id: str, agent: Agent) -> bool:
    trace = state.trace
    if trace is None:
        return False
    model = getattr(agent.model, "model", None)
    return record(question, trace, session_id, model if isinstance(model, str) else None)


def ensure_api_key() -> None:
    """Ask on the terminal when the key is missing, and store it in ``.env``."""
    if api_key_from_env():
        return
    print("还没有 OPENAI_API_KEY。输入后写入项目根目录的 .env。", flush=True)
    try:
        key = getpass.getpass("OPENAI_API_KEY: ")
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(1) from None
    if not key.strip():
        raise SystemExit("没有填写 OPENAI_API_KEY")
    save_api_key(key)


def _ask(preview: str) -> bool:
    print(preview, flush=True)
    try:
        return input("确认写入？[yes/no]: ").strip().casefold() == "yes"
    except EOFError:
        return False


def _prompt_lines():
    while True:
        try:
            yield input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return


def _preview(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."
