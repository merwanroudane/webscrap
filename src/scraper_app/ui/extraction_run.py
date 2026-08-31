"""Pages 4-5 — Crawl settings, preflight and run monitor (spec section 19, 106.5).

Auto mode shows a preview and a preflight card. Guided mode adds scope and
limits. Advanced mode exposes headers, selectors, pagination internals and the
engine preference — each with a safe default and a short tooltip.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..config import SETTINGS
from ..models import (
    CrawlPlan,
    ExtractionRequest,
    PaginationPlan,
    PaginationType,
    RequestOptions,
)
from ..service import extract, preflight
from . import state
from .dataset_builder import schema_from_selection
from .i18n import t
from .theme import key_value, note, pills


def _selected_candidate():
    analysis = st.session_state.get("analysis")
    if analysis is None:
        return None
    candidate_id = st.session_state.get("selected_candidate_id")
    for candidate in analysis.profile.candidates:
        if candidate.id == candidate_id:
            return candidate
    return analysis.profile.candidates[0] if analysis.profile.candidates else None


def _advanced_controls(lang: str, profile) -> dict:
    """Advanced-mode settings. Secrets use password inputs and are not persisted."""
    advanced = dict(st.session_state.get("advanced", {}))
    with st.expander("Request" if lang == "en" else "الطلب", expanded=False):
        columns = st.columns(2)
        advanced["method"] = columns[0].selectbox(
            "HTTP method", ["GET", "POST"], index=0, help="Most public data uses GET."
        )
        advanced["timeout"] = columns[1].number_input(
            "Timeout (seconds)",
            min_value=5.0,
            max_value=180.0,
            value=float(SETTINGS.limits.http_timeout),
        )
        advanced["headers_raw"] = st.text_area(
            "Extra headers (one per line, `Name: value`)",
            value=advanced.get("headers_raw", ""),
            height=70,
            help="Only send headers you are authorised to use. They are never saved in the recipe.",
        )
        advanced["token"] = st.text_input(
            "Bearer token / API key (optional)",
            value="",
            type="password",
            help="Kept in memory for this run only. Never written to logs, recipes or generated code.",
        )
        advanced["rps"] = st.slider(
            "Requests per second",
            min_value=0.2,
            max_value=5.0,
            value=float(SETTINGS.politeness.requests_per_second),
            step=0.1,
            help="Lower is politer. The source may rate-limit you if this is too high.",
        )

    with st.expander("Selectors" if lang == "en" else "المحددات", expanded=False):
        advanced["selector"] = st.text_input(
            "CSS selector for repeated items",
            value=advanced.get("selector", ""),
            help="Example: div.card . Leave empty to use the detected structure.",
        )
        advanced["xpath"] = st.text_input(
            "XPath (optional)",
            value=advanced.get("xpath", ""),
            help="Used instead of the CSS selector.",
        )
        advanced["records_path"] = st.text_input(
            "JSON records path",
            value=advanced.get("records_path", ""),
            help="Example: data.items — the path to the array of records in a JSON response.",
        )
        advanced["wait_for"] = st.text_input(
            "Wait for element (browser mode)",
            value=advanced.get("wait_for", ""),
            help="A CSS selector the browser waits for before reading the page.",
        )

    with st.expander("Pagination" if lang == "en" else "ترقيم الصفحات", expanded=False):
        detected = profile.pagination if profile else PaginationPlan()
        types = [item.value for item in PaginationType]
        advanced["pagination_type"] = st.selectbox(
            "Pagination type",
            types,
            index=types.index(detected.type.value),
            help="Detected automatically; override only if the detection was wrong.",
        )
        advanced["url_template"] = st.text_input(
            "URL template",
            value=detected.url_template or "",
            help="Use {page} where the page number goes.",
        )
        advanced["next_selector"] = st.text_input(
            "Next/Load-more selector", value=detected.next_selector or ""
        )
        advanced["cursor_path"] = st.text_input(
            "Cursor field path (APIs)", value=detected.cursor_path or ""
        )

    with st.expander("Engine" if lang == "en" else "المحرك", expanded=False):
        from ..routing.capability_registry import engine_instances

        options = ["(automatic)"] + [
            name for name, engine in engine_instances().items() if engine.available()
        ]
        choice = st.selectbox(
            "Engine preference",
            options,
            index=0,
            help="Automatic picks the cheapest reliable method. Override only when you know better.",
        )
        advanced["engine_preference"] = None if choice == "(automatic)" else choice

    st.session_state["advanced"] = advanced
    return advanced


def _build_request(lang: str) -> ExtractionRequest:
    analysis = st.session_state.get("analysis")
    profile = analysis.profile if analysis else None
    mode = st.session_state.get("mode", "auto")
    advanced = st.session_state.get("advanced", {}) if mode == "advanced" else {}

    pagination = (profile.pagination if profile else PaginationPlan()).model_copy()
    if advanced.get("pagination_type"):
        pagination = pagination.model_copy(
            update={
                "type": PaginationType(advanced["pagination_type"]),
                "url_template": advanced.get("url_template") or pagination.url_template,
                "next_selector": advanced.get("next_selector") or pagination.next_selector,
                "cursor_path": advanced.get("cursor_path") or pagination.cursor_path,
            }
        )

    follow = st.session_state.get("follow_pagination", False)
    max_pages = int(st.session_state.get("max_pages", 1)) if follow else 1
    if not follow:
        pagination = pagination.model_copy(update={"type": PaginationType.NONE})

    headers: dict[str, str] = {}
    for line in (advanced.get("headers_raw") or "").splitlines():
        if ":" in line:
            name, _, value = line.partition(":")
            if name.strip():
                headers[name.strip()] = value.strip()
    if advanced.get("token"):
        headers["Authorization"] = f"Bearer {advanced['token']}"

    return ExtractionRequest(
        url=st.session_state.get("url", ""),
        mode=mode,
        user_goal=st.session_state.get("goal") or None,
        preset=st.session_state.get("preset", "auto"),
        max_pages=max_pages,
        max_rows=st.session_state.get("max_rows") or None,
        respect_robots=st.session_state.get("respect_robots", True),
        allow_browser=st.session_state.get("allow_browser", True),
        allow_cloud=st.session_state.get("allow_cloud", False),
        allow_ai=st.session_state.get("allow_ai", False),
        ai_provider=st.session_state.get("ai_provider"),
        allow_agentic=st.session_state.get("allow_agentic", False),
        engine_preference=advanced.get("engine_preference"),
        selector=advanced.get("selector") or None,
        xpath=advanced.get("xpath") or None,
        records_path=advanced.get("records_path") or None,
        wait_for=advanced.get("wait_for") or None,
        add_provenance_columns=st.session_state.get("include_provenance", True),
        options=RequestOptions(
            method=advanced.get("method", "GET"),
            headers=headers,
            timeout=advanced.get("timeout") or None,
            requests_per_second=advanced.get("rps") or None,
        ),
        pagination=pagination,
        crawl=CrawlPlan(
            enabled=follow,
            scope="template" if follow else "single",
            max_pages=max_pages,
            same_domain_only=True,
        ),
    )


def render() -> None:
    lang = state.lang()
    analysis = st.session_state.get("analysis")
    if analysis is None:
        note(t("no_results_yet", lang))
        return

    candidate = _selected_candidate()
    profile = analysis.profile
    mode = st.session_state.get("mode", "auto")

    st.title(t("step_preview", lang) + " · " + t("step_extract", lang))

    # ------------------------------------------------------------------ scope
    with st.container(border=True):
        st.markdown(f"**{t('scope', lang)}**")
        columns = st.columns([2, 1, 1])
        follow = columns[0].toggle(
            t("several_pages", lang),
            value=st.session_state.get("follow_pagination", False),
            help=f"Detected pagination: {profile.pagination.type.value}"
            if lang == "en"
            else f"الترقيم المكتشف: {profile.pagination.type.value}",
        )
        st.session_state["follow_pagination"] = follow
        st.session_state["max_pages"] = columns[1].number_input(
            t("max_pages", lang),
            min_value=1,
            max_value=SETTINGS.limits.hard_max_pages,
            value=int(st.session_state.get("max_pages", 1)) if follow else 1,
            disabled=not follow,
        )
        rows_value = columns[2].number_input(
            t("max_rows", lang),
            min_value=0,
            max_value=SETTINGS.limits.max_rows,
            value=int(st.session_state.get("max_rows") or 0),
            help="0 means no extra limit beyond the safety cap."
            if lang == "en"
            else "0 يعني بلا حد إضافي عدا الحد الآمن.",
        )
        st.session_state["max_rows"] = int(rows_value) or None
        st.session_state["include_provenance"] = st.checkbox(
            "Add source columns (_source_url, _source_page, _retrieved_at)"
            if lang == "en"
            else "أضف أعمدة المصدر (_source_url، _source_page، _retrieved_at)",
            value=st.session_state.get("include_provenance", True),
        )

    if mode == "advanced":
        _advanced_controls(lang, profile)

    request = _build_request(lang)
    schema = schema_from_selection(analysis)

    # -------------------------------------------------------------- preflight
    try:
        summary = preflight(request, candidate, profile)
    except Exception as exc:
        state.show_error(exc, [(t("step_detect", lang), "detect")])
        return

    with st.container(border=True):
        st.markdown(f"### {t('preflight', lang)}")
        key_value("Detected source", summary["detected_source"])
        key_value(t("recommended_method", lang), summary["selected_method"])
        key_value("Estimated pages", str(summary["estimated_pages"]))
        key_value("Estimated requests", str(summary["estimated_requests"]))
        key_value("AI calls", str(summary["ai_calls"]))
        key_value("Cloud provider", summary["cloud_provider"])
        key_value("Robots status", summary["robots_status"])
        badges = [(summary["engine"], "info", "⚙")]
        badges.append(
            ("Local only", "ok", "✓")
            if summary["cost_mode"] != "metered"
            else ("Metered provider", "warn", "$")
        )
        if summary["uses_browser"]:
            badges.append(("Uses local browser", "warn", "◧"))
        pills(badges)
        st.markdown(
            f"**{t('why_this_method', lang)}** "
            + (summary["why_ar"] if lang == "ar" else summary["why"])
        )

    if summary["cost_mode"] == "metered":
        st.warning(
            "This route sends page content to an external provider and may be billed."
            if lang == "en"
            else "هذا المسار يرسل محتوى الصفحة إلى مزود خارجي وقد يكون مدفوعًا."
        )

    # ------------------------------------------------------------------ actions
    preview_column, run_column, back_column = st.columns([1, 1, 1])
    preview_clicked = preview_column.button(
        t("preview_extraction", lang), width="stretch", key="run_preview"
    )
    run_clicked = run_column.button(
        t("start_extraction", lang), type="primary", width="stretch", key="run_full"
    )
    if back_column.button(t("change_settings", lang), width="stretch", key="back_to_fields"):
        state.set_step("fields")
        st.rerun()

    if preview_clicked or run_clicked:
        _run(request, candidate, profile, schema, analysis, preview=preview_clicked, lang=lang)

    preview_outcome = st.session_state.get("preview_outcome")
    if preview_outcome is not None and not run_clicked:
        st.divider()
        st.markdown(f"**{t('preview_extraction', lang)}**")
        st.caption(
            f"{len(preview_outcome.clean_df):,} rows from {preview_outcome.result.pages_successful} page(s) · "
            f"engine: {preview_outcome.result.engine}"
        )
        st.dataframe(preview_outcome.clean_df.head(50), width="stretch", hide_index=True)
        if preview_outcome.mapping and preview_outcome.mapping.needs_review:
            st.warning(
                "Some requested fields need review: "
                + ", ".join(preview_outcome.mapping.unmatched or ["low-confidence matches"])
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "requested": m.requested,
                            "matched_column": m.matched_column or "—",
                            "match_type": m.method,
                            "confidence": m.confidence.value,
                        }
                        for m in preview_outcome.mapping.mappings
                    ]
                ),
                width="stretch",
                hide_index=True,
            )


def _run(request, candidate, profile, schema, analysis, *, preview: bool, lang: str) -> None:
    label = t("running", lang)
    with st.status(label, expanded=True) as status:
        progress_bar = st.progress(0.0)
        line = st.empty()

        def progress(current: int, total: int, url: str) -> None:
            progress_bar.progress(min(current / max(total, 1), 1.0))
            line.write(f"Page {current}/{total} · {url}")

        try:
            outcome = extract(
                request,
                candidate,
                profile=profile,
                schema=schema,
                logger=analysis.logger,
                run_id=analysis.run_id if not preview else None,
                progress=progress,
                preview=preview,
                preview_pages=int(st.session_state.get("preview_pages", 1)),
            )
        except Exception as exc:
            status.update(
                label="Extraction failed" if lang == "en" else "فشل الاستخراج", state="error"
            )
            state.show_error(
                exc,
                [(t("step_detect", lang), "detect"), (t("step_fields", lang), "fields")],
            )
            return

        progress_bar.progress(1.0)
        st.write(
            f"✓ {len(outcome.clean_df):,} rows collected from "
            f"{outcome.result.pages_successful} page(s)."
        )
        for warning in outcome.warnings[:5]:
            st.write(f"⚠ {warning}")
        status.update(
            label="Preview ready"
            if preview
            else ("Extraction complete" if lang == "en" else "اكتمل الاستخراج"),
            state="complete",
        )

    if preview:
        st.session_state["preview_outcome"] = outcome
        state.mark("preview", "done")
        st.rerun()
    else:
        st.session_state["outcome"] = outcome
        st.session_state["preview_outcome"] = None
        try:
            from ..service import persist

            persist(outcome)
        except Exception:
            pass  # history is a convenience; never block the result on it
        state.set_step("clean")
        st.rerun()
