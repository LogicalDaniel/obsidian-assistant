"""Interface copy. The page stores the chosen language in session state."""

from __future__ import annotations

import streamlit as st

_STRINGS = {
    "zh": {
        "no_folder": "没有选中文件夹。",
        "key_title": "填写 OpenAI API key",
        "key_caption": "保存到项目根目录的 .env，下次启动不用再填。",
        "key_missing": "请填写 OPENAI_API_KEY",
        "save": "保存",
        "vault_title": "选择笔记库",
        "vault_caption": "选一个 Obsidian 库文件夹。工作区会建在这个库的 .assistant 里。",
        "browse": "浏览文件夹",
        "paste_path": "或粘贴路径",
        "use_path": "使用此路径",
        "not_a_folder": "这个路径不是文件夹。",
        "pick_vault": "选择笔记库",
        "thinking": "正在思考",
        "interrupted": "思考中断",
        "waiting_status": "等待确认",
        "finished": "思考完成",
        "writing": "正在写入",
        "cancelling": "正在取消",
        "not_finished": "没有完成",
        "kicker": "笔记库",
        "app_title": "笔记助手",
        "change_vault": "更换笔记库",
        "new_chat": "新对话",
        "filter": "筛选标题",
        "no_chats": "没有匹配的对话。",
        "chat_count": "{title}  ·  {count} 问",
        "empty_chat": "这一则还没有问题。",
        "round_summary": "{questions} 个问题 · {steps} 步工具 · {tokens} prompt tokens",
        "confirm_first": "先确认上面的写入",
        "ask": "问笔记里的一个问题",
        "step_count": "{count} 步",
        "confirm": "确认",
        "write": "写入",
        "cancel": "取消",
        "from_page": "从第 {offset} 页",
        "from_line": "从第 {offset} 行",
        "hit_line": "第 {line} 行",
        "no_return": "这一步没有返回。",
        "search_notes": "搜索",
        "note_links": "链接",
        "read_note": "阅读",
        "read_file": "读取",
        "list_notes": "列出",
        "glob": "查找",
        "insert_text": "插入",
        "delete_lines": "删除",
        "create_note": "新建",
        "write_file": "写入",
        "run_subtask": "子任务",
        "read_pdf": "阅读 PDF",
        "tool_describe": "加载工具",
    },
    "en": {
        "no_folder": "No folder was selected.",
        "key_title": "Enter your OpenAI API key",
        "key_caption": "Saved in the project .env. You will not need to enter it next time.",
        "key_missing": "Enter an OPENAI_API_KEY.",
        "save": "Save",
        "vault_title": "Choose a notes folder",
        "vault_caption": "Choose an Obsidian vault. Its workspace is created in .assistant.",
        "browse": "Browse",
        "paste_path": "Or paste a path",
        "use_path": "Use this path",
        "not_a_folder": "That path is not a folder.",
        "pick_vault": "Choose a notes folder",
        "thinking": "Thinking",
        "interrupted": "Interrupted",
        "waiting_status": "Waiting for confirmation",
        "finished": "Finished",
        "writing": "Writing",
        "cancelling": "Cancelling",
        "not_finished": "Not finished",
        "kicker": "Vault",
        "app_title": "Notes",
        "change_vault": "Change vault",
        "new_chat": "New chat",
        "filter": "Filter titles",
        "no_chats": "No matching chats.",
        "chat_count": "{title}  ·  {count} questions",
        "empty_chat": "This chat has no question yet.",
        "round_summary": "{questions} questions · {steps} tool steps · {tokens} prompt tokens",
        "confirm_first": "Confirm the write above first",
        "ask": "Ask a question about your notes",
        "step_count": "{count} steps",
        "confirm": "Confirm",
        "write": "Write",
        "cancel": "Cancel",
        "from_page": "from page {offset}",
        "from_line": "from line {offset}",
        "hit_line": "Line {line}",
        "no_return": "This step returned nothing.",
        "search_notes": "Search",
        "note_links": "Links",
        "read_note": "Read",
        "read_file": "Read file",
        "list_notes": "List",
        "glob": "Find",
        "insert_text": "Insert",
        "delete_lines": "Delete",
        "create_note": "New note",
        "write_file": "Write file",
        "run_subtask": "Subtask",
        "read_pdf": "Read PDF",
        "tool_describe": "Load tool",
    },
}


def language() -> str:
    """The language for this browser session. A new session follows the browser."""
    choice = st.session_state.get("language")
    if choice in _STRINGS:
        return choice
    return "en" if _browser_language().lower().startswith("en") else "zh"


def choose_language() -> None:
    """Draw the language switch. The control itself stays bilingual."""
    if "language" not in st.session_state:
        st.session_state.language = language()
    st.radio(
        "language",
        ["zh", "en"],
        format_func=lambda code: "中文" if code == "zh" else "English",
        horizontal=True,
        label_visibility="collapsed",
        key="language",
    )


def t(key: str, **values: object) -> str:
    """One interface string in the current language. An unknown key is returned as itself."""
    text = _STRINGS[language()].get(key, key)
    return text.format(**values) if values else text


def _browser_language() -> str:
    context = getattr(st, "context", None)
    if context is None:
        return ""
    return str(getattr(context, "locale", "") or "")
