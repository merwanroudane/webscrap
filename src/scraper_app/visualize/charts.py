"""Automatic chart suggestions and the chart builder (spec sections 33, 80).

Everything is Plotly, styled with the light research palette. Suggestions come
from the column dtypes; the researcher can always override them.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from ..config import CHART_SEQUENCE, PALETTE

MAX_POINTS = 20_000


def apply_theme(figure: go.Figure, title: str | None = None) -> go.Figure:
    figure.update_layout(
        template="plotly_white",
        colorway=CHART_SEQUENCE,
        paper_bgcolor=PALETTE["background"],
        plot_bgcolor="#FFFFFF",
        font=dict(color=PALETTE["text"], size=13),
        title=dict(text=title or figure.layout.title.text or "", font=dict(size=16)),
        margin=dict(l=48, r=24, t=56, b=48),
        legend=dict(bgcolor="rgba(255,255,255,0.7)", bordercolor=PALETTE["border"], borderwidth=1),
        hoverlabel=dict(bgcolor="#FFFFFF", bordercolor=PALETTE["border"]),
    )
    figure.update_xaxes(gridcolor=PALETTE["border"], zerolinecolor=PALETTE["border"])
    figure.update_yaxes(gridcolor=PALETTE["border"], zerolinecolor=PALETTE["border"])
    return figure


@dataclass
class ChartSuggestion:
    kind: str  # line | bar | scatter | histogram | box | frequency | missingness
    title: str
    x: str | None = None
    y: str | None = None
    color: str | None = None
    reason: str = ""


#: Numeric columns whose name marks them as identifiers or time, not measures.
_NON_MEASURE = ("year", "id", "code", "rank", "page", "index", "no", "num", "سنة", "رقم")


def _is_measure(name: str) -> bool:
    lowered = str(name).lower()
    return not any(
        lowered == token or lowered.endswith("_" + token) or lowered.startswith(token + "_")
        for token in _NON_MEASURE
    )


def _column_types(frame: pd.DataFrame) -> tuple[list[str], list[str], list[str]]:
    numeric = [
        c for c in frame.columns
        if pd.api.types.is_numeric_dtype(frame[c]) and not str(c).startswith("_")
        and not str(c).endswith("_outlier_flag")
    ]
    dates = [
        c for c in frame.columns
        if pd.api.types.is_datetime64_any_dtype(frame[c]) and not str(c).startswith("_")
    ]
    categorical = [
        c for c in frame.columns
        if c not in numeric and c not in dates and not str(c).startswith("_")
        and frame[c].dropna().nunique() <= max(30, len(frame) // 10)
    ]
    # Real measures first: a "year" or "id" column is an axis, not a value.
    numeric.sort(key=lambda c: not _is_measure(c))
    time_like = [c for c in numeric if str(c).lower() in {"year", "سنة"}]
    dates = dates + [c for c in time_like if c not in dates]
    return numeric, dates, categorical


def suggest(frame: pd.DataFrame, limit: int = 5) -> list[ChartSuggestion]:
    """Propose charts based on the schema (spec section 33)."""
    if frame is None or frame.empty:
        return []
    numeric, dates, categorical = _column_types(frame)
    suggestions: list[ChartSuggestion] = []

    if dates and numeric:
        suggestions.append(
            ChartSuggestion(
                "line",
                f"{numeric[0]} over {dates[0]}",
                x=dates[0],
                y=numeric[0],
                reason="A date column combined with a numeric column reads best as a time series.",
            )
        )
    if categorical and numeric:
        suggestions.append(
            ChartSuggestion(
                "bar",
                f"{numeric[0]} by {categorical[0]}",
                x=categorical[0],
                y=numeric[0],
                reason="A category with a numeric measure compares well as a bar chart.",
            )
        )
    if len(numeric) >= 2:
        suggestions.append(
            ChartSuggestion(
                "scatter",
                f"{numeric[1]} vs {numeric[0]}",
                x=numeric[0],
                y=numeric[1],
                reason="Two numeric columns show their relationship in a scatter plot.",
            )
        )
    if numeric:
        suggestions.append(
            ChartSuggestion(
                "histogram",
                f"Distribution of {numeric[0]}",
                x=numeric[0],
                reason="A single numeric column is best understood through its distribution.",
            )
        )
    if categorical and not numeric:
        suggestions.append(
            ChartSuggestion(
                "frequency",
                f"Most frequent {categorical[0]}",
                x=categorical[0],
                reason="Category-only data is summarised by frequency.",
            )
        )
    if frame.isna().to_numpy().any():
        suggestions.append(
            ChartSuggestion(
                "missingness",
                "Missing values by column",
                reason="Some values are missing; this shows where.",
            )
        )
    return suggestions[:limit]


def _downsample(frame: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    if len(frame) > MAX_POINTS:
        return frame.sample(MAX_POINTS, random_state=0), True
    return frame, False


def build_chart(
    frame: pd.DataFrame,
    kind: str,
    *,
    x: str | None = None,
    y: str | None = None,
    color: str | None = None,
    aggregation: str = "none",
    title: str | None = None,
) -> go.Figure:
    """Build one Plotly figure for the chart builder or a suggestion."""
    data, sampled = _downsample(frame)
    note = " (sampled)" if sampled else ""

    if kind == "missingness":
        from ..data.profiler import missingness_frame

        missing = missingness_frame(frame)
        figure = px.bar(missing, x="missing_pct", y="column", orientation="h")
        figure.update_traces(marker_color=PALETTE["coral"])
        return apply_theme(figure, title or "Missing values by column (%)")

    if kind == "frequency" and x:
        counts = data[x].astype(str).value_counts().head(25).reset_index()
        counts.columns = [x, "count"]
        figure = px.bar(counts, x=x, y="count")
        return apply_theme(figure, title or f"Most frequent {x}{note}")

    if aggregation != "none" and x and y:
        grouped = getattr(data.groupby(x, dropna=False)[y], aggregation)().reset_index()
        data = grouped

    if kind == "line" and x and y:
        figure = px.line(data.sort_values(x), x=x, y=y, color=color, markers=len(data) < 500)
    elif kind == "bar" and x and y:
        figure = px.bar(data, x=x, y=y, color=color, barmode="group")
    elif kind == "scatter" and x and y:
        figure = px.scatter(data, x=x, y=y, color=color, opacity=0.75)
    elif kind == "histogram" and x:
        figure = px.histogram(data, x=x, color=color, nbins=40)
    elif kind == "box" and y:
        figure = px.box(data, x=x, y=y, color=color, points="outliers")
    elif kind == "heatmap" and x and y:
        pivot = data.pivot_table(index=y, columns=x, aggfunc="size", fill_value=0)
        figure = px.imshow(pivot, color_continuous_scale="Blues", aspect="auto")
    else:
        figure = go.Figure()
        figure.add_annotation(
            text="Choose columns that match the selected chart type.",
            showarrow=False,
            font=dict(color=PALETTE["muted"]),
        )
    return apply_theme(figure, title or f"{kind.title()}{note}")


def numeric_summary(frame: pd.DataFrame) -> pd.DataFrame:
    numeric = frame.select_dtypes("number")
    numeric = numeric[[c for c in numeric.columns if not str(c).startswith("_")]]
    if numeric.empty:
        return pd.DataFrame()
    summary = numeric.describe().T.reset_index().rename(columns={"index": "column"})
    return summary.round(4)


def categorical_summary(frame: pd.DataFrame, top: int = 5) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for column in frame.columns:
        if str(column).startswith("_") or pd.api.types.is_numeric_dtype(frame[column]):
            continue
        series = frame[column].dropna().astype(str)
        if series.empty:
            continue
        counts = series.value_counts().head(top)
        rows.append(
            {
                "column": str(column),
                "unique": int(series.nunique()),
                "top_values": ", ".join(f"{value} ({count})" for value, count in counts.items()),
            }
        )
    return pd.DataFrame(rows)
