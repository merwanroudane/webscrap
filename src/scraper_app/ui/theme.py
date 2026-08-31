"""Light visual system for the Streamlit UI (spec sections 17, 107).

The Streamlit theme in ``.streamlit/config.toml`` does the heavy lifting; this
module adds only the small amount of CSS the theme system cannot express
(cards, status pills, RTL for explanatory text) plus reusable render helpers.
Status is never communicated by colour alone — every pill carries a symbol.
"""

from __future__ import annotations

import html

import streamlit as st

from ..config import PALETTE

_CSS = """
<style>
:root {{
  --srws-bg: {background};
  --srws-panel: {panel};
  --srws-primary: {primary};
  --srws-mint: {mint};
  --srws-coral: {coral};
  --srws-gold: {gold};
  --srws-text: {text};
  --srws-muted: {muted};
  --srws-border: {border};
  --srws-success: {success};
  --srws-warning: {warning};
  --srws-error: {error};
}}
.block-container {{ padding-top: 2.2rem; max-width: 1180px; }}
.srws-card {{
  background: #FFFFFF;
  border: 1px solid var(--srws-border);
  border-radius: 14px;
  padding: 1rem 1.15rem;
  margin-bottom: 0.85rem;
}}
.srws-card h4 {{ margin: 0 0 .35rem 0; font-size: 1.02rem; color: var(--srws-text); }}
.srws-card p {{ margin: 0; color: var(--srws-muted); font-size: .9rem; line-height: 1.5; }}
.srws-pill {{
  display: inline-block; padding: .16rem .6rem; border-radius: 999px;
  font-size: .78rem; font-weight: 600; border: 1px solid var(--srws-border);
  margin-right: .35rem; white-space: nowrap;
}}
.srws-pill.ok      {{ background: var(--srws-success); color: #1F6B52; border-color: #BFE7D8; }}
.srws-pill.warn    {{ background: var(--srws-warning); color: #8A6100; border-color: #F2DFB0; }}
.srws-pill.err     {{ background: var(--srws-error);   color: #A64232; border-color: #F5CFC8; }}
.srws-pill.info    {{ background: var(--srws-panel);   color: #2E5AA8; border-color: #CFE0FA; }}
.srws-pill.neutral {{ background: #F5F7FB;             color: var(--srws-muted); }}
.srws-note {{
  background: var(--srws-panel); border: 1px solid var(--srws-border);
  border-radius: 12px; padding: .8rem 1rem; color: var(--srws-text); font-size: .92rem;
}}
.srws-step {{ font-size: .9rem; padding: .12rem 0; color: var(--srws-muted); }}
.srws-step.done {{ color: #1F6B52; }}
.srws-step.now  {{ color: var(--srws-primary); font-weight: 700; }}
.srws-step.review {{ color: #8A6100; font-weight: 600; }}
.srws-kv {{ font-size: .9rem; color: var(--srws-text); margin: .15rem 0; }}
.srws-kv span.k {{ color: var(--srws-muted); display: inline-block; min-width: 190px; }}
.srws-rtl {{ direction: rtl; text-align: right; }}
.srws-ltr {{ direction: ltr; text-align: left; unicode-bidi: isolate; }}
code, pre, .stCode {{ direction: ltr !important; text-align: left !important; }}
[data-testid="stMetricValue"] {{ font-size: 1.5rem; }}
</style>
"""

_RTL_CSS = """
<style>
.block-container p, .block-container li, .block-container label,
.block-container h1, .block-container h2, .block-container h3,
.block-container h4, [data-testid="stMarkdownContainer"] {
  direction: rtl; text-align: right;
}
[data-testid="stDataFrame"], [data-testid="stTable"], code, pre, .stCode,
input, textarea { direction: ltr !important; text-align: left !important; }
</style>
"""


def inject(rtl: bool = False) -> None:
    """Inject the small CSS layer once per rerun."""
    st.markdown(_CSS.format(**PALETTE), unsafe_allow_html=True)
    if rtl:
        st.markdown(_RTL_CSS, unsafe_allow_html=True)


def pill(text: str, kind: str = "info", symbol: str = "") -> str:
    """Return a status pill. ``symbol`` keeps status readable without colour."""
    label = f"{symbol} {text}".strip()
    return f'<span class="srws-pill {kind}">{html.escape(label)}</span>'


def pills(items: list[tuple[str, str, str]]) -> None:
    st.markdown(
        " ".join(pill(text, kind, symbol) for text, kind, symbol in items),
        unsafe_allow_html=True,
    )


def card(title: str, body: str = "", badges: list[tuple[str, str, str]] | None = None) -> None:
    badge_html = " ".join(pill(t, k, s) for t, k, s in (badges or []))
    st.markdown(
        f'<div class="srws-card"><h4>{html.escape(title)}</h4>'
        f"{badge_html}<p>{html.escape(body)}</p></div>",
        unsafe_allow_html=True,
    )


def note(text: str, kind: str = "info") -> None:
    st.markdown(f'<div class="srws-note">{html.escape(text)}</div>', unsafe_allow_html=True)


def key_value(label: str, value: str) -> None:
    st.markdown(
        f'<div class="srws-kv"><span class="k">{html.escape(label)}</span>'
        f'<span class="srws-ltr">{html.escape(str(value))}</span></div>',
        unsafe_allow_html=True,
    )


def confidence_badge(confidence, lang: str = "en") -> tuple[str, str, str]:
    """Map a Confidence enum onto a pill definition (symbol + text + tone)."""
    kind = {"high": "ok", "medium": "warn", "low": "err"}[confidence.value]
    return confidence.label(lang), kind, confidence.symbol()


def robots_badge(state: str, lang: str = "en") -> tuple[str, str, str]:
    text = {
        "allowed": {"en": "robots.txt: allowed", "ar": "robots.txt: مسموح"},
        "restricted": {"en": "robots.txt: restricted", "ar": "robots.txt: مقيّد"},
        "unknown": {"en": "robots.txt: unknown", "ar": "robots.txt: غير معروف"},
        "not_checked": {"en": "robots.txt: not checked", "ar": "robots.txt: لم يُفحص"},
    }[state][lang if lang in {"en", "ar"} else "en"]
    kind = {"allowed": "ok", "restricted": "warn", "unknown": "neutral", "not_checked": "neutral"}[
        state
    ]
    symbol = {"allowed": "✓", "restricted": "⚠", "unknown": "?", "not_checked": "–"}[state]
    return text, kind, symbol
