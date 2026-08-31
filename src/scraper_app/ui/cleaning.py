"""Page 7 — Clean & validate (spec section 29).

Every operation is opt-in, reversible within the session, and reported. The
raw extracted frame is never modified, so "Reset to extracted data" always
works.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..data.cleaner import CleaningOptions
from ..data.validator import rules_from_schema, validate
from ..service import apply_cleaning, reset_cleaning
from .i18n import t
from .theme import note


def render_panel(outcome, lang: str) -> None:
    st.markdown(f"### {t('clean_validate', lang)}")
    st.caption(
        "Nothing is changed until you apply it, and you can always return to the extracted data."
        if lang == "en"
        else "لا يتغير شيء حتى تطبّقه، ويمكنك دائمًا العودة إلى البيانات المستخرجة."
    )

    frame = outcome.raw_df
    numeric_default = [c for c in frame.columns if not str(c).startswith("_")]

    columns = st.columns(3)
    with columns[0]:
        trim = st.checkbox(
            "Trim whitespace" if lang == "en" else "إزالة المسافات الزائدة", value=True
        )
        missing = st.checkbox(
            "Normalize missing tokens (-, N/A, ..)" if lang == "en" else "توحيد رموز القيم الناقصة",
            value=True,
        )
        duplicates = st.checkbox(
            "Remove duplicate rows" if lang == "en" else "حذف الصفوف المكررة", value=False
        )
    with columns[1]:
        numeric = st.checkbox(
            "Convert numeric text to numbers" if lang == "en" else "تحويل النص الرقمي إلى أرقام",
            value=False,
        )
        percentages = st.checkbox(
            "Parse percentages (9.3% → 0.093)"
            if lang == "en"
            else "تحليل النسب المئوية (9.3% ← 0.093)",
            value=False,
        )
        currency = st.checkbox(
            "Parse currency amounts" if lang == "en" else "تحليل المبالغ النقدية", value=False
        )
    with columns[2]:
        dates = st.checkbox("Parse dates" if lang == "en" else "تحليل التواريخ", value=False)
        booleans = st.checkbox(
            "Normalize yes/no columns" if lang == "en" else "توحيد أعمدة نعم/لا", value=False
        )
        standardize = st.checkbox(
            "Standardize column names" if lang == "en" else "توحيد أسماء الأعمدة", value=False
        )

    with st.expander("Advanced cleaning" if lang == "en" else "تنظيف متقدم", expanded=False):
        numeric_columns = st.multiselect(
            "Numeric columns (leave empty to detect automatically)"
            if lang == "en"
            else "الأعمدة الرقمية (اتركها فارغة للاكتشاف التلقائي)",
            options=numeric_default,
        )
        date_columns = st.multiselect(
            "Date columns (leave empty to detect automatically)"
            if lang == "en"
            else "أعمدة التاريخ (اتركها فارغة للاكتشاف التلقائي)",
            options=numeric_default,
        )
        duplicate_subset = st.multiselect(
            "Duplicate key columns" if lang == "en" else "أعمدة مفتاح التكرار",
            options=numeric_default,
        )
        outliers = st.checkbox(
            "Flag outliers (never deletes rows)"
            if lang == "en"
            else "وسم القيم الشاذة (لا يحذف صفوفًا)",
            value=False,
        )
        outlier_z = st.slider("Outlier threshold |z|", 2.0, 6.0, 3.0, 0.5, disabled=not outliers)
        categories = st.checkbox(
            "Normalize category labels" if lang == "en" else "توحيد تسميات الفئات", value=False
        )

    options = CleaningOptions(
        trim_whitespace=trim,
        normalize_missing=missing,
        numeric_conversion=numeric,
        parse_percentages=percentages,
        parse_currency=currency,
        parse_dates=dates,
        normalize_booleans=booleans,
        standardize_column_names=standardize,
        normalize_categories=categories,
        drop_duplicates=duplicates,
        duplicate_subset=duplicate_subset or None,
        flag_outliers=outliers,
        outlier_z=outlier_z if outliers else 3.0,
        numeric_columns=numeric_columns or None,
        date_columns=date_columns or None,
    )

    left, right = st.columns(2)
    if left.button(t("apply_cleaning", lang), type="primary", width="stretch", key="apply_clean"):
        st.session_state["outcome"] = apply_cleaning(outcome, options)
        st.rerun()
    if right.button(t("reset_cleaning", lang), width="stretch", key="reset_clean"):
        st.session_state["outcome"] = reset_cleaning(outcome)
        st.rerun()

    if outcome.cleaning and outcome.cleaning.operations:
        st.markdown(f"**{'Applied operations' if lang == 'en' else 'العمليات المطبقة'}**")
        st.dataframe(
            pd.DataFrame([operation.as_dict() for operation in outcome.cleaning.operations]),
            width="stretch",
            hide_index=True,
        )
        for warning in outcome.cleaning.warnings:
            st.warning(warning)

    # ---------------------------------------------------------------- validation
    if outcome.schema and outcome.schema.fields:
        st.markdown(f"**{'Validation' if lang == 'en' else 'التحقق'}**")
        result = validate(outcome.clean_df, rules_from_schema(outcome.schema))
        if result.passed:
            st.success(
                f"All checks passed ({result.engine})."
                if lang == "en"
                else f"نجحت كل الفحوص ({result.engine})."
            )
        else:
            for error in result.errors:
                st.warning(error)
            note(
                "Validation is advisory — no rows were removed."
                if lang == "en"
                else "التحقق إرشادي — لم يتم حذف أي صفوف."
            )
