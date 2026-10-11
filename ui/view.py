"""Turn a saved session into the chat pane.

Search hits, page text, tool rows, and the write-confirm card live here.
The page script decides when to ask and when to approve.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from pathlib import Path

import streamlit as st

from text import t

_MARKER = "完整结果："


def rounds(turns: list[dict]) -> list[dict]:
    grouped: list[dict] = []
    current: dict | None = None
    for turn in turns:
        role = turn.get("role")
        if role == "user":
            current = {"user": turn, "calls": [], "tools": [], "answer": None}
            grouped.append(current)
        elif current is None:
            continue
        elif role == "assistant" and turn.get("tool_calls"):
            current["calls"].append(turn)
        elif role == "tool":
            current["tools"].append(turn)
        elif role == "assistant" and turn.get("content"):
            current["answer"] = turn
    return grouped


def steps(round_: dict) -> list[tuple[dict, dict | None]]:
    results = {item.get("tool_call_id"): item for item in round_["tools"]}
    paired: list[tuple[dict, dict | None]] = []
    seen: set[str] = set()
    for call_turn in round_["calls"]:
        for call in call_turn.get("tool_calls") or []:
            call_id = call.get("id") or ""
            seen.add(call_id)
            paired.append((call, results.get(call_id)))
    for tool in round_["tools"]:
        call_id = tool.get("tool_call_id") or ""
        if call_id not in seen:
            paired.append(({"name": tool.get("name") or "tool", "arguments": {}, "id": call_id}, tool))
    return paired


def show_round(round_: dict, pending_id: str | None = None) -> None:
    with st.chat_message("user"):
        st.markdown(round_["user"].get("content") or "")
    shown = [
        (call, tool)
        for call, tool in steps(round_)
        if pending_id is None or call.get("id") != pending_id
    ]
    if shown:
        _pad, trace = st.columns([0.04, 0.96])
        with trace:
            st.caption(t("step_count", count=len(shown)))
            for index, (call, tool) in enumerate(shown, start=1):
                with st.expander(f"{index}　{_step_label(call)}", expanded=False):
                    _show_result(call, tool)
    answer = round_.get("answer")
    if answer is not None:
        with st.chat_message("assistant"):
            st.markdown(answer.get("content") or "")


def live_tool(call: dict, result: str) -> None:
    """One finished tool call, drawn under the open thinking status. Nested calls are indented."""
    depth = int(call.get("depth") or 0)
    with st.expander(f"{'· ' * depth}{_step_label(call)}", expanded=False):
        _show_result(call, {"content": result})


def show_waiting(call: dict, preview: str, on_decide: Callable[[bool], None]) -> None:
    path, rows = _preview_rows(preview)
    kind = t(call.get("name") or "confirm")
    if rows and all(mark == "add" for mark, _text in rows):
        body = _note_html([text for _mark, text in rows])
    elif rows:
        body = _diff_html(rows)
    else:
        body = f"<div class='note-p'>{html.escape(preview)}</div>"
    st.html(
        "<div class='confirm'>"
        "<div class='confirm-head'>"
        f"<span class='confirm-path'>{html.escape(path or kind)}</span>"
        f"<span class='confirm-kind'>{html.escape(kind)}</span>"
        "</div>"
        f"<div class='confirm-body'>{body}</div>"
        "</div>"
    )
    _spacer, write, cancel = st.columns([0.64, 0.18, 0.18])
    with write:
        if st.button(t("write"), type="primary", use_container_width=True):
            on_decide(True)
            st.rerun()
    with cancel:
        if st.button(t("cancel"), use_container_width=True):
            on_decide(False)
            st.rerun()


def _full_text(content: str) -> str:
    if _MARKER not in content:
        return content
    _head, _, path = content.partition(_MARKER)
    file = Path(st.session_state.workspace) / path.strip()
    if file.is_file():
        return file.read_text(encoding="utf-8")
    return content


def _fields(block: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in block.splitlines():
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        if key in {"path", "title", "line", "lines", "snippet"} and key not in found:
            found[key] = value
    return found


def _search_hits(text: str) -> list[dict[str, str]]:
    hits = []
    for block in text.split("\n\n"):
        found = _fields(block)
        if "path" in found and "snippet" in found:
            hits.append(found)
    return hits


def _read_parts(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    meta: dict[str, str] = {}
    body_at = len(lines)
    for index, line in enumerate(lines):
        if line == "":
            body_at = index + 1
            break
        if ": " in line:
            key, value = line.split(": ", 1)
            meta[key] = value
    return meta, "\n".join(lines[body_at:])


def _step_label(call: dict) -> str:
    name = call.get("name") or "tool"
    arguments = call.get("arguments") or {}
    action = t(name)
    if name == "search_notes":
        return f"{action}  {arguments.get('query') or ''}"
    if name == "tool_describe":
        return f"{action}  {arguments.get('name') or ''}"
    if name == "read_pdf":
        path = arguments.get("path") or ""
        offset = arguments.get("offset")
        if offset:
            return f"{action}  {path}  {t('from_page', offset=offset)}"
        return f"{action}  {path}"
    if name in {"read_note", "read_file"}:
        path = arguments.get("path") or ""
        offset = arguments.get("offset")
        if offset:
            return f"{action}  {path}  {t('from_line', offset=offset)}"
        return f"{action}  {path}"
    if name in {"insert_text", "delete_lines", "create_note", "write_file", "run_subtask"}:
        return f"{action}  {arguments.get('path') or arguments.get('scope') or ''}"
    return action


def _one_line(text: str, limit: int = 96) -> str:
    line = " ".join(text.split())
    if len(line) <= limit:
        return line
    return line[:limit] + "…"


def _show_search(text: str) -> None:
    hits = _search_hits(text)
    if not hits:
        st.text(text)
        return
    rows = []
    for hit in hits:
        path = html.escape(hit.get("path") or "")
        line = html.escape(hit.get("line") or "?")
        snippet = html.escape(_one_line(hit.get("snippet") or ""))
        rows.append(
            "<div class='hit'>"
            f"<div class='hit-path'>{path}</div>"
            f"<div class='hit-line'>{t('hit_line', line=line)}</div>"
            f"<div class='hit-snippet'>{snippet}</div>"
            "</div>"
        )
    st.markdown("".join(rows), unsafe_allow_html=True)


def _show_page(text: str) -> None:
    meta, body = _read_parts(text)
    path = html.escape(meta.get("path") or "")
    span = html.escape(meta.get("lines") or meta.get("pages") or "")
    if path or span:
        st.markdown(
            f"<div class='page-meta'>{path}　{span}</div>",
            unsafe_allow_html=True,
        )
    if body:
        st.markdown(
            f"<div class='page-body'>{html.escape(body)}</div>",
            unsafe_allow_html=True,
        )


def _show_result(call: dict, tool: dict | None) -> None:
    if tool is None:
        st.caption(t("no_return"))
        return
    content = _full_text(tool.get("content") or "")
    if content.startswith("error:"):
        st.error(content)
        return
    name = call.get("name") or tool.get("name")
    if name == "search_notes":
        _show_search(content)
        return
    if name in {"read_note", "read_file", "read_pdf"}:
        _show_page(content)
        return
    if name in {"list_notes", "glob"}:
        paths = [line for line in content.splitlines() if line.strip()]
        st.markdown(
            f"<div class='page-body'>{html.escape(chr(10).join(paths))}</div>",
            unsafe_allow_html=True,
        )
        return
    st.markdown(
        f"<div class='page-body'>{html.escape(content)}</div>",
        unsafe_allow_html=True,
    )


def _preview_rows(preview: str) -> tuple[str, list[tuple[str, str]]]:
    path = ""
    rows: list[tuple[str, str]] = []
    body = False
    for line in preview.splitlines():
        if not body:
            if line.startswith("path: "):
                path = line.removeprefix("path: ").strip()
            elif line == "":
                body = True
            continue
        if line.startswith("+ "):
            rows.append(("add", line[2:]))
        elif line == "+":
            rows.append(("add", ""))
        elif line.startswith("- "):
            rows.append(("del", line[2:]))
        elif line == "-":
            rows.append(("del", ""))
        else:
            number, sep, text = line.partition("| ")
            if sep and number.isdigit():
                rows.append(("ctx", text))
            elif line:
                rows.append(("add", line))
    return path, rows


def _note_html(lines: list[str]) -> str:
    parts: list[str] = []
    for line in lines:
        if line == "":
            parts.append("<div class='note-gap'></div>")
        elif line.startswith("### "):
            parts.append(f"<div class='note-h2'>{html.escape(line[4:])}</div>")
        elif line.startswith("## "):
            parts.append(f"<div class='note-h2'>{html.escape(line[3:])}</div>")
        elif line.startswith("# "):
            parts.append(f"<div class='note-h1'>{html.escape(line[2:])}</div>")
        else:
            parts.append(f"<div class='note-p'>{html.escape(line)}</div>")
    return "".join(parts)


def _diff_html(rows: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    for kind, text in rows:
        shown = html.escape(text) if text else " "
        parts.append(f"<div class='diff-line diff-{kind}'>{shown}</div>")
    return "".join(parts)
