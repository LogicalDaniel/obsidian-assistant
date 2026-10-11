"""Send one finished run to Langfuse.

The agent loop stays free of this. A missing key skips the send, so a run
still answers. One process shares a session id across its questions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from agent.openai_model import _load_dotenv
from agent.trace import Trace


@dataclass(frozen=True)
class _ToolStep:
    name: str
    arguments: dict
    output: str


@dataclass(frozen=True)
class _ModelStep:
    prompt: list[dict]
    output: object
    tools: list[_ToolStep]


def model_steps(messages: list[dict]) -> list[_ModelStep]:
    """Group each assistant turn with the tool results that follow it."""
    steps: list[_ModelStep] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message["role"] != "assistant":
            index += 1
            continue
        prompt = messages[:index]
        calls = message.get("tool_calls")
        if calls:
            tools: list[_ToolStep] = []
            index += 1
            for call in calls:
                output = ""
                if index < len(messages) and messages[index]["role"] == "tool":
                    output = messages[index]["content"]
                    index += 1
                tools.append(_ToolStep(call["name"], call.get("arguments") or {}, output))
            steps.append(_ModelStep(prompt, calls, tools))
            continue
        steps.append(_ModelStep(prompt, message.get("content") or "", []))
        index += 1
    return steps


def langfuse_configured() -> bool:
    _load_dotenv()
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def record(question: str, trace: Trace, session_id: str, model: str | None = None) -> bool:
    """Upload the run. Return whether it was sent."""
    if not langfuse_configured():
        return False
    try:
        _send(question, trace, session_id, model)
    except Exception as exc:
        print(f"langfuse: {exc}")
        return False
    return True


def _send(question: str, trace: Trace, session_id: str, model: str | None) -> None:
    from langfuse import get_client, propagate_attributes

    langfuse = get_client()
    with langfuse.start_as_current_observation(as_type="agent", name="run", input=question) as root:
        with propagate_attributes(session_id=session_id):
            for step in model_steps(trace.messages):
                _generation(langfuse, step, model)
        root.update(output=trace.answer)
    langfuse.flush()


def _generation(langfuse, step: _ModelStep, model: str | None) -> None:
    details = {"as_type": "generation", "name": "model", "input": step.prompt, "output": step.output}
    if model:
        details["model"] = model
    with langfuse.start_as_current_observation(**details):
        for tool in step.tools:
            with langfuse.start_as_current_observation(
                as_type="tool",
                name=tool.name,
                input=tool.arguments,
                output=tool.output,
            ):
                pass
