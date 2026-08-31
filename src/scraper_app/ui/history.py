"""Page 10 — History and recipes (spec section 19).

Lists previous runs stored on disk, lets the researcher reload a dataset, or
re-run a saved recipe against the live source.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..service import rerun_recipe
from ..storage import run_store
from . import state
from .i18n import t
from .theme import note


def render() -> None:
    lang = state.lang()
    st.title(t("history", lang))
    st.caption(
        "Runs are stored locally in the runs/ folder of this project."
        if lang == "en"
        else "تُحفظ عمليات التشغيل محليًا في مجلد runs/ داخل المشروع."
    )

    records = run_store.list_runs()
    if not records:
        note(
            "No previous runs yet." if lang == "en" else "لا توجد عمليات سابقة بعد."
        )
    else:
        st.dataframe(
            pd.DataFrame([record.as_dict() for record in records])[
                ["created_at", "title", "source_url", "engine", "rows", "columns", "recipe_hash", "run_id"]
            ],
            width="stretch",
            hide_index=True,
        )

        choice = st.selectbox(
            "Select a run" if lang == "en" else "اختر عملية",
            options=[record.run_id for record in records],
            format_func=lambda run_id: next(
                (f"{r.created_at[:16]} · {r.title or r.source_url}" for r in records if r.run_id == run_id),
                run_id,
            ),
        )
        columns = st.columns(3)
        if columns[0].button("Load dataset" if lang == "en" else "تحميل البيانات", width="stretch"):
            frame = run_store.load_frame(choice)
            if frame is None:
                st.warning("This run has no stored dataset.")
            else:
                st.session_state["history_frame"] = frame
        if columns[1].button("Re-run recipe" if lang == "en" else "إعادة تشغيل الوصفة", width="stretch"):
            recipe = run_store.load_recipe(choice)
            if not recipe:
                st.warning("This run has no stored recipe.")
            else:
                with st.status("Re-running the saved recipe…", expanded=True) as status:
                    try:
                        import json

                        outcome = rerun_recipe(json.dumps(recipe))
                        st.session_state["outcome"] = outcome
                        status.update(label="Recipe re-run complete", state="complete")
                        state.set_step("clean")
                        st.rerun()
                    except Exception as exc:
                        status.update(label="Re-run failed", state="error")
                        state.show_error(exc)
        if columns[2].button("Delete run" if lang == "en" else "حذف العملية", width="stretch"):
            run_store.delete_run(choice)
            st.rerun()

        frame = st.session_state.get("history_frame")
        if frame is not None:
            st.markdown("**Stored dataset**")
            st.dataframe(frame.head(500), width="stretch", hide_index=True)

    st.divider()
    st.markdown(f"### {'Run a recipe file' if lang == 'en' else 'تشغيل ملف وصفة'}")
    uploaded = st.file_uploader(
        "extraction_recipe.json", type=["json"], accept_multiple_files=False
    )
    if uploaded is not None and st.button(
        "Run this recipe" if lang == "en" else "شغّل هذه الوصفة", type="primary"
    ):
        with st.status("Running the recipe…", expanded=True) as status:
            try:
                outcome = rerun_recipe(uploaded.getvalue())
                st.session_state["outcome"] = outcome
                status.update(label="Recipe complete", state="complete")
                state.set_step("clean")
                st.rerun()
            except Exception as exc:
                status.update(label="Recipe failed", state="error")
                state.show_error(exc)
