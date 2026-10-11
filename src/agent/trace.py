"""The record of one finished run.

The loop stays in `Agent`. A later UI or evaluation reads this record instead of
the live state.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Trace:
    messages: list[dict]
    answer: str
    steps: int
    prompt_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
