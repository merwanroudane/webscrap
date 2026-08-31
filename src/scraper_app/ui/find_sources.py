"""Find sources page (audit section P).

Search for candidate sources, read them as cards, then hand one to the ordinary
Analyze workflow. Nothing is fetched or extracted here — approving a source is
always the researcher's click.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..discovery import source_finder
from . import state
from .i18n import t
from .theme import card, note, pills


def render() -> None:
    lang = state.lang()
    st.title(t("find_sources", lang))
    st.caption(
        "Search for pages that might hold your data, then send one to the analyzer. "
        "Nothing is collected until you choose a source."
        if lang == "en"
        else "ابحث عن صفحات قد تحتوي بياناتك، ثم أرسل واحدة إلى المحلل. "
        "لا يتم جمع أي شيء حتى تختار مصدرًا."
    )

    providers = source_finder.available_providers()
    ready = [p for p in providers if p["status"].startswith("✓")]

    if not ready:
        note(
            "No discovery provider is configured. This step is optional — you can always paste a "
            "URL directly on the Source page."
            if lang == "en"
            else "لا يوجد مزود اكتشاف مضبوط. هذه الخطوة اختيارية — يمكنك دائمًا لصق الرابط مباشرة في صفحة المصدر."
        )
        st.dataframe(pd.DataFrame(providers), width="stretch", hide_index=True)
        with st.expander(
            "How to enable source discovery" if lang == "en" else "كيفية تفعيل اكتشاف المصادر"
        ):
            st.code(
                "# add one of these to your .env file\n"
                "TAVILY_API_KEY=...\n"
                "EXA_API_KEY=...\n"
                "JINA_API_KEY=...",
                language="bash",
            )
        return

    pills([(p["provider"], "ok", "✓") for p in ready])

    columns = st.columns([3, 1, 1])
    query = columns[0].text_input(
        "What are you looking for?" if lang == "en" else "عمّ تبحث؟",
        placeholder="annual inflation rate by country statistics table"
        if lang == "en"
        else "جدول إحصائي لمعدل التضخم السنوي حسب الدولة",
        key="discovery_query",
    )
    provider_name = columns[1].selectbox(
        "Provider" if lang == "en" else "المزود",
        options=[p["id"] for p in ready],
        format_func=lambda pid: next((p["provider"] for p in ready if p["id"] == pid), pid),
        key="discovery_provider",
    )
    max_results = columns[2].number_input(
        "Results" if lang == "en" else "النتائج", min_value=3, max_value=25, value=10
    )

    domains_raw = st.text_input(
        "Limit to domains (optional, comma separated)"
        if lang == "en"
        else "حصر النطاقات (اختياري، مفصولة بفواصل)",
        placeholder="worldbank.org, imf.org",
    )

    if st.button(t("search_sources", lang), type="primary", disabled=not query.strip()):
        with st.status("Searching…" if lang == "en" else "جارٍ البحث…", expanded=False) as status:
            try:
                outcome = source_finder.find_sources(
                    query,
                    provider_name=provider_name,
                    max_results=int(max_results),
                    include_domains=[d.strip() for d in domains_raw.split(",") if d.strip()],
                )
                st.session_state["discovery_outcome"] = outcome
                status.update(label=f"{len(outcome.candidates)} sources found", state="complete")
            except Exception as exc:
                status.update(label="Search failed", state="error")
                state.show_error(exc)
                return

    outcome = st.session_state.get("discovery_outcome")
    if outcome is None:
        return

    for warning in outcome.warnings:
        st.warning(warning)

    for index, candidate in enumerate(outcome.candidates):
        with st.container(border=True):
            left, right = st.columns([5, 1])
            with left:
                st.markdown(f"**{candidate.title or candidate.domain}**")
                st.caption(candidate.domain)
                if candidate.snippet:
                    st.write(candidate.snippet[:300])
                badges = [(candidate.provider, "info", "🔎")]
                if candidate.published:
                    badges.append((candidate.published[:10], "neutral", "📅"))
                if candidate.score is not None:
                    badges.append((f"relevance {candidate.score:.2f}", "neutral", "#"))
                pills(badges)
                st.code(candidate.url, language="text")
            with right:
                if st.button(
                    t("analyze_this", lang), key=f"analyze_source_{index}", width="stretch"
                ):
                    st.session_state["url"] = candidate.url
                    st.session_state["page_select"] = "workflow"
                    state.set_step("source")
                    st.rerun()

    if outcome.candidates:
        with st.expander("All results as a table" if lang == "en" else "كل النتائج كجدول"):
            st.dataframe(pd.DataFrame(outcome.rows), width="stretch", hide_index=True)

    card(
        "Discovery is not extraction" if lang == "en" else "الاكتشاف ليس استخراجًا",
        "These results were returned by a search provider. Open a source, check that it really "
        "holds the data you need, then analyze it."
        if lang == "en"
        else "هذه النتائج أعادها مزود بحث. افتح المصدر، وتأكد أنه يحتوي فعلًا على البيانات، ثم حلّله.",
    )
