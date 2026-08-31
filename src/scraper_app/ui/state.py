"""Session state helpers, the workflow stepper and the shared error panel."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ..exceptions import ScraperError
from .i18n import t
from .theme import pill

STEPS = [
    ("source", "step_source"),
    ("detect", "step_detect"),
    ("fields", "step_fields"),
    ("preview", "step_preview"),
    ("extract", "step_extract"),
    ("clean", "step_clean"),
    ("export", "step_export"),
]

DEFAULTS: dict[str, Any] = {
    "lang": "en",
    "mode": "auto",
    "preset": "auto",
    "url": "",
    "goal": "",
    "analysis": None,          # AnalysisOutcome
    "outcome": None,           # ExtractionOutcome
    "selected_candidate_id": None,
    "step": "source",
    "step_states": {},
    "advanced": {},
    "demo_server": None,
    "last_error": None,
    "allow_browser": True,
    "allow_cloud": False,
    "allow_ai": False,
    "respect_robots": True,
    "max_pages": 1,
    "max_rows": None,
    "follow_pagination": False,
    "include_provenance": True,
}


def init() -> None:
    for key, value in DEFAULTS.items():
        st.session_state.setdefault(key, value)


def lang() -> str:
    return st.session_state.get("lang", "en")


def set_step(step: str, state: str = "current") -> None:
    """Advance the stepper, marking every earlier step complete."""
    order = [key for key, _label in STEPS]
    if step not in order:
        return
    states = dict(st.session_state.get("step_states", {}))
    index = order.index(step)
    for earlier in order[:index]:
        states.setdefault(earlier, "done")
        if states[earlier] == "current":
            states[earlier] = "done"
    states[step] = state
    st.session_state["step_states"] = states
    st.session_state["step"] = step


def mark(step: str, state: str) -> None:
    states = dict(st.session_state.get("step_states", {}))
    states[step] = state
    st.session_state["step_states"] = states


def render_stepper() -> None:
    """Sidebar workflow orientation — symbol + text, never colour alone."""
    language = lang()
    states = st.session_state.get("step_states", {})
    current = st.session_state.get("step", "source")
    st.sidebar.markdown(f"**{t('workflow', language)}**")
    symbols = {"done": "✓", "current": "●", "not_started": "○", "review": "!"}
    css = {"done": "done", "current": "now", "not_started": "", "review": "review"}
    for index, (key, label_key) in enumerate(STEPS, start=1):
        state = states.get(key, "current" if key == current else "not_started")
        st.sidebar.markdown(
            f'<div class="srws-step {css.get(state, "")}">'
            f'{symbols.get(state, "○")} {index}. {t(label_key, language)}'
            f'</div>',
            unsafe_allow_html=True,
        )


def reset_run(keep_url: bool = True) -> None:
    url = st.session_state.get("url", "") if keep_url else ""
    goal = st.session_state.get("goal", "") if keep_url else ""
    language = st.session_state.get("lang", "en")
    mode = st.session_state.get("mode", "auto")
    for key in list(st.session_state.keys()):
        if key in DEFAULTS:
            st.session_state[key] = DEFAULTS[key]
    st.session_state["url"] = url
    st.session_state["goal"] = goal
    st.session_state["lang"] = language
    st.session_state["mode"] = mode


def show_error(error: Exception, extra_actions: list[tuple[str, str]] | None = None) -> None:
    """Readable error panel with recovery actions (spec section 106.11)."""
    language = lang()
    if isinstance(error, ScraperError):
        st.error(f"**{error.code.value}** — {error.message(language)}")
        actions = error.actions(language)
    else:
        st.error(
            t("app_title", language)
            + ": "
            + ("حدث خطأ غير متوقع." if language == "ar" else "An unexpected error occurred.")
        )
        actions = []

    if actions:
        st.markdown(f"**{t('what_next', language)}**")
        for action in actions:
            st.markdown(f"- {action}")

    if extra_actions:
        columns = st.columns(len(extra_actions))
        for column, (label, target) in zip(columns, extra_actions, strict=False):
            with column:
                if st.button(label, key=f"recover_{target}", width="stretch"):
                    st.session_state["step"] = target
                    st.rerun()

    if isinstance(error, ScraperError) and error.context:
        with st.expander("Technical details", expanded=False):
            st.json({k: str(v) for k, v in error.context.items()})


def engine_badge(engine_name: str) -> str:
    return pill(engine_name, "info", "⚙")
