"""Help and onboarding (spec section 106.9)."""

from __future__ import annotations

import streamlit as st

from ..config import APP_AUTHOR, APP_AUTHOR_URL, APP_VERSION
from . import state
from .demo import demo_pages, demo_url, ensure_demo_server
from .i18n import t
from .theme import card, note

GLOSSARY_EN = [
    ("API", "A machine-readable address that returns data directly, usually as JSON. The most reliable source when one exists."),
    ("Table", "An HTML table on a page. Read directly into rows and columns, no AI needed."),
    ("Repeated structure", "A block (card, row, listing) that repeats. Each block becomes one row of your dataset."),
    ("Pagination", "How a site splits a long list across pages: page numbers, a Next link, a Load more button or infinite scroll."),
    ("CSS selector", "A short pattern that points at page elements, e.g. div.card. You never need one in Auto mode."),
    ("XPath", "Another way to point at page elements, useful for unusual layouts."),
    ("JSONPath", "A path into a JSON document, e.g. data.items, telling the app where the records are."),
    ("robots.txt", "A file where a site states which paths automated tools should not read. Respected by default."),
    ("Provenance", "The record of where each row came from and how it was collected — essential for research."),
]

GLOSSARY_AR = [
    ("API", "عنوان يعيد البيانات مباشرة بصيغة JSON غالبًا. أفضل مصدر عند توفره."),
    ("جدول", "جدول HTML في الصفحة. يُقرأ مباشرة إلى صفوف وأعمدة بدون ذكاء اصطناعي."),
    ("بنية متكررة", "كتلة (بطاقة، صف، عنصر قائمة) تتكرر. كل كتلة تصبح صفًا في بياناتك."),
    ("ترقيم الصفحات", "طريقة تقسيم القائمة الطويلة: أرقام صفحات، رابط التالي، زر المزيد، أو تمرير لا نهائي."),
    ("محدد CSS", "نمط قصير يشير إلى عناصر الصفحة مثل div.card. لا تحتاجه في الوضع التلقائي."),
    ("XPath", "طريقة أخرى للإشارة إلى عناصر الصفحة، مفيدة للتخطيطات غير المعتادة."),
    ("JSONPath", "مسار داخل مستند JSON مثل data.items يحدد مكان السجلات."),
    ("robots.txt", "ملف يحدد فيه الموقع المسارات التي يجب ألا تقرأها الأدوات الآلية. يُحترم افتراضيًا."),
    ("الإسناد", "سجل مصدر كل صف وكيفية جمعه — ضروري للبحث العلمي."),
]


def render() -> None:
    lang = state.lang()
    st.title(t("help", lang))

    card(
        t("quick_start", lang),
        "1. Paste a URL · 2. Describe the data you need (optional) · 3. Analyze · "
        "4. Review the detected datasets · 5. Preview · 6. Extract · 7. Clean, chart and download."
        if lang == "en"
        else "1. الصق رابطًا · 2. صف البيانات (اختياري) · 3. حلّل · 4. راجع المجموعات المكتشفة · "
        "5. عايِن · 6. استخرج · 7. نظّف وارسم ونزّل.",
    )

    st.markdown(f"### {'Try the offline demo' if lang == 'en' else 'جرّب العرض التجريبي'}")
    st.caption(
        "These pages are bundled with the project, so the demo always behaves the same way."
        if lang == "en"
        else "هذه الصفحات مرفقة مع المشروع، لذا يتصرف العرض التجريبي بنفس الطريقة دائمًا."
    )
    for label, path in demo_pages():
        columns = st.columns([3, 1])
        columns[0].markdown(f"**{label}** · `{path}`")
        if columns[1].button("Use", key=f"demo_{path}", width="stretch"):
            ensure_demo_server()
            st.session_state["url"] = demo_url(path)
            st.session_state["step"] = "source"
            st.rerun()

    st.markdown(f"### {'Glossary' if lang == 'en' else 'مصطلحات'}")
    for term, definition in GLOSSARY_AR if lang == "ar" else GLOSSARY_EN:
        with st.expander(term):
            st.write(definition)

    note(
        "This tool collects public data. Always check the source terms of use, licence and any "
        "personal-data restrictions before redistributing a dataset, and cite the original publisher."
        if lang == "en"
        else "تجمع هذه الأداة بيانات عامة. تحقق دائمًا من شروط الاستخدام والترخيص وقيود البيانات "
        "الشخصية قبل إعادة نشر أي مجموعة بيانات، واذكر الناشر الأصلي."
    )

    st.divider()
    st.markdown(f"### {'About' if lang == 'en' else 'حول التطبيق'}")
    st.markdown(
        f"**Smart Research Web Scraper** v{APP_VERSION} — "
        f"{'developed by' if lang == 'en' else 'تطوير'} **{APP_AUTHOR}** · [{APP_AUTHOR_URL}]({APP_AUTHOR_URL})"
    )
    st.caption(
        f"Roudane, M. (2026). Smart Research Web Scraper (Version {APP_VERSION}) [Computer software]."
    )
