"""Grade one benchmark answer from the trace, without calling a model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


def grade(
    task: dict,
    messages: list[dict],
    answer: str,
    before: dict[str, str | None] | None = None,
    after: dict[str, str | None] | None = None,
) -> list[Check]:
    """Check facts, reads, calls, disclosure, and optional vault file contents."""
    checks: list[Check] = []
    plain = _plain(answer or "")
    for text in task.get("answer_contains") or []:
        checks.append(Check(f"answer has {text}", _plain(text) in plain))
    alternatives = task.get("answer_any") or []
    if alternatives:
        matched = next((text for text in alternatives if _plain(text) in plain), "")
        checks.append(Check("answer has " + " or ".join(alternatives), bool(matched), matched))
    note_reads = _calls(messages, "read_note") + _calls(messages, "read_file")
    minimum = task.get("min_offset")
    for path in task.get("reads") or []:
        matched = [item for item in note_reads if item["path"] == _path(path)]
        offsets = ", ".join(str(item["offset"]) for item in matched)
        checks.append(Check(f"read {path}", bool(matched), offsets))
        if minimum is not None:
            passed = any(item["offset"] >= minimum for item in matched)
            checks.append(Check(f"read {path} from line {minimum}", passed, offsets))
    for path in task.get("file_reads") or []:
        matched = [item for item in note_reads if item["path"] == _path(path)]
        offsets = ", ".join(str(item["offset"]) for item in matched)
        checks.append(Check(f"opened {path}", bool(matched), offsets))
    pdf_reads = _calls(messages, "read_pdf")
    pdf_minimum = task.get("min_pdf_offset")
    for path in task.get("pdfs") or []:
        matched = [item for item in pdf_reads if item["path"] == _path(path)]
        offsets = ", ".join(str(item["offset"]) for item in matched)
        checks.append(Check(f"read_pdf {path}", bool(matched), offsets))
        if pdf_minimum is not None:
            passed = any(item["offset"] >= pdf_minimum for item in matched)
            checks.append(Check(f"read_pdf {path} from page {pdf_minimum}", passed, offsets))
    names = _call_names(messages)
    for name in task.get("calls") or []:
        checks.append(Check(f"called {name}", name in names))
    for name in task.get("reveals") or []:
        checks.append(Check(f"revealed {name}", _revealed(messages, name)))
    tool_text = "\n".join(
        message.get("content") or "" for message in messages if message.get("role") == "tool"
    )
    for text in task.get("tool_contains") or []:
        checks.append(Check(f"tool has {text}", text in tool_text))
    if task.get("spilled"):
        checks.append(Check("spilled", "完整结果：" in tool_text))
    if task.get("reads_spill"):
        checks.append(Check("read spill", _read_spill(messages)))
    before = before or {}
    after = after or {}
    for path, expect in (task.get("writes") or {}).items():
        content = after.get(path)
        if content is None:
            checks.append(Check(f"wrote {path}", False, "missing"))
            continue
        for text in expect.get("contains") or []:
            checks.append(Check(f"{path} has {text}", text in content))
        for text in expect.get("keeps") or []:
            checks.append(Check(f"{path} keeps {text}", text in content))
        for text in expect.get("absent") or []:
            checks.append(Check(f"{path} lacks {text}", text not in content))
    for path in task.get("unchanged") or []:
        checks.append(Check(f"{path} unchanged", before.get(path) == after.get(path)))
    for path in task.get("created") or []:
        checks.append(Check(f"created {path}", after.get(path) is not None))
    for path in task.get("missing") or []:
        checks.append(Check(f"missing {path}", after.get(path) is None))
    return checks


def grade_turns(
    task: dict,
    answers: list[str],
    messages: list[dict],
    before: dict[str, str | None] | None = None,
    after: dict[str, str | None] | None = None,
) -> list[Check]:
    """Check each turn's answer, then the shared reads, calls, and files."""
    checks: list[Check] = []
    for index, turn in enumerate(task.get("turns") or [], start=1):
        answer = answers[index - 1] if index - 1 < len(answers) else ""
        plain = _plain(answer or "")
        for text in turn.get("answer_contains") or []:
            checks.append(Check(f"turn {index} has {text}", _plain(text) in plain))
    rest = {key: value for key, value in task.items() if key != "answer_contains"}
    checks.extend(grade(rest, messages, answers[-1] if answers else "", before, after))
    return checks


def _plain(text: str) -> str:
    """Drop markdown emphasis so ``**4** 次`` still contains ``4 次``."""
    return " ".join("".join(char for char in text if char not in "*_`").split())


def passed(checks: list[Check]) -> bool:
    return all(check.passed for check in checks)


def tool_trace(messages: list[dict]) -> list[dict]:
    """Name, path, whether this result revealed a deferred tool, and whether it was spilled."""
    results: dict[str, str] = {}
    for message in messages:
        if message.get("role") != "tool":
            continue
        results[message.get("tool_call_id") or ""] = message.get("content") or ""
    steps: list[dict] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            content = results.get(call.get("id") or "") or ""
            steps.append(
                {
                    "name": call.get("name") or "",
                    "path": _call_path(call.get("arguments") or {}),
                    "revealed": _result_revealed(call.get("name") or "", content),
                    "compacted": "完整结果：" in content,
                }
            )
    return steps


def _call_path(arguments: dict) -> str:
    for key in ("path", "pattern", "name", "query"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return _path(value) if key == "path" else value
    return ""


def _result_revealed(name: str, content: str) -> bool:
    if content.startswith("error:"):
        return False
    if name == "tool_describe" and " is available" in content:
        return True
    if name == "read_file" and "tools:" in content:
        return True
    return False


def _calls(messages: list[dict], name: str) -> list[dict]:
    found = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            if call.get("name") != name:
                continue
            arguments = call.get("arguments") or {}
            offset = arguments.get("offset", 1)
            found.append({"path": _path(str(arguments.get("path") or "")), "offset": int(offset)})
    return found


def _read_spill(messages: list[dict]) -> bool:
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            if call.get("name") != "read_file":
                continue
            path = str((call.get("arguments") or {}).get("path") or "")
            if "tools/" in path.replace("\\", "/"):
                return True
    return False


def _call_names(messages: list[dict]) -> set[str]:
    names: set[str] = set()
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            names.add(call.get("name") or "")
    return names


def _revealed(messages: list[dict], name: str) -> bool:
    for message in messages:
        if message.get("role") != "tool":
            continue
        content = message.get("content") or ""
        if content.startswith("error:"):
            continue
        tool = message.get("name") or ""
        if tool == "tool_describe" and f"{name} is available" in content:
            return True
        if tool == "read_file" and f"tools: {name}" in content:
            return True
    return False


def _path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")
