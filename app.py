"""Smart Research Web Scraper — Streamlit entry point.

Developed by Dr Merwan Roudane (https://github.com/merwanroudane).

Run with:

    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scraper_app.config import APP_AUTHOR, APP_NAME, APP_VERSION, ensure_dirs  # noqa: E402
from scraper_app.ui import (  # noqa: E402
    dataset_builder,
    extraction_run,
    find_sources,
    help_page,
    history,
    home,
    settings,
    source_analysis,
    state,
    workspace,
)
from scraper_app.ui.i18n import LANGUAGES, is_rtl, t  # noqa: E402
from scraper_app.ui.theme import inject  # noqa: E402

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

ensure_dirs()
state.init()
inject(rtl=is_rtl(state.lang()))

STEP_PAGES = {
    "source": home.render,
    "detect": source_analysis.render,
    "fields": dataset_builder.render,
    "preview": extraction_run.render,
    "extract": extraction_run.render,
    "clean": workspace.render,
    "export": workspace.render,
}


def _sidebar() -> str:
    lang = state.lang()
    with st.sidebar:
        st.markdown(f"### {t('app_title', lang)}")
        st.caption(f"v{APP_VERSION} · {t('developed_by', lang)} {APP_AUTHOR}")

        chosen = st.selectbox(
            t("language", lang),
            options=list(LANGUAGES),
            format_func=lambda key: LANGUAGES[key],
            index=list(LANGUAGES).index(lang),
            key="language_select",
        )
        if chosen != lang:
            st.session_state["lang"] = chosen
            st.rerun()

        st.divider()
        state.render_stepper()
        st.divider()

        page = st.radio(
            "Pages" if lang == "en" else "الصفحات",
            options=["workflow", "find_sources", "history", "engines", "help"],
            format_func=lambda key: {
                "workflow": t("workflow", lang),
                "find_sources": t("find_sources", lang),
                "history": t("history", lang),
                "engines": t("engines", lang),
                "help": t("help", lang),
            }[key],
            key="page_select",
        )

        st.divider()
        if st.button(t("new_extraction", lang), width="stretch"):
            state.reset_run(keep_url=False)
            st.rerun()
        if (
            st.session_state.get("outcome") is not None
            or st.session_state.get("analysis") is not None
        ):
            if st.button(t("clear_session", lang), width="stretch"):
                if st.session_state.get("outcome") is not None:
                    st.warning(
                        "This clears the current dataset from memory. Download it first if you need it."
                        if lang == "en"
                        else "هذا يمسح البيانات الحالية من الذاكرة. نزّلها أولًا إذا كنت تحتاجها."
                    )
                state.reset_run(keep_url=False)
                st.rerun()

        outcome = st.session_state.get("outcome")
        if outcome is not None:
            st.caption(
                f"{len(outcome.clean_df):,} {t('rows', lang).lower()} · {outcome.result.engine}"
            )
    return page


def _workflow_navigation(lang: str) -> None:
    """Let the researcher move back and forth once a step is reachable."""
    analysis = st.session_state.get("analysis")
    outcome = st.session_state.get("outcome")
    available = [("source", t("step_source", lang))]
    if analysis is not None:
        available += [
            ("detect", t("step_detect", lang)),
            ("fields", t("step_fields", lang)),
            ("preview", t("step_preview", lang)),
        ]
    if outcome is not None:
        available.append(("clean", t("step_clean", lang)))

    if len(available) < 2:
        return
    keys = [key for key, _label in available]
    current = st.session_state.get("step", "source")
    if current not in keys:
        current = keys[-1]
    labels = dict(available)
    # Keep the control in sync when the step advanced programmatically: a keyed
    # widget would otherwise keep returning its own stale selection.
    if (
        st.session_state.get("workflow_nav") not in keys
        or st.session_state.get("workflow_nav") != current
    ):
        st.session_state["workflow_nav"] = current
    chosen = st.segmented_control(
        t("workflow", lang),
        options=keys,
        format_func=lambda key: labels[key],
        key="workflow_nav",
        label_visibility="collapsed",
    )
    if chosen and chosen != current:
        state.set_step(chosen)
        st.rerun()


def main() -> None:
    page = _sidebar()
    lang = state.lang()

    if page == "find_sources":
        find_sources.render()
        return
    if page == "history":
        history.render()
        return
    if page == "engines":
        settings.render()
        return
    if page == "help":
        help_page.render()
        return

    _workflow_navigation(lang)
    step = st.session_state.get("step", "source")
    renderer = STEP_PAGES.get(step, home.render)
    renderer()


if __name__ == "__main__":
    main()
else:
    main()
