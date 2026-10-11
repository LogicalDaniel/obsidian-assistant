"""Run the benchmark tasks against the local test vault.

    uv run python benchmark/run.py
    uv run python benchmark/run.py --list
    uv run python benchmark/run.py --category links
    uv run python benchmark/run.py --id link-outgoing --id link-backlinks

Each task is one session. A single question is one turn. ``turns`` is a
multi-turn session. A write that pauses is approved or declined from the task.
The session directory is removed afterwards. Changed notes are restored.
A full run writes ``benchmark/last_run.json``. A category or id selection
prints the same checks and leaves that file unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config import assistant_dir  # noqa: E402
from entry import build_agent  # noqa: E402
from sessions import SessionStore  # noqa: E402

from pdfs import write_fixture_pdfs  # noqa: E402
from report import HTML, write_report  # noqa: E402
from score import Check, grade, grade_turns, passed, tool_trace  # noqa: E402

VAULT = Path(__file__).resolve().parent / "test_vault"
TASKS = Path(__file__).resolve().parent / "tasks.json"
REPORT = Path(__file__).resolve().parent / "last_run.json"


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    tasks = json.loads(TASKS.read_text(encoding="utf-8"))
    if args.list:
        _print_catalog(tasks)
        return
    unknown = _unknown(tasks, args.category, args.id)
    if unknown:
        for line in unknown:
            print(line)
        raise SystemExit(2)
    selected = _select(tasks, args.category, args.id)
    subset = bool(args.category or args.id)
    print(f"running {len(selected)}/{len(tasks)} tasks")
    write_fixture_pdfs(VAULT)
    agent = build_agent(VAULT)
    store = SessionStore(assistant_dir(VAULT) / "sessions", agent)
    rows = [_run_one(agent, store, task) for task in selected]
    ok = sum(1 for row in rows if row["passed"])
    _print_groups(rows)
    print(f"\n{ok}/{len(rows)} tasks passed")
    if subset:
        print("left last_run.json unchanged")
        return
    REPORT.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(rows, HTML)
    print(f"wrote {REPORT.relative_to(ROOT).as_posix()}")
    print(f"wrote {HTML.relative_to(ROOT).as_posix()}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run benchmark tasks against the local test vault.")
    parser.add_argument("--category", action="append", default=[], help="Include this category. Repeat to add more.")
    parser.add_argument("--id", action="append", default=[], help="Include this task id. Repeat to add more.")
    parser.add_argument("--list", action="store_true", help="Print categories and task ids, then exit.")
    return parser


def _select(tasks: list[dict], categories: list[str], ids: list[str]) -> list[dict]:
    """Tasks whose category or id was requested. No filter returns every task."""
    if not categories and not ids:
        return tasks
    chosen = set(categories)
    named = set(ids)
    return [
        task
        for task in tasks
        if (task.get("category") or "note-qa") in chosen or task["id"] in named
    ]


def _unknown(tasks: list[dict], categories: list[str], ids: list[str]) -> list[str]:
    known_categories = {task.get("category") or "note-qa" for task in tasks}
    known_ids = {task["id"] for task in tasks}
    lines = [f"unknown category: {name}" for name in categories if name not in known_categories]
    lines.extend(f"unknown id: {name}" for name in ids if name not in known_ids)
    return lines


def _print_catalog(tasks: list[dict]) -> None:
    groups: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        groups[task.get("category") or "note-qa"].append(task["id"])
    for category, task_ids in groups.items():
        print(f"{category}  {len(task_ids)}")
        for task_id in task_ids:
            print(f"  {task_id}")


def _run_one(agent, store: SessionStore, task: dict) -> dict:
    category = task.get("category") or "note-qa"
    question = task.get("question") or _first_question(task)
    print(f"\n[{category}] {task['id']}")
    print(question)
    paths = _paths(task)
    before = _snapshot(VAULT, paths)
    started = time.perf_counter()
    try:
        row = execute_task(agent, store, task, VAULT, before)
    except Exception as exc:
        print(f"  error  {type(exc).__name__}: {exc}")
        return {
            "id": task["id"],
            "category": category,
            "question": question,
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
            "checks": [],
        }
    finally:
        _restore(VAULT, before)
    row["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    for check in row["checks"]:
        mark = "ok  " if check["passed"] else "fail"
        detail = f"  {check['detail']}" if check["detail"] else ""
        print(f"  {mark}  {check['name']}{detail}")
    if row.get("trace"):
        print("  trace " + " | ".join(_trace_item(item) for item in row["trace"]))
    print(
        f"  steps {row['steps']}  tool_calls {row['tool_calls']}  "
        f"input_tokens {row['input_tokens']}  output_tokens {row['output_tokens']}  "
        f"cached_tokens {row['cached_tokens']}  elapsed_ms {row['elapsed_ms']}"
    )
    print(row.get("answer") or "")
    return row


def execute_task(agent, store: SessionStore, task: dict, vault: Path, before: dict[str, str | None]) -> dict:
    """Run one task as its own session, then delete that session."""
    saved = store.compactor.light
    if task.get("compact_light") is not None:
        store.compactor.light = int(task["compact_light"])
    session = None
    try:
        session = store.create()
        answers: list[str] = []
        input_tokens = output_tokens = cached_tokens = 0
        for question in _questions(task):
            session = store.send(session.id, question)
            session = _approve_session(store, session, task, vault)
            answers.append(_last_answer(session.turns))
            input_tokens += session.input_tokens
            output_tokens += session.output_tokens
            cached_tokens += session.cached_tokens
        turns = [dict(message) for message in session.turns]
        prompt_tokens = session.prompt_tokens
    finally:
        store.compactor.light = saved
        if session is not None:
            store.discard(session.id)
    after = _snapshot(vault, _paths(task))
    if task.get("turns"):
        checks = grade_turns(task, answers, turns, before, after)
    else:
        checks = grade(task, turns, answers[-1] if answers else "", before, after)
    return _row(
        task,
        turns,
        answers[-1] if answers else "",
        checks,
        sum(1 for message in turns if message.get("role") == "assistant"),
        prompt_tokens,
        input_tokens,
        output_tokens,
        cached_tokens,
    )


def _approve_session(store: SessionStore, session, task: dict, vault: Path):
    mutated = False
    while store.waiting(session.id) is not None:
        if "approve" not in task:
            break
        if not mutated:
            _apply_mutate(vault, task.get("mutate_before_approve") or {})
            mutated = True
        session = store.approve(session.id, bool(task["approve"]))
    return session


def _questions(task: dict) -> list[str]:
    if task.get("turns"):
        return [turn["question"] for turn in task["turns"]]
    return [task["question"]]


def _last_answer(turns: list[dict]) -> str:
    answers = []
    current = ""
    started = False
    for message in turns:
        if message.get("role") == "user":
            if started:
                answers.append(current)
            started = True
            current = ""
            continue
        if message.get("role") == "assistant" and not message.get("tool_calls"):
            current = message.get("content") or ""
    if started:
        answers.append(current)
    return answers[-1] if answers else ""


def _complete(agent, state, task: dict, root: Path | None = None):
    """Approve or decline a waiting write. Optionally edit the file first."""
    root = root if root is not None else VAULT
    mutated = False
    while state.waiting is not None:
        if "approve" not in task:
            break
        if not mutated:
            _apply_mutate(root, task.get("mutate_before_approve") or {})
            mutated = True
        state = agent.resume(
            state.context.messages,
            bool(task["approve"]),
            state.prompt_tokens,
            state.input_tokens,
            state.output_tokens,
            state.cached_tokens,
        )
    return state


def _apply_mutate(root: Path, files: dict[str, str]) -> None:
    for path, content in files.items():
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")


def _row(
    task: dict,
    messages: list[dict],
    answer: str,
    checks: list[Check],
    steps: int,
    prompt_tokens: int,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
) -> dict:
    return {
        "id": task["id"],
        "category": task.get("category") or "note-qa",
        "question": task.get("question") or _first_question(task),
        "passed": passed(checks),
        "answer": answer,
        "steps": steps,
        "tool_calls": _tool_call_count(messages),
        "prompt_tokens": prompt_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "trace": tool_trace(messages),
        "checks": [
            {"name": check.name, "passed": check.passed, "detail": check.detail} for check in checks
        ],
    }


def _paths(task: dict) -> list[str]:
    paths = set(task.get("unchanged") or [])
    paths.update(task.get("created") or [])
    paths.update(task.get("missing") or [])
    paths.update(task.get("writes") or {})
    paths.update(task.get("mutate_before_approve") or {})
    return sorted(paths)


def _snapshot(root: Path, paths: list[str]) -> dict[str, str | None]:
    files: dict[str, str | None] = {}
    for path in paths:
        file = root / path
        files[path] = file.read_text(encoding="utf-8") if file.is_file() else None
    return files


def _restore(root: Path, before: dict[str, str | None]) -> None:
    for path, content in before.items():
        file = root / path
        if content is None:
            if file.is_file():
                file.unlink()
            continue
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")


def _trace_item(item: dict) -> str:
    name = item.get("name") or ""
    path = item.get("path") or ""
    label = f"{name} {path}".strip()
    marks = []
    if item.get("revealed"):
        marks.append("revealed")
    if item.get("compacted"):
        marks.append("compacted")
    if marks:
        label += f" ({', '.join(marks)})"
    return label


def _tool_call_count(messages: list[dict]) -> int:
    return sum(len(message.get("tool_calls") or []) for message in messages if message.get("role") == "assistant")


def _first_question(task: dict) -> str:
    turns = task.get("turns") or []
    if not turns:
        return ""
    return turns[0].get("question") or ""


def _print_groups(rows: list[dict]) -> None:
    groups: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        groups[row.get("category") or "note-qa"].append(row["passed"])
    print("\nby category")
    for category, results in groups.items():
        print(f"  {category}  {sum(results)}/{len(results)}")


if __name__ == "__main__":
    main()
