"""The record of one run.

The record is prior turns, then this run's question if there is one. A run
that resumes a paused tool call starts from the saved turns alone. The loop
appends tool calls, tool results, and the final answer. `prompt` copies that
record. The system prompt is assembled outside the record.
"""

from __future__ import annotations


class Context:
    def __init__(self, history: list[dict] | None = None):
        self.messages: list[dict] = [dict(message) for message in history or []]

    def ask(self, query: str) -> None:
        self.messages.append({"role": "user", "content": query})

    def add_tool_calls(self, calls: list[dict]) -> None:
        self.messages.append({"role": "assistant", "tool_calls": calls})

    def add_tool_result(self, call: dict, result: str) -> None:
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "name": call["name"],
                "content": result,
            }
        )

    def add_answer(self, answer: str) -> None:
        self.messages.append({"role": "assistant", "content": answer})

    def prompt(self) -> list[dict]:
        """The messages for one model call. Editing the copy leaves the record intact."""
        return [dict(message) for message in self.messages]
