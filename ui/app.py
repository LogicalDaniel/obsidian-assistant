"""Session sidebar and a chat pane.

    uv run streamlit run ui/app.py

The page calls `SessionStore`. Sending a message runs the agent for that session.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import streamlit as st

from agent.openai_model import api_key_from_env, save_api_key
from config import assistant_dir, load_vault, save_vault
from entry import build_agent, pick_directory
from sessions import SessionStore
from style import CSS
from text import choose_language, t
from view import live_tool, rounds, show_round, show_waiting, steps

st.set_page_config(page_title="笔记助手", layout="wide", initial_sidebar_state="expanded")
st.markdown(CSS, unsafe_allow_html=True)
with st.sidebar:
    choose_language()


def _open_store() -> SessionStore:
    vault = load_vault()
    if vault is None:
        raise FileNotFoundError("choose a notes vault before starting")
    st.session_state.vault_path = vault
    st.session_state.workspace = assistant_dir(vault)
    return SessionStore(st.session_state.workspace / "sessions", build_agent(vault))


def _select_vault() -> None:
    chosen = pick_directory(t("pick_vault"))
    if chosen is None:
        st.session_state.vault_message = t("no_folder")
        return
    save_vault(chosen)
    st.session_state.pop("store", None)
    st.session_state.pop("vault_message", None)
    st.rerun()


if not api_key_from_env():
    st.subheader(t("key_title"))
    st.caption(t("key_caption"))
    with st.form("openai-api-key"):
        typed = st.text_input("OPENAI_API_KEY", type="password")
        submitted = st.form_submit_button(t("save"))
    if submitted:
        if typed.strip():
            save_api_key(typed)
            st.rerun()
        else:
            st.warning(t("key_missing"))
    st.stop()

if load_vault() is None:
    st.subheader(t("vault_title"))
    st.caption(t("vault_caption"))
    if st.button(t("browse")):
        _select_vault()
    typed = st.text_input(t("paste_path"))
    if st.button(t("use_path")):
        path = Path(typed.strip().strip('"'))
        if path.is_dir():
            save_vault(path)
            st.session_state.pop("store", None)
            st.rerun()
        else:
            st.warning(t("not_a_folder"))
    if message := st.session_state.get("vault_message"):
        st.info(message)
    st.stop()

if "store" not in st.session_state or st.session_state.store.agent is None:
    st.session_state.store = _open_store()

store: SessionStore = st.session_state.store


def _ask(text: str) -> None:
    session = store.current()
    if session is None:
        session = store.create()
    with st.status(t("thinking"), expanded=False) as status:
        try:
            store.send(session.id, text, on_tool=live_tool)
        except Exception as exc:
            status.update(label=t("interrupted"), state="error")
            st.session_state.send_error = f"{type(exc).__name__}: {exc}"
            return
        if store.waiting(session.id) is not None:
            status.update(label=t("waiting_status"), state="complete")
        else:
            status.update(label=t("finished"), state="complete")


def _approve(approved: bool) -> None:
    session = store.current()
    if session is None:
        return
    label = t("writing") if approved else t("cancelling")
    with st.status(label, expanded=False) as status:
        try:
            store.approve(session.id, approved, on_tool=live_tool)
        except Exception as exc:
            status.update(label=t("not_finished"), state="error")
            st.session_state.send_error = f"{type(exc).__name__}: {exc}"
            return
        if store.waiting(session.id) is not None:
            status.update(label=t("waiting_status"), state="complete")
        else:
            status.update(label=t("finished"), state="complete")


with st.sidebar:
    st.markdown(f"<div class='desk-kicker'>{html.escape(t('kicker'))}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='desk-title'>{html.escape(t('app_title'))}</div>", unsafe_allow_html=True)
    st.caption(str(st.session_state.vault_path))
    if st.button(t("change_vault"), use_container_width=True):
        _select_vault()
    if message := st.session_state.get("vault_message"):
        st.caption(message)
    if st.button(t("new_chat"), use_container_width=True):
        store.create()
        st.rerun()
    needle = st.text_input("filter", placeholder=t("filter"), label_visibility="collapsed")
    sessions = [
        session
        for session in reversed(store.list())
        if needle.strip().casefold() in session.title.casefold()
    ]
    if not sessions:
        st.caption(t("no_chats"))
    for session in sessions:
        active = session.id == store.current_id
        questions = sum(1 for turn in session.turns if turn.get("role") == "user")
        title = t("new_chat") if session.title == "新对话" else session.title
        label = title if not questions else t("chat_count", title=title, count=questions)
        if st.button(
            label,
            key=session.id,
            type="primary" if active else "secondary",
            use_container_width=True,
        ):
            store.switch(session.id)
            st.rerun()

error = st.session_state.pop("send_error", None)
if error:
    st.error(error)

current = store.current()
waiting = store.waiting(current.id) if current is not None else None
visible = rounds(current.turns) if current is not None else []

if current is not None and not visible:
    st.markdown(
        f"<div class='desk-title'>{html.escape(current.title)}</div>",
        unsafe_allow_html=True,
    )
    st.caption(t("empty_chat"))
elif current is not None:
    tool_steps = sum(len(steps(item)) for item in visible)
    st.markdown(
        f"<div class='desk-title'>{html.escape(current.title)}</div>",
        unsafe_allow_html=True,
    )
    st.caption(t("round_summary", questions=len(visible), steps=tool_steps, tokens=current.prompt_tokens))
    pending_id = waiting[0].get("id") if waiting is not None else None
    for round_ in visible:
        show_round(round_, pending_id)
    if waiting is not None:
        show_waiting(*waiting, _approve)

question = st.chat_input(
    t("confirm_first") if waiting is not None else t("ask"),
    disabled=waiting is not None,
)
if question and waiting is None:
    _ask(question)
    st.rerun()
