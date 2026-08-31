"""Settings — engines, keys and limits (spec section 106.8).

Shows what is ready, what is optional, and what is only catalogued. It prints
install instructions; it never executes shell commands from the web UI.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..config import PROVIDER_ENV_KEYS, SETTINGS, has_credentials
from ..routing.capability_registry import engine_status_table
from . import state
from .i18n import t
from .theme import card, note, pills

_STATE_LABEL = {
    "ready": ("Ready", "ok", "✓"),
    "optional": ("Optional", "warn", "○"),
    "catalogue": ("Catalogue", "neutral", "–"),
}


def render() -> None:
    lang = state.lang()
    st.title(t("engines", lang))
    st.caption(
        "The application runs fully with the local engines and no API keys."
        if lang == "en"
        else "التطبيق يعمل بالكامل بالمحركات المحلية وبدون أي مفاتيح."
    )

    rows = engine_status_table()
    ready = sum(1 for row in rows if row.state == "ready")
    optional = sum(1 for row in rows if row.state == "optional")
    catalogue = sum(1 for row in rows if row.state == "catalogue")
    pills(
        [
            (f"{ready} ready", "ok", "✓"),
            (f"{optional} optional", "warn", "○"),
            (f"{catalogue} catalogued", "neutral", "–"),
        ]
    )

    table = pd.DataFrame(
        [
            {
                "engine": row.label,
                "type": row.type,
                "status": _STATE_LABEL[row.state][2] + " " + _STATE_LABEL[row.state][0],
                "detail": row.detail,
                "cost": row.cost_mode,
                "setup": row.install_hint or "built-in",
                "docs": row.docs,
            }
            for row in rows
        ]
    )
    st.dataframe(table, width="stretch", hide_index=True)

    with st.expander("How to install an optional engine" if lang == "en" else "كيفية تثبيت محرك اختياري"):
        st.markdown(
            "Run these in the project environment, then restart the app:"
            if lang == "en"
            else "شغّل هذه الأوامر في بيئة المشروع ثم أعد تشغيل التطبيق:"
        )
        st.code(
            "pip install playwright && playwright install chromium   # browser rendering\n"
            "pip install crawl4ai && crawl4ai-setup                  # local adaptive engine\n"
            "pip install pymupdf                                     # PDF documents\n"
            "pip install firecrawl-py                                # hosted extraction (needs a key)",
            language="bash",
        )
        note(
            "The app never runs installation commands for you — you stay in control of your environment."
            if lang == "en"
            else "التطبيق لا ينفذ أوامر التثبيت نيابة عنك — أنت من يتحكم في بيئتك."
        )

    st.divider()
    st.markdown(f"### {'API keys' if lang == 'en' else 'مفاتيح API'}")
    st.caption(
        "Keys are read from environment variables / .env only. The app never stores or displays them."
        if lang == "en"
        else "تُقرأ المفاتيح من متغيرات البيئة / ملف .env فقط. التطبيق لا يخزّنها ولا يعرضها."
    )
    key_rows = [
        {
            "provider": provider,
            "environment_variables": ", ".join(keys),
            "configured": "✓ yes" if has_credentials(provider) else "– no",
        }
        for provider, keys in PROVIDER_ENV_KEYS.items()
    ]
    st.dataframe(pd.DataFrame(key_rows), width="stretch", hide_index=True)

    st.divider()
    st.markdown(f"### {'Limits in force' if lang == 'en' else 'الحدود المفعّلة'}")
    limits = SETTINGS.limits
    st.dataframe(
        pd.DataFrame(
            [
                {"setting": "Max HTML response", "value": f"{limits.max_html_bytes / 1_048_576:.0f} MB"},
                {"setting": "Max JSON sample", "value": f"{limits.max_json_sample_bytes / 1_048_576:.0f} MB"},
                {"setting": "Max preview rows", "value": f"{limits.max_preview_rows:,}"},
                {"setting": "Default crawl pages", "value": limits.default_max_pages},
                {"setting": "Hard page cap", "value": limits.hard_max_pages},
                {"setting": "Max redirects", "value": limits.max_redirects},
                {"setting": "HTTP timeout", "value": f"{limits.http_timeout:.0f}s"},
                {"setting": "Browser timeout", "value": f"{limits.browser_timeout:.0f}s"},
                {"setting": "Requests per second", "value": SETTINGS.politeness.requests_per_second},
                {"setting": "User agent", "value": SETTINGS.user_agent},
                {
                    "setting": "Private networks allowed",
                    "value": "yes (demo mode)" if SETTINGS.security.allow_private_networks else "no",
                },
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    card(
        "Security posture" if lang == "en" else "الوضع الأمني",
        "Every URL and every redirect is checked against the SSRF guard. Private, loopback, "
        "link-local and cloud-metadata addresses are refused. robots.txt is respected by default. "
        "Credentials never enter logs, recipes, provenance files or generated code."
        if lang == "en"
        else "كل رابط وكل إعادة توجيه يمر عبر حارس SSRF. تُرفض العناوين الخاصة والمحلية وعناوين "
        "بيانات السحابة. يُحترم robots.txt افتراضيًا. ولا تدخل بيانات الاعتماد إلى السجلات أو "
        "الوصفات أو ملفات الإسناد أو الكود المولّد.",
    )
