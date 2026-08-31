"""Crawl / site graph (spec section 19, page 8).

NetworkX builds the graph, Plotly renders it — no extra front-end dependency.
Nodes are URLs, edges are links, colour encodes depth and size encodes degree.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import networkx as nx
import plotly.graph_objects as go

from ..config import CHART_SEQUENCE, PALETTE

MAX_NODES = 400


def build_graph(edges: list[tuple[str, str]], depths: dict[str, int] | None = None) -> nx.DiGraph:
    graph = nx.DiGraph()
    for source, target in edges[: MAX_NODES * 3]:
        graph.add_edge(source, target)
        if graph.number_of_nodes() > MAX_NODES:
            break
    if depths:
        nx.set_node_attributes(graph, {n: depths.get(n, 0) for n in graph.nodes}, "depth")
    return graph


def _label(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path or "/"
    return (path if len(path) <= 40 else path[:37] + "...") or parts.netloc


def render(graph: nx.DiGraph, title: str = "Pages visited during this run") -> go.Figure:
    """Render the crawl graph as a light, readable Plotly figure."""
    if graph.number_of_nodes() == 0:
        figure = go.Figure()
        figure.add_annotation(
            text="Only one page was collected, so there is no crawl graph to show.",
            showarrow=False,
            font=dict(color=PALETTE["muted"]),
        )
        figure.update_layout(paper_bgcolor=PALETTE["background"], plot_bgcolor="#FFFFFF")
        return figure

    positions = nx.spring_layout(graph, seed=7, k=0.6)
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    for source, target in graph.edges():
        x0, y0 = positions[source]
        x1, y1 = positions[target]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    depths = nx.get_node_attributes(graph, "depth")
    node_x = [positions[n][0] for n in graph.nodes()]
    node_y = [positions[n][1] for n in graph.nodes()]
    degrees = [graph.degree(n) for n in graph.nodes()]
    colors = [CHART_SEQUENCE[depths.get(n, 0) % len(CHART_SEQUENCE)] for n in graph.nodes()]

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line=dict(width=1, color=PALETTE["border"]),
            hoverinfo="none",
            showlegend=False,
        )
    )
    figure.add_trace(
        go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers",
            marker=dict(
                size=[10 + min(degree, 12) * 2 for degree in degrees],
                color=colors,
                line=dict(width=1.5, color="#FFFFFF"),
            ),
            text=[f"{_label(n)}<br>{n}<br>links: {graph.degree(n)}" for n in graph.nodes()],
            hoverinfo="text",
            showlegend=False,
        )
    )
    figure.update_layout(
        title=dict(text=title, font=dict(size=16, color=PALETTE["text"])),
        paper_bgcolor=PALETTE["background"],
        plot_bgcolor="#FFFFFF",
        margin=dict(l=16, r=16, t=56, b=16),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=520,
    )
    return figure


def edges_from_sources(source_urls: list[str], root: str) -> list[tuple[str, str]]:
    """Build a simple star graph when only the visited URL list is known."""
    return [(root, url) for url in dict.fromkeys(source_urls) if url != root]
