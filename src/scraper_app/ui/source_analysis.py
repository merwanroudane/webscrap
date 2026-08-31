"""Page 2 — Source analysis (spec section 19).

Shows what the profiler found as readable metrics, candidate cards and tabs.
Technical details are collapsed by default for beginners.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..models import DatasetKind
from . import state
from .i18n import t
from .theme import card, confidence_badge, key_value, note, pills, robots_badge

_KIND_ICON = {
    DatasetKind.FILE: "📄",
    DatasetKind.API: "🔗",
    DatasetKind.TABLE: "▦",
    DatasetKind.REPEATED: "▤",
    DatasetKind.STRUCTURED: "🏷",
    DatasetKind.ARTICLE: "📰",
    DatasetKind.FEED: "📡",
    DatasetKind.LINKS: "🔍",
    DatasetKind.DOCUMENT: "📕",
}


def render() -> None:
    lang = state.lang()
    analysis = st.session_state.get("analysis")
    if analysis is None:
        note(t("no_results_yet", lang))
        return

    profile = analysis.profile
    st.title(t("analysis_title", lang))
    st.caption(profile.final_url)

    columns = st.columns(5)
    columns[0].metric(t("status", lang), f"{profile.status_code} · {t('accessible', lang)}")
    columns[1].metric(
        t("content", lang),
        ("HTML + JS" if profile.requires_js else "HTML")
        if profile.is_html
        else (profile.file_format or profile.content_type or "—"),
    )
    columns[2].metric(t("tables_found", lang), profile.table_count)
    columns[3].metric(t("json_found", lang), len(profile.api_candidates))
    columns[4].metric(t("links_found", lang), profile.internal_link_count)

    difficulty_kind = {"low": "ok", "medium": "warn", "high": "err"}[profile.difficulty]
    difficulty_symbol = {"low": "✓", "medium": "≈", "high": "!"}[profile.difficulty]
    pills(
        [
            robots_badge(profile.robots.state, lang),
            (f"{t('difficulty', lang)}: {profile.difficulty}", difficulty_kind, difficulty_symbol),
            confidence_badge(profile.confidence, lang),
        ]
    )

    if profile.warnings:
        for warning in profile.warnings:
            st.warning(warning)
    if profile.challenge_detected:
        st.warning(
            "This source shows an interactive verification challenge. The app does not bypass such checks."
            if lang == "en"
            else "هذا المصدر يعرض تحققًا تفاعليًا. التطبيق لا يتجاوز هذه الفحوص."
        )
    if profile.login_wall:
        st.warning(
            "This page appears to require a signed-in session."
            if lang == "en"
            else "يبدو أن هذه الصفحة تتطلب جلسة مسجّلة الدخول."
        )

    tabs = st.tabs(
        [
            t("detected_datasets", lang),
            t("overview", lang),
            "APIs / JSON",
            "Tables" if lang == "en" else "الجداول",
            "Links & files" if lang == "en" else "الروابط والملفات",
            t("technical_details", lang),
        ]
    )

    with tabs[0]:
        _render_candidates(profile, lang)
    with tabs[1]:
        _render_overview(profile, lang)
    with tabs[2]:
        _render_apis(profile, lang)
    with tabs[3]:
        _render_tables(profile, lang)
    with tabs[4]:
        _render_links(profile, lang)
    with tabs[5]:
        _render_technical(profile, lang)


def _render_candidates(profile, lang: str) -> None:
    if not profile.candidates:
        note(t("no_results_yet", lang))
        return

    for candidate in profile.candidates:
        with st.container(border=True):
            head, action = st.columns([5, 1])
            with head:
                icon = _KIND_ICON.get(candidate.kind, "•")
                st.markdown(f"**{icon} {candidate.title}**")
                st.caption(candidate.description or candidate.why)
                pills(
                    [
                        confidence_badge(candidate.confidence, lang),
                        (candidate.engine, "info", "⚙"),
                        (
                            f"{candidate.rows_estimate:,} {t('rows', lang).lower()}"
                            if candidate.rows_estimate
                            else t("sample", lang),
                            "neutral",
                            "#",
                        ),
                    ]
                )
                if candidate.columns:
                    st.caption(
                        f"{t('columns', lang)}: " + ", ".join(str(c) for c in candidate.columns[:10])
                    )
                if candidate.sample_rows:
                    with st.expander(t("sample", lang), expanded=False):
                        st.dataframe(
                            pd.DataFrame(candidate.sample_rows),
                            width="stretch",
                            hide_index=True,
                        )
            with action:
                if st.button(
                    t("use_this", lang),
                    key=f"use_{candidate.id}",
                    type="primary" if candidate.id == profile.candidates[0].id else "secondary",
                    width="stretch",
                ):
                    st.session_state["selected_candidate_id"] = candidate.id
                    state.set_step("fields")
                    st.rerun()


def _render_overview(profile, lang: str) -> None:
    key_value("Final URL", profile.final_url)
    key_value("Content type", profile.content_type or "—")
    key_value("Page title", profile.title or "—")
    key_value(t("recommended_method", lang), profile.recommended_engine or "—")
    key_value("Structured metadata", ", ".join(profile.structured_types[:8]) or "none found")
    key_value("Pagination", f"{profile.pagination.type.value} ({profile.pagination.detected_from or 'not detected'})")
    key_value("Readable text", f"{profile.article_chars:,} characters")
    key_value("Analysis time", f"{profile.elapsed_ms:,} ms")

    if profile.js_evidence:
        st.markdown(
            f"**{'Why JavaScript may be needed' if lang == 'en' else 'لماذا قد تلزم JavaScript'}**"
        )
        for line in profile.js_evidence:
            st.markdown(f"- {line}")


def _render_apis(profile, lang: str) -> None:
    if not profile.api_candidates:
        note(
            "No JSON endpoint was observed for this page."
            if lang == "en"
            else "لم يتم رصد أي نقطة JSON لهذه الصفحة."
        )
        return
    rows = [
        {
            "url": api.url,
            "records": api.record_count,
            "path": api.records_path or "",
            "fields": ", ".join(api.sample_keys[:8]),
            "found_by": api.discovered_by,
            "confidence": api.confidence.value,
        }
        for api in profile.api_candidates
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    note(
        "When a stable JSON endpoint exists, using it directly is faster and easier to reproduce "
        "than scraping the rendered page."
        if lang == "en"
        else "عند وجود نقطة JSON مستقرة، استخدامها مباشرة أسرع وأسهل في إعادة الإنتاج من كشط الصفحة."
    )


def _render_tables(profile, lang: str) -> None:
    if not profile.tables:
        note("No HTML table found." if lang == "en" else "لا يوجد جدول HTML.")
        return
    rows = [
        {
            "table": table.index + 1,
            "rows": table.rows,
            "columns": table.columns,
            "title": table.caption or table.preceding_heading or "",
            "confidence": table.confidence.value,
        }
        for table in profile.tables
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _render_links(profile, lang: str) -> None:
    if profile.downloadable_files:
        st.markdown(f"**{'Downloadable files' if lang == 'en' else 'ملفات قابلة للتنزيل'}**")
        st.dataframe(pd.DataFrame(profile.downloadable_files), width="stretch", hide_index=True)
    if profile.feeds:
        st.markdown(f"**{'Feeds' if lang == 'en' else 'التغذيات'}**")
        st.dataframe(pd.DataFrame({"feed": profile.feeds}), width="stretch", hide_index=True)
    if profile.internal_links:
        with st.expander(
            f"{t('links_found', lang)} ({profile.internal_link_count})", expanded=False
        ):
            st.dataframe(
                pd.DataFrame({"url": profile.internal_links[:500]}),
                width="stretch",
                hide_index=True,
            )
    if not (profile.downloadable_files or profile.feeds or profile.internal_links):
        note("No links were found." if lang == "en" else "لم يتم العثور على روابط.")


def _render_technical(profile, lang: str) -> None:
    card(
        "This section is for troubleshooting" if lang == "en" else "هذا القسم للتشخيص",
        "Nothing here is required to extract data."
        if lang == "en"
        else "لا شيء هنا مطلوب لاستخراج البيانات.",
    )
    with st.expander("Source profile (JSON)", expanded=False):
        payload = profile.model_dump(mode="json")
        payload["internal_links"] = payload.get("internal_links", [])[:25]
        st.json(payload, expanded=False)
