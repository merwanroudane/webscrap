"""Result workspace — Data | Variables | Quality | Charts | Sources | Recipe |
Code | Downloads | Diagnostics (spec section 106.10).

Readable tables, metrics and cards first. Raw JSON, selectors and logs live
only in the Diagnostics tab and in expanders.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..config import SETTINGS
from ..data import provenance as provenance_module
from ..export import exporters
from ..reproducibility import recipe as recipe_module
from ..reproducibility.report_generator import citation_text
from ..service import build_bundle
from ..visualize import charts, crawl_graph
from . import cleaning as cleaning_ui
from . import state
from .i18n import t
from .theme import card, key_value, note, pills


def render() -> None:
    lang = state.lang()
    outcome = st.session_state.get("outcome")
    if outcome is None:
        note(t("no_results_yet", lang))
        return

    frame = outcome.clean_df
    quality = outcome.quality

    st.title(outcome.candidate.title if outcome.candidate else t("tab_data", lang))
    columns = st.columns(4)
    columns[0].metric(t("rows", lang), f"{quality.rows:,}")
    columns[1].metric(t("columns", lang), quality.columns)
    columns[2].metric(t("missing_cells", lang), f"{quality.missing_pct}%")
    columns[3].metric(t("duplicates", lang), f"{quality.duplicate_rows:,}")

    pills(
        [
            (outcome.result.engine, "info", "⚙"),
            (
                f"{outcome.result.pages_successful}/{outcome.result.pages_requested} pages",
                "neutral",
                "▤",
            ),
            (f"recipe {outcome.recipe_hash}", "neutral", "#"),
        ]
    )

    tabs = st.tabs(
        [
            t("tab_data", lang),
            t("tab_variables", lang),
            t("tab_quality", lang),
            t("tab_charts", lang),
            t("tab_sources", lang),
            t("tab_recipe", lang),
            t("tab_code", lang),
            t("tab_downloads", lang),
            t("tab_diagnostics", lang),
        ]
    )

    with tabs[0]:
        _data_tab(outcome, frame, lang)
    with tabs[1]:
        _variables_tab(outcome, lang)
    with tabs[2]:
        _quality_tab(outcome, lang)
    with tabs[3]:
        _charts_tab(frame, lang)
    with tabs[4]:
        _sources_tab(outcome, lang)
    with tabs[5]:
        _recipe_tab(outcome, lang)
    with tabs[6]:
        _code_tab(outcome, lang)
    with tabs[7]:
        _downloads_tab(outcome, frame, lang)
    with tabs[8]:
        _diagnostics_tab(outcome, lang)


# --------------------------------------------------------------------------- tabs
def _data_tab(outcome, frame: pd.DataFrame, lang: str) -> None:
    controls = st.columns([2, 2, 1])
    search = controls[0].text_input(
        "Search" if lang == "en" else "بحث", key="data_search", placeholder="filter rows…"
    )
    visible = controls[1].multiselect(
        "Visible columns" if lang == "en" else "الأعمدة الظاهرة",
        options=[str(c) for c in frame.columns],
        default=[str(c) for c in frame.columns if not str(c).startswith("_")][:12]
        or [str(c) for c in frame.columns][:12],
        key="data_columns",
    )
    hide_provenance = controls[2].toggle(
        "Hide source columns" if lang == "en" else "إخفاء أعمدة المصدر",
        value=True,
        key="hide_prov",
    )

    view = frame
    if search:
        mask = (
            view.astype(str)
            .apply(lambda column: column.str.contains(search, case=False, na=False))
            .any(axis=1)
        )
        view = view[mask]
    keep = [c for c in (visible or list(frame.columns)) if c in frame.columns]
    if hide_provenance:
        keep = [c for c in keep if not str(c).startswith("_")]
    if keep:
        view = view[keep]

    limit = SETTINGS.limits.max_preview_rows
    st.caption(
        f"Showing {min(len(view), limit):,} of {len(frame):,} rows"
        if lang == "en"
        else f"عرض {min(len(view), limit):,} من {len(frame):,} صفًا"
    )
    st.dataframe(view.head(limit), width="stretch", hide_index=True)

    if outcome.warnings:
        with st.expander("Warnings from this run" if lang == "en" else "تحذيرات هذا التشغيل"):
            for warning in outcome.warnings:
                st.markdown(f"- {warning}")


def _variables_tab(outcome, lang: str) -> None:
    st.markdown(f"**{t('tab_variables', lang)}**")
    st.caption(
        "Each variable records whether its name came from the source, a heuristic, you, or AI."
        if lang == "en"
        else "كل متغير يسجّل مصدر اسمه: المصدر نفسه، أو استدلال، أو أنت، أو الذكاء الاصطناعي."
    )
    st.dataframe(outcome.dictionary, width="stretch", hide_index=True)

    if outcome.mapping and outcome.mapping.mappings:
        with st.expander("Field mapping" if lang == "en" else "ربط الحقول", expanded=False):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "requested": m.requested,
                            "matched_column": m.matched_column or "—",
                            "match_type": m.method,
                            "confidence": m.confidence.value,
                            "sample": m.sample or "",
                        }
                        for m in outcome.mapping.mappings
                    ]
                ),
                width="stretch",
                hide_index=True,
            )


def _quality_tab(outcome, lang: str) -> None:
    quality = outcome.quality
    for warning in quality.warnings:
        st.warning(warning)
    if quality.schema_drift:
        st.warning(
            ("Schema drift detected: " if lang == "en" else "تم رصد اختلاف في المخطط: ")
            + "; ".join(quality.schema_drift[:4])
        )
    st.dataframe(pd.DataFrame(quality.column_stats), width="stretch", hide_index=True)

    if quality.conversion_failures:
        st.markdown(f"**{'Conversion failures' if lang == 'en' else 'حالات فشل التحويل'}**")
        st.dataframe(
            pd.DataFrame(
                [{"column": k, "failed_values": v} for k, v in quality.conversion_failures.items()]
            ),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "These values were left unchanged rather than silently turned into missing data."
            if lang == "en"
            else "تُركت هذه القيم كما هي بدل تحويلها صامتًا إلى قيم ناقصة."
        )

    st.divider()
    cleaning_ui.render_panel(outcome, lang)


def _charts_tab(frame: pd.DataFrame, lang: str) -> None:
    suggestions = charts.suggest(frame)
    if suggestions:
        st.markdown(f"**{'Recommended charts' if lang == 'en' else 'رسوم مقترحة'}**")
        labels = [s.title for s in suggestions]
        chosen = st.radio(
            "Suggestion",
            labels,
            horizontal=True,
            label_visibility="collapsed",
            key="chart_suggestion",
        )
        suggestion = suggestions[labels.index(chosen)]
        st.caption(suggestion.reason)
        st.plotly_chart(
            charts.build_chart(
                frame, suggestion.kind, x=suggestion.x, y=suggestion.y, title=suggestion.title
            ),
            width="stretch",
        )

    with st.expander(
        "Build your own chart" if lang == "en" else "أنشئ رسمك الخاص", expanded=not suggestions
    ):
        columns = st.columns(4)
        kind = columns[0].selectbox(
            "Chart type", ["bar", "line", "scatter", "histogram", "box", "heatmap", "frequency"]
        )
        options = ["(none)"] + [str(c) for c in frame.columns]
        x = columns[1].selectbox("X", options, index=1 if len(options) > 1 else 0)
        y = columns[2].selectbox("Y", options, index=2 if len(options) > 2 else 0)
        color = columns[3].selectbox("Colour / group", options, index=0)
        aggregation = st.selectbox(
            "Aggregation", ["none", "sum", "mean", "count", "median"], index=0
        )
        st.plotly_chart(
            charts.build_chart(
                frame,
                kind,
                x=None if x == "(none)" else x,
                y=None if y == "(none)" else y,
                color=None if color == "(none)" else color,
                aggregation=aggregation,
            ),
            width="stretch",
        )

    with st.expander("Automatic summaries" if lang == "en" else "ملخصات تلقائية", expanded=False):
        numeric = charts.numeric_summary(frame)
        if not numeric.empty:
            st.markdown("**Numeric**")
            st.dataframe(numeric, width="stretch", hide_index=True)
        categorical = charts.categorical_summary(frame)
        if not categorical.empty:
            st.markdown("**Categorical**")
            st.dataframe(categorical, width="stretch", hide_index=True)


def _sources_tab(outcome, lang: str) -> None:
    provenance = outcome.provenance
    key_value("Source URL", provenance.source_url)
    key_value("Final URL", provenance.final_url)
    key_value("Retrieved at", provenance.retrieved_at.isoformat())
    key_value("Engine", provenance.engine)
    key_value("Why this method", provenance.route_rationale)
    key_value("robots.txt", f"{provenance.robots_status} ({provenance.robots_url or '—'})")
    key_value("User agent", provenance.user_agent)
    key_value(
        "Pages requested / successful",
        f"{provenance.pages_requested} / {provenance.pages_successful}",
    )

    urls = list(dict.fromkeys(outcome.result.source_urls))
    if len(urls) > 1:
        st.markdown(f"**{'Pages collected' if lang == 'en' else 'الصفحات المجمعة'}**")
        st.dataframe(pd.DataFrame({"url": urls}), width="stretch", hide_index=True)
        graph = crawl_graph.build_graph(crawl_graph.edges_from_sources(urls, outcome.request.url))
        st.plotly_chart(crawl_graph.render(graph), width="stretch")

    st.markdown(f"**{'Citation' if lang == 'en' else 'الاقتباس'}**")
    st.code(citation_text(provenance, outcome.recipe.get("name", "Dataset")), language="text")


def _recipe_tab(outcome, lang: str) -> None:
    recipe = outcome.recipe
    key_value("Name", recipe.get("name", ""))
    key_value("Engine", recipe.get("engine", ""))
    key_value("Pagination", str((recipe.get("pagination") or {}).get("type", "none")))
    key_value("Max pages", str((recipe.get("limits") or {}).get("max_pages", 1)))
    key_value("Recipe hash", outcome.recipe_hash)
    st.caption(
        "Recipes never contain credentials, cookies or tokens."
        if lang == "en"
        else "الوصفات لا تحتوي أبدًا على بيانات اعتماد أو كوكيز أو رموز."
    )
    with st.expander("Raw recipe (YAML)", expanded=False):
        st.code(recipe_module.to_yaml_bytes(recipe).decode("utf-8"), language="yaml")

    columns = st.columns(2)
    columns[0].download_button(
        "extraction_recipe.json",
        data=recipe_module.to_json_bytes(recipe),
        file_name="extraction_recipe.json",
        mime="application/json",
        width="stretch",
    )
    columns[1].download_button(
        "extraction_recipe.yaml",
        data=recipe_module.to_yaml_bytes(recipe),
        file_name="extraction_recipe.yaml",
        mime="text/yaml",
        width="stretch",
    )


def _code_tab(outcome, lang: str) -> None:
    st.caption(
        "This script matches the engine that actually ran and contains no credentials."
        if lang == "en"
        else "هذا السكربت يطابق المحرك الذي عمل فعلًا ولا يحتوي على بيانات اعتماد."
    )
    st.code(outcome.script, language="python")
    st.download_button(
        "generated_scraper.py",
        data=outcome.script.encode("utf-8"),
        file_name="generated_scraper.py",
        mime="text/x-python",
    )


def _downloads_tab(outcome, frame: pd.DataFrame, lang: str) -> None:
    categories = {
        "common": t("common_formats", lang),
        "research": t("research_formats", lang),
        "database": t("database_formats", lang),
    }
    for category, label in categories.items():
        st.markdown(f"**{label}**")
        formats = [
            (fmt, support)
            for fmt, support in exporters.available_formats(frame)
            if fmt.category == category
        ]
        columns = st.columns(min(4, max(len(formats), 1)))
        for index, (fmt, support) in enumerate(formats):
            column = columns[index % len(columns)]
            with column:
                if support.ok:
                    try:
                        payload = exporters.build(frame, fmt.key)
                    except Exception as exc:
                        st.button(fmt.label, disabled=True, width="stretch")
                        st.caption(str(exc)[:120])
                        continue
                    st.download_button(
                        fmt.label,
                        data=payload,
                        file_name=f"dataset{fmt.extension}",
                        mime=fmt.mime,
                        width="stretch",
                        key=f"dl_{fmt.key}",
                    )
                else:
                    st.button(fmt.label, disabled=True, width="stretch", key=f"dis_{fmt.key}")
                    st.caption(f"⚠ {support.reason}")
        st.write("")

    st.markdown(f"**{t('reproducible_formats', lang)}**")
    columns = st.columns(4)
    columns[0].download_button(
        "data_dictionary.csv",
        data=outcome.dictionary.to_csv(index=False).encode("utf-8-sig"),
        file_name="data_dictionary.csv",
        mime="text/csv",
        width="stretch",
    )
    columns[1].download_button(
        "provenance.json",
        data=provenance_module.to_json_bytes(outcome.provenance),
        file_name="provenance.json",
        mime="application/json",
        width="stretch",
    )
    columns[2].download_button(
        "provenance.csv",
        data=provenance_module.to_csv_bytes(outcome.provenance),
        file_name="provenance.csv",
        mime="text/csv",
        width="stretch",
    )
    columns[3].download_button(
        "generated_scraper.py",
        data=outcome.script.encode("utf-8"),
        file_name="generated_scraper.py",
        mime="text/x-python",
        width="stretch",
        key="dl_script_downloads",
    )

    st.divider()
    include_raw = st.checkbox(
        "Include the raw (pre-cleaning) dataset in the package"
        if lang == "en"
        else "تضمين البيانات الخام (قبل التنظيف) في الحزمة",
        value=True,
    )
    st.download_button(
        t("download_bundle", lang),
        data=build_bundle(outcome, include_raw=include_raw),
        file_name=f"research_bundle_{outcome.recipe_hash}.zip",
        mime="application/zip",
        type="primary",
        width="stretch",
    )


def _diagnostics_tab(outcome, lang: str) -> None:
    decision = outcome.decision
    card(
        f"{'Selected engine' if lang == 'en' else 'المحرك المختار'}: {decision.engine}",
        decision.rationale_ar if lang == "ar" else decision.rationale,
    )
    if decision.steps:
        st.markdown(f"**{'Route steps' if lang == 'en' else 'خطوات المسار'}**")
        for step in decision.steps:
            st.markdown(f"- {step}")
    if decision.alternatives:
        st.markdown(f"**{'Alternatives considered' if lang == 'en' else 'بدائل تم النظر فيها'}**")
        st.dataframe(pd.DataFrame(decision.alternatives), width="stretch", hide_index=True)

    key_value("Elapsed", f"{outcome.result.elapsed_ms:,} ms")
    key_value(
        "Fallback chain",
        ", ".join(outcome.result.metadata.get("fallback_chain", [decision.engine])),
    )
    key_value("Run id", outcome.run_id)

    st.markdown(f"**{'Technical log (sanitized)' if lang == 'en' else 'السجل التقني (منقّح)'}**")
    rows = outcome.logger.rows()
    if rows:
        st.dataframe(
            pd.DataFrame(rows)[["time", "level", "component", "event", "engine", "url", "status"]],
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("No log entries for this run.")
