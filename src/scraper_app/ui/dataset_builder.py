"""Page 3 — Dataset builder (spec section 19).

The researcher confirms which fields to keep, renames them if wanted, and
previews the extraction on a few pages before committing to a full run
(spec section 62).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..models import Confidence, ExtractionSchema, FieldSpec, NameSource
from . import state
from .i18n import t
from .theme import card, confidence_badge, note, pills


def _selected_candidate():
    analysis = st.session_state.get("analysis")
    if analysis is None:
        return None
    candidate_id = st.session_state.get("selected_candidate_id")
    for candidate in analysis.profile.candidates:
        if candidate.id == candidate_id:
            return candidate
    return analysis.profile.candidates[0] if analysis.profile.candidates else None


def _field_rows(candidate, analysis) -> pd.DataFrame:
    """Build the editable field table from the candidate and the user request."""
    payload_fields = (candidate.payload or {}).get("fields") or []
    specs: list[FieldSpec] = [FieldSpec(**f) for f in payload_fields] if payload_fields else []
    if not specs:
        columns = candidate.columns or (
            list(candidate.sample_rows[0].keys()) if candidate.sample_rows else []
        )
        specs = [
            FieldSpec(name=str(column), label=str(column), confidence=Confidence.HIGH)
            for column in columns
        ]

    requested = {f.name for f in (analysis.schema.fields if analysis and analysis.schema else [])}
    sample = candidate.sample_rows[0] if candidate.sample_rows else {}

    rows = []
    for spec in specs:
        rows.append(
            {
                "include": True,
                "field": spec.name,
                "sample": str(sample.get(spec.name, spec.sample or ""))[:60],
                "type": spec.dtype or "string",
                "confidence": spec.confidence.value,
                "rename_to": spec.name,
                "requested": spec.name in requested,
            }
        )
    return pd.DataFrame(rows)


def render() -> None:
    lang = state.lang()
    analysis = st.session_state.get("analysis")
    if analysis is None:
        note(t("no_results_yet", lang))
        return

    candidate = _selected_candidate()
    if candidate is None:
        note(t("no_results_yet", lang))
        return

    st.title(t("fields_title", lang))
    card(candidate.title, candidate.why, [confidence_badge(candidate.confidence, lang)])

    if analysis.schema and analysis.schema.fields:
        pills([(f.name, "info", "→") for f in analysis.schema.fields[:10]])
        st.caption(
            "These are the fields you asked for. Matching happens after the preview, and unmatched "
            "fields are reported rather than invented."
            if lang == "en"
            else "هذه هي الحقول التي طلبتها. تتم المطابقة بعد المعاينة، والحقول غير المطابقة تُعرض ولا تُختلق."
        )

    frame = _field_rows(candidate, analysis)
    if frame.empty:
        note(
            "This dataset does not expose named fields yet — run the preview to see its columns."
            if lang == "en"
            else "هذه المجموعة لا تعرض حقولًا مسماة بعد — شغّل المعاينة لرؤية أعمدتها."
        )
    else:
        edited = st.data_editor(
            frame,
            width="stretch",
            hide_index=True,
            column_config={
                "include": st.column_config.CheckboxColumn(t("include", lang)),
                "field": st.column_config.TextColumn(t("field", lang), disabled=True),
                "sample": st.column_config.TextColumn(t("sample", lang), disabled=True),
                "type": st.column_config.SelectboxColumn(
                    t("detected_type", lang),
                    options=["string", "number", "integer", "date", "url", "boolean"],
                ),
                "confidence": st.column_config.TextColumn(t("confidence", lang), disabled=True),
                "rename_to": st.column_config.TextColumn(t("rename", lang)),
                "requested": st.column_config.CheckboxColumn(
                    "You asked for it" if lang == "en" else "طلبتها", disabled=True
                ),
            },
            key="field_editor",
        )
        st.session_state["field_selection"] = edited.to_dict(orient="records")

    st.divider()
    left, right = st.columns([1, 1])
    with left:
        preview_pages = st.number_input(
            "Preview pages" if lang == "en" else "صفحات المعاينة",
            min_value=1,
            max_value=5,
            value=1,
            help="A small preview runs before any large crawl."
            if lang == "en"
            else "تُشغَّل معاينة صغيرة قبل أي زحف كبير.",
        )
    with right:
        st.write("")
        if st.button(t("preview_extraction", lang), type="primary", width="stretch"):
            st.session_state["preview_pages"] = int(preview_pages)
            state.set_step("preview")
            st.rerun()


def schema_from_selection(analysis) -> ExtractionSchema | None:
    """Turn the edited field table into the schema used for mapping."""
    selection = st.session_state.get("field_selection")
    if not selection:
        return analysis.schema if analysis else None

    fields: list[FieldSpec] = []
    for row in selection:
        if not row.get("include", True):
            continue
        name = (row.get("rename_to") or row.get("field") or "").strip()
        if not name:
            continue
        fields.append(
            FieldSpec(
                name=name,
                label=row.get("field"),
                dtype=row.get("type") or "string",
                name_source=NameSource.USER_DEFINED
                if name != row.get("field")
                else NameSource.SOURCE_NATIVE,
                confidence=Confidence(row.get("confidence", "medium")),
            )
        )
    return ExtractionSchema(name="dataset", fields=fields) if fields else None
