"""A minimal tool-calling loop.

`Model` is the client interface. `OpenAIModel` performs the API call. The loop
only distinguishes tool calls from a final answer. `Context` keeps the record.
Each model call receives the assembled system prompt, then `Context.prompt()`.

A tool marked `needs_approval` is not run inside the loop. The run stops with
that call recorded but unanswered, so the record itself shows what is waiting.
`resume` answers it with the user's decision and continues the same run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from agent.context import Context
from agent.prompt import system_prompt
from agent.trace import Trace
from compact import Compactor
from config import DEFAULT_MAX_STEPS, DEFAULT_SUBTASK_STEPS
from skills.skill import Skill
from tools.registry import ToolRegistry

DECLINED = "用户没有确认"


@dataclass
class ToolCall:
    name: str
    arguments: dict = field(default_factory=dict)
    id: str = ""


@dataclass
class ModelUsage:
    """Token counts from one model call. `cached_tokens` is the cached part of the prompt."""

    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int


@dataclass
class ModelResponse:
    """One model turn. A tool call is executed. Otherwise `answer` ends the run."""

    tool_calls: list[ToolCall] | None = None
    answer: str | None = None
    usage: ModelUsage | None = None


@dataclass
class AgentState:
    context: Context
    step: int = 0
    finished: bool = False
    answer: str | None = None
    trace: Trace | None = None
    visible: set[str] = field(default_factory=set)
    waiting: dict | None = None
    prompt_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    spill_id: str | None = None
    prompt_chars: int = 0


class Model:
    """Stub. Subclasses turn messages and tool schemas into a `ModelResponse`."""

    def generate(self, messages: list[dict], tools: list[dict]) -> ModelResponse:
        raise NotImplementedError


class Agent:
    def __init__(
        self,
        model: Model,
        tools: ToolRegistry,
        skills: list[Skill] | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        subtask_steps: int = DEFAULT_SUBTASK_STEPS,
        compactor: Compactor | None = None,
    ):
        self.model = model
        self.tools = tools
        self.skills = skills or []
        self.max_steps = max_steps
        self.subtask_steps = subtask_steps
        self.compactor = compactor
        # Set for the duration of run/resume. A subtask reads it to report its own tools.
        self.on_tool: Callable[[dict, str], None] | None = None

    def run(
        self,
        query: str,
        history: list[dict] | None = None,
        spill_id: str | None = None,
        on_tool: Callable[[dict, str], None] | None = None,
    ) -> AgentState:
        if _unanswered(history or []):
            raise ValueError("a tool call is waiting for approval")
        state = self._open(history)
        state.spill_id = spill_id
        state.context.ask(query)
        return self._run_notified(state, on_tool)

    def resume(
        self,
        history: list[dict],
        approved: bool,
        prompt_tokens: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        spill_id: str | None = None,
        on_tool: Callable[[dict, str], None] | None = None,
    ) -> AgentState:
        """Answer the waiting call with the user's decision, then continue the run."""
        calls = _unanswered(history)
        if not calls:
            raise ValueError("no tool call is waiting")
        state = self._open(history)
        state.step = _steps_since_question(history)
        state.prompt_tokens = prompt_tokens
        state.input_tokens = input_tokens
        state.output_tokens = output_tokens
        state.cached_tokens = cached_tokens
        state.spill_id = spill_id
        previous = self.on_tool
        self.on_tool = on_tool
        try:
            first, rest = calls[0], calls[1:]
            result = self.tools.call(first["name"], first.get("arguments")) if approved else DECLINED
            self._add_result(state, first, result)
            self._run_calls(state, rest)
            self._loop(state)
            return self._close(state)
        finally:
            self.on_tool = previous

    def _run_notified(self, state: AgentState, on_tool: Callable[[dict, str], None] | None) -> AgentState:
        """Run the loop, notifying `on_tool` as each tool result is recorded."""
        previous = self.on_tool
        self.on_tool = on_tool
        try:
            self._loop(state)
            return self._close(state)
        finally:
            self.on_tool = previous

    def waiting(self, history: list[dict]) -> tuple[dict, str] | None:
        """The call waiting for approval and its preview."""
        calls = _unanswered(history)
        if not calls:
            return None
        call = calls[0]
        return call, self.tools.preview(call["name"], call.get("arguments"))

    def _open(self, history: list[dict] | None) -> AgentState:
        state = AgentState(context=Context(history))
        state.visible.update(self._visible_in(state.context.messages))
        return state

    def _loop(self, state: AgentState) -> None:
        while not state.finished and state.waiting is None and state.step < self.max_steps:
            self._compact_step(state)
            response = self.model.generate(self._messages(state), self.tools.schemas(state.visible))
            if response.usage is not None:
                state.prompt_tokens = response.usage.prompt_tokens
                state.input_tokens += response.usage.prompt_tokens
                state.output_tokens += response.usage.completion_tokens
                state.cached_tokens += response.usage.cached_tokens
            state.prompt_chars = sum(
                len(message.get("content") or "") for message in state.context.messages
            )
            state.step += 1
            if response.tool_calls is not None:
                self._call_tools(state, response.tool_calls)
            else:
                self._finish(state, response.answer or "")

    def _compact_step(self, state: AgentState) -> None:
        if self.compactor is None or not state.spill_id:
            return
        state.context.messages[:] = self.compactor.compact_step(
            state.spill_id,
            state.context.messages,
            state.prompt_tokens,
            state.prompt_chars,
        )

    def _messages(self, state: AgentState) -> list[dict]:
        request = state.context.prompt()
        listing = system_prompt(self.skills, self.tools)
        if listing:
            request.insert(0, {"role": "system", "content": listing})
        return request

    def _close(self, state: AgentState) -> AgentState:
        if state.waiting is None and not state.finished:
            self._finish(state, "stopped: max steps reached")
        state.trace = Trace(
            state.context.messages,
            state.answer or "",
            state.step,
            state.prompt_tokens,
            state.input_tokens,
            state.output_tokens,
            state.cached_tokens,
        )
        return state

    def _call_tools(self, state: AgentState, calls: list[ToolCall]) -> None:
        recorded = [
            {"id": call.id or f"call_{state.step}_{index}", "name": call.name, "arguments": call.arguments}
            for index, call in enumerate(calls, start=1)
        ]
        state.context.add_tool_calls(recorded)
        self._run_calls(state, recorded)

    def _run_calls(self, state: AgentState, calls: list[dict]) -> None:
        """Run calls in order. Stop at the first one that needs approval and would succeed."""
        for call in calls:
            name, arguments = call["name"], call.get("arguments")
            if self.tools.needs_approval(name):
                preview = self.tools.preview(name, arguments)
                if not preview.startswith("error:"):
                    state.waiting = call
                    return
                self._add_result(state, call, preview)
                continue
            self._add_result(state, call, self.tools.call(name, arguments))

    def _add_result(self, state: AgentState, call: dict, result: str) -> None:
        missing = [name for name in self._revealed(call, result) if not self._allow(state.visible, name)]
        if missing:
            result += "\n\nunknown tool: " + " ".join(missing)
        state.context.add_tool_result(call, result)
        # Fired after the result is on the record. Absent means the caller only wants the final trace.
        if self.on_tool is not None:
            self.on_tool(call, result)

    def _visible_in(self, messages: list[dict]) -> set[str]:
        visible: set[str] = set()
        calls: list[dict] = []
        for message in messages:
            if message.get("role") == "assistant" and message.get("tool_calls"):
                calls = list(message["tool_calls"])
                continue
            if message.get("role") != "tool" or not calls:
                continue
            call = calls.pop(0)
            for name in self._revealed(call, message.get("content") or ""):
                self._allow(visible, name)
        return visible

    def _revealed(self, call: dict, result: str) -> list[str]:
        if result.startswith("error:"):
            return []
        tool = self.tools.get(call.get("name") or "")
        if tool is None:
            return []
        return tool.revealed(call.get("arguments") or {}, result)

    def _allow(self, visible: set[str], name: str) -> bool:
        try:
            self.tools.tool_describe(name)
        except KeyError:
            return False
        visible.add(name)
        return True

    def _finish(self, state: AgentState, answer: str) -> None:
        state.context.add_answer(answer)
        state.answer = answer
        state.finished = True


def _unanswered(messages: list[dict]) -> list[dict]:
    """Calls in the last tool batch that have no result yet, in call order."""
    answered: set[str] = set()
    for message in reversed(messages):
        if message.get("role") == "tool":
            answered.add(message.get("tool_call_id") or "")
            continue
        if message.get("role") == "assistant" and message.get("tool_calls"):
            return [call for call in message["tool_calls"] if call.get("id") not in answered]
        return []
    return []


def _steps_since_question(messages: list[dict]) -> int:
    steps = 0
    for message in reversed(messages):
        if message.get("role") == "user":
            break
        if message.get("role") == "assistant":
            steps += 1
    return steps
