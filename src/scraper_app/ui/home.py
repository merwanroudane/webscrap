"""Page 1 — Home / New extraction (spec section 19, 106.1-106.4).

Auto mode shows five controls at most: URL, optional request, preset, mode and
the Analyze button. Everything technical is elsewhere.
"""

from __future__ import annotations

import streamlit as st

from ..service import PRESETS, analyze
from . import state
from .demo import demo_url, ensure_demo_server
from .i18n import t
from .theme import card, note


def _mode_selector(lang: str) -> str:
    labels = {
        "auto": f"{t('auto', lang)} — {t('auto_help', lang)}",
        "guided": f"{t('guided', lang)} — {t('guided_help', lang)}",
        "advanced": f"{t('advanced', lang)} — {t('advanced_help', lang)}",
    }
    current = st.session_state.get("mode", "auto")
    choice = st.radio(
        t("mode", lang),
        options=list(labels),
        format_func=lambda key: labels[key],
        index=list(labels).index(current),
        horizontal=False,
        key="mode_radio",
    )
    st.session_state["mode"] = choice
    return choice


def render() -> None:
    lang = state.lang()
    st.title(t("app_title", lang))
    st.caption(t("app_tagline", lang))

    left, right = st.columns([3, 2], gap="large")

    with left:
        url = st.text_input(
            t("url_label", lang),
            value=st.session_state.get("url", ""),
            placeholder="https://example.org/statistics",
            help=t("url_help", lang),
            key="url_input",
        )
        goal = st.text_area(
            t("goal_label", lang),
            value=st.session_state.get("goal", ""),
            placeholder=t("goal_placeholder", lang),
            height=90,
            key="goal_input",
        )

        preset_labels = {
            key: value["label_ar" if lang == "ar" else "label_en"] for key, value in PRESETS.items()
        }
        preset = st.selectbox(
            t("preset", lang),
            options=list(preset_labels),
            format_func=lambda key: preset_labels[key],
            index=list(preset_labels).index(st.session_state.get("preset", "auto")),
            key="preset_select",
        )
        mode = _mode_selector(lang)

        with st.expander(
            "Access and privacy options" if lang == "en" else "خيارات الوصول والخصوصية",
            expanded=False,
        ):
            st.session_state["respect_robots"] = st.checkbox(
                "Respect robots.txt (recommended)"
                if lang == "en"
                else "احترام robots.txt (موصى به)",
                value=st.session_state.get("respect_robots", True),
                help=(
                    "robots.txt is the site owner's access signal. Turning this off is only for "
                    "sources you are authorised to collect."
                    if lang == "en"
                    else "robots.txt هو إشارة الوصول من صاحب الموقع. لا تعطّله إلا لمصادر مصرح لك بجمعها."
                ),
            )
            st.session_state["allow_browser"] = st.checkbox(
                "Allow browser rendering when needed"
                if lang == "en"
                else "السماح بعرض المتصفح عند الحاجة",
                value=st.session_state.get("allow_browser", True),
                help=(
                    "Used only when the data is not in the plain HTML. A local Chromium is "
                    "preferred; a configured remote browser is used instead when you select one. "
                    "Unticking this prevents any browser from running."
                )
                if lang == "en"
                else (
                    "يُستخدم فقط عندما لا تكون البيانات في HTML العادي. يُفضّل Chromium المحلي، "
                    "ويُستخدم متصفح بعيد مضبوط إذا اخترته. إلغاء التحديد يمنع تشغيل أي متصفح."
                ),
            )
            st.session_state["allow_cloud"] = st.checkbox(
                "Allow cloud providers (sends page content off this machine)"
                if lang == "en"
                else "السماح بمزودي السحابة (يرسل محتوى الصفحة خارج الجهاز)",
                value=st.session_state.get("allow_cloud", False),
            )

            from ..ai import service as ai_service

            ai_ready = ai_service.available_providers()
            st.session_state["allow_ai"] = st.checkbox(
                "Allow AI assistance when deterministic extraction is not enough"
                if lang == "en"
                else "السماح بمساعدة الذكاء الاصطناعي عندما لا يكفي الاستخراج الحتمي",
                value=st.session_state.get("allow_ai", False),
                disabled=not ai_ready,
                help=(
                    "No model provider is configured — add a key to enable this."
                    if not ai_ready
                    else "A bounded page excerpt is sent to the model. Deterministic parsing is always tried first."
                )
                if lang == "en"
                else (
                    "لا يوجد مزود نماذج مضبوط — أضف مفتاحًا لتفعيل هذا."
                    if not ai_ready
                    else "يُرسل مقتطف محدود من الصفحة إلى النموذج. يُجرَّب التحليل الحتمي أولًا دائمًا."
                ),
            )
            if ai_ready and st.session_state.get("allow_ai"):
                st.session_state["ai_provider"] = st.selectbox(
                    t("ai_provider", lang),
                    options=[p.name for p in ai_ready],
                    format_func=lambda name: next(
                        (p.label for p in ai_ready if p.name == name), name
                    ),
                    key="ai_provider_select",
                )
            st.session_state["allow_agentic"] = st.checkbox(
                t("agentic_mode", lang),
                value=st.session_state.get("allow_agentic", False),
                help="Only for pages that genuinely need clicking through steps. Never signs in "
                "or bypasses access controls."
                if lang == "en"
                else "فقط للصفحات التي تحتاج فعلًا للنقر عبر خطوات. لا يسجل الدخول ولا يتجاوز ضوابط الوصول.",
            )

        run_column, demo_column = st.columns([2, 1])
        analyze_clicked = run_column.button(
            t("analyze", lang), type="primary", width="stretch", key="analyze_button"
        )
        demo_clicked = demo_column.button(t("try_demo", lang), width="stretch", key="demo_button")

    with right:
        st.markdown(f"### {t('quick_start', lang)}")
        steps_en = [
            "Paste a URL",
            "Optionally describe the data you need",
            "Click Analyze",
            "Review the detected data",
            "Click Extract",
            "Download or explore",
        ]
        steps_ar = [
            "الصق رابطًا",
            "صف البيانات التي تريدها (اختياري)",
            "اضغط تحليل",
            "راجع البيانات المكتشفة",
            "اضغط استخراج",
            "نزّل أو استكشف",
        ]
        for index, line in enumerate(steps_ar if lang == "ar" else steps_en, start=1):
            st.markdown(f"{index}. {line}")

        st.markdown("")
        card(
            "Example requests" if lang == "en" else "أمثلة على الطلبات",
            "Extract country, year, inflation rate, GDP and source link. · "
            "Get the title, author and date of each article. · "
            "Collect product name, price and rating."
            if lang == "en"
            else "استخرج الدولة، السنة، معدل التضخم، الناتج المحلي، ورابط المصدر. · "
            "احصل على عنوان وكاتب وتاريخ كل مقال. · "
            "اجمع اسم المنتج والسعر والتقييم.",
        )
        note(
            "The demo runs against bundled offline fixtures, so you can learn the workflow "
            "without finding a live website first."
            if lang == "en"
            else "العرض التجريبي يعمل على ملفات محلية مرفقة، فتتعلم المسار دون الحاجة لموقع حقيقي."
        )

    if demo_clicked:
        ensure_demo_server()
        url = demo_url("/table.html")
        st.session_state["url"] = url
        st.session_state["goal"] = (
            "country, year, inflation" if lang == "en" else "الدولة، السنة، التضخم"
        )
        analyze_clicked = True
        goal = st.session_state["goal"]

    if analyze_clicked:
        if not (url or "").strip():
            st.warning(
                "Please paste a website address first."
                if lang == "en"
                else "الرجاء لصق عنوان الموقع أولًا."
            )
            return
        st.session_state["url"] = url
        st.session_state["goal"] = goal
        st.session_state["preset"] = preset
        st.session_state["mode"] = mode
        st.session_state["last_error"] = None

        failure: Exception | None = None
        with st.status(
            "Analyzing the source…" if lang == "en" else "جارٍ تحليل المصدر…", expanded=True
        ) as status:
            try:
                st.write(
                    "Checking the address and access rules…"
                    if lang == "en"
                    else "فحص العنوان وقواعد الوصول…"
                )
                outcome = analyze(
                    url,
                    user_goal=goal,
                    respect_robots=st.session_state.get("respect_robots", True),
                    # The researcher's choice governs profiling too: with the
                    # box unticked, no browser probe may run even on a page
                    # that looks JavaScript-heavy.
                    use_browser=None if st.session_state.get("allow_browser", True) else False,
                    preset=preset,
                    allow_ai=st.session_state.get("allow_ai", False),
                    ai_provider=st.session_state.get("ai_provider"),
                )
                st.write(
                    f"Found {len(outcome.profile.candidates)} candidate dataset(s)."
                    if lang == "en"
                    else f"تم العثور على {len(outcome.profile.candidates)} مجموعة بيانات محتملة."
                )
                st.session_state["analysis"] = outcome
                st.session_state["outcome"] = None
                st.session_state["selected_candidate_id"] = outcome.profile.candidates[0].id
                status.update(
                    label="Analysis complete" if lang == "en" else "اكتمل التحليل", state="complete"
                )
            except Exception as exc:  # shown as a readable panel, never a traceback
                status.update(
                    label="Analysis failed" if lang == "en" else "فشل التحليل", state="error"
                )
                st.session_state["last_error"] = exc
                state.mark("source", "review")
                failure = exc

        # The explanation is rendered outside the status container: inside it,
        # the panel would be hidden the moment the status collapses, leaving the
        # user with a bare "Analysis failed" line and no next step.
        if failure is not None:
            state.show_error(failure)
            return

        state.set_step("detect")
        st.rerun()

    if st.session_state.get("last_error") is not None:
        state.show_error(st.session_state["last_error"])
