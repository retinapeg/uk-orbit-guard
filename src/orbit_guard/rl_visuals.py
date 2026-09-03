"""Plotly visuals for the public debris field and synthetic RL evolution."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from html import escape
import math
from typing import Any

import numpy as np
import plotly.graph_objects as go

from .rl_core import (
    ACTION_NAMES,
    EARTH_RADIUS_KM,
    MEAN_MOTION_RAD_S,
    ORBIT_RADIUS_KM,
    SAFETY_RADIUS_KM,
)


GROUP_COLOURS = {
    "FENGYUN-1C-DEBRIS": "#a78bfa",
    "IRIDIUM-33-DEBRIS": "#fbbf24",
    "COSMOS-2251-DEBRIS": "#fb7185",
}


def hill_to_earth_display(
    x_km: float,
    y_km: float,
    time_s: float,
    *,
    inclination_deg: float = 51.6,
    phase_rad: float = 0.55,
) -> tuple[float, float, float]:
    """Embed local Hill offsets in a declared circular Earth-centred display."""

    theta = phase_rad + MEAN_MOTION_RAD_S * time_s
    radius = ORBIT_RADIUS_KM + x_km
    plane_x = radius * math.cos(theta) - y_km * math.sin(theta)
    plane_y = radius * math.sin(theta) + y_km * math.cos(theta)
    inclination = math.radians(inclination_deg)
    return (
        plane_x,
        plane_y * math.cos(inclination),
        plane_y * math.sin(inclination),
    )


def build_command_globe(
    debris_records: Sequence[Mapping[str, Any]],
    *,
    replay: Mapping[str, Any] | None = None,
    source_label: str,
    displayed_at: str,
) -> go.Figure:
    """Build a dense public debris globe plus the synthetic reference asset."""

    longitude = np.linspace(0, 2 * np.pi, 64)
    latitude = np.linspace(0, np.pi, 34)
    x = EARTH_RADIUS_KM * np.outer(np.cos(longitude), np.sin(latitude))
    y = EARTH_RADIUS_KM * np.outer(np.sin(longitude), np.sin(latitude))
    z = EARTH_RADIUS_KM * np.outer(np.ones_like(longitude), np.cos(latitude))
    texture = (
        np.outer(np.sin(2.0 * longitude) + 1.0, np.ones_like(latitude))
        + 0.25 * np.outer(np.ones_like(longitude), np.cos(3.0 * latitude))
    )
    figure = go.Figure(
        go.Surface(
            x=x,
            y=y,
            z=z,
            surfacecolor=texture,
            colorscale=[
                [0.0, "#020b1e"],
                [0.35, "#042f5c"],
                [0.62, "#075985"],
                [1.0, "#0ea5e9"],
            ],
            opacity=0.97,
            showscale=False,
            hoverinfo="skip",
            lighting={"ambient": 0.48, "diffuse": 0.88, "roughness": 0.72},
            showlegend=False,
        )
    )

    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in debris_records:
        grouped[str(record.get("source_group", "PUBLIC DEBRIS"))].append(record)
    for group, values in grouped.items():
        safe_group = escape(group)
        positions = [item["position_km"] for item in values]
        figure.add_trace(
            go.Scatter3d(
                x=[item[0] for item in positions],
                y=[item[1] for item in positions],
                z=[item[2] for item in positions],
                mode="markers",
                marker={
                    "size": 2.2,
                    "color": GROUP_COLOURS.get(group, "#94a3b8"),
                    "opacity": 0.58,
                    "symbol": "circle",
                },
                name=f"{safe_group.replace('-', ' ')} · {len(values):,}",
                text=[
                    f"<b>{escape(str(item['name']))}</b><br>NORAD "
                    f"{escape(str(item['object_id']))}"
                    f"<br>{escape(str(item.get('object_type', 'PUBLIC OBJECT')))} · "
                    f"{safe_group}"
                    "<br>Public GP/OMM display position"
                    for item in values
                ],
                hovertemplate="%{text}<extra></extra>",
            )
        )

    angles = np.linspace(0.0, 2.0 * np.pi, 280)
    inclination = math.radians(51.6)
    orbit_x = ORBIT_RADIUS_KM * np.cos(angles)
    orbit_plane_y = ORBIT_RADIUS_KM * np.sin(angles)
    figure.add_trace(
        go.Scatter3d(
            x=orbit_x,
            y=orbit_plane_y * math.cos(inclination),
            z=orbit_plane_y * math.sin(inclination),
            mode="lines",
            line={"color": "#22d3ee", "width": 4},
            opacity=0.78,
            name="Protected synthetic reference orbit",
            hoverinfo="skip",
        )
    )
    if replay and replay.get("trajectory"):
        final = replay["trajectory"][-1]
        satellite = final["satellite"]
        point = hill_to_earth_display(
            float(satellite["x_km"]),
            float(satellite["y_km"]),
            float(final["time_s"]),
        )
    else:
        point = hill_to_earth_display(0.0, 0.0, 0.0)
    figure.add_trace(
        go.Scatter3d(
            x=[point[0]], y=[point[1]], z=[point[2]],
            mode="markers+text",
            marker={
                "size": 9,
                "color": "#67e8f9",
                "symbol": "diamond",
                "line": {"color": "#ffffff", "width": 2},
            },
            text=["GUARD-1"],
            textposition="top center",
            textfont={"color": "#dffbff", "size": 11},
            name="Controlled synthetic satellite",
            hovertemplate=(
                "<b>GUARD-1</b><br>Synthetic controlled satellite"
                "<br>550 km circular display reference<extra></extra>"
            ),
        )
    )

    extent = 10_500
    figure.update_layout(
        height=610,
        margin={"l": 0, "r": 0, "t": 88, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title={
            "text": (
                f"PUBLIC SGP4/TEME FIELD · {len(debris_records):,} GROUP-QUERY OBJECTS"
                f"<br><sup>{escape(source_label)} · DISPLAYED {escape(displayed_at)}"
                "</sup><br><sup>CONSTRUCTED SYNTHETIC REFERENCE-ORBIT EMBEDDING</sup>"
            ),
            "font": {"color": "#f8fafc", "size": 17},
            "x": 0.02,
        },
        legend={
            "font": {"color": "#b8c7da", "size": 10},
            "bgcolor": "rgba(2,6,23,.68)",
            "bordercolor": "rgba(103,232,249,.2)",
            "borderwidth": 1,
            "x": 0.01,
            "y": 0.03,
        },
        scene={
            "xaxis": {"visible": False, "range": [-extent, extent]},
            "yaxis": {"visible": False, "range": [-extent, extent]},
            "zaxis": {"visible": False, "range": [-extent, extent]},
            "aspectmode": "cube",
            "bgcolor": "rgba(1,5,15,.92)",
            "camera": {"eye": {"x": 1.38, "y": 1.42, "z": 0.86}},
        },
        uirevision="uk-orbit-guard-command-globe-v1",
        annotations=[
            {
                "text": "PUBLIC MEAN-ELEMENT CONTEXT · NOT SENSOR TELEMETRY",
                "x": 0.99,
                "y": 0.99,
                "xref": "paper",
                "yref": "paper",
                "xanchor": "right",
                "yanchor": "top",
                "showarrow": False,
                "font": {"color": "#fbbf24", "size": 10},
                "bgcolor": "rgba(69,45,4,.72)",
                "borderpad": 5,
            }
        ],
    )
    return figure


def build_encounter_replay(
    replay: Mapping[str, Any],
    *,
    generation: int,
    baseline: Mapping[str, Any] | None = None,
) -> go.Figure:
    """Animate one generation in the magnified local Hill encounter frame."""

    trajectory = replay["trajectory"]
    satellite_x = [point["satellite"]["x_km"] for point in trajectory]
    satellite_y = [point["satellite"]["y_km"] for point in trajectory]
    figure = go.Figure()

    if baseline is not None and generation > 0:
        base_trajectory = baseline["trajectory"]
        figure.add_trace(
            go.Scatter(
                x=[point["satellite"]["x_km"] for point in base_trajectory],
                y=[point["satellite"]["y_km"] for point in base_trajectory],
                mode="lines",
                line={"color": "rgba(248,113,113,.62)", "width": 2, "dash": "dot"},
                name="Gen 0 path",
                hoverinfo="skip",
            )
        )

    figure.add_trace(
        go.Scatter(
            x=satellite_x,
            y=satellite_y,
            mode="lines",
            line={"color": "#22d3ee", "width": 5},
            name=f"Gen {generation} controlled path",
            hovertemplate="Radial %{x:.3f} km<br>Along-track %{y:.3f} km<extra></extra>",
        )
    )
    object_ids = [item["object_id"] for item in trajectory[0]["objects"]]
    for object_index, object_id in enumerate(object_ids):
        values = [point["objects"][object_index] for point in trajectory]
        figure.add_trace(
            go.Scatter(
                x=[item["x_km"] for item in values],
                y=[item["y_km"] for item in values],
                mode="lines",
                line={"color": values[0]["colour"], "width": 3, "dash": "dash"},
                name=f"{object_id} incoming path",
                hovertemplate=f"<b>{object_id}</b><br>Radial %{{x:.3f}} km<br>Along-track %{{y:.3f}} km<extra></extra>",
            )
        )

    satellite_marker_index = len(figure.data)
    figure.add_trace(
        go.Scatter(
            x=[satellite_x[0]], y=[satellite_y[0]], mode="markers",
            marker={"size": 16, "color": "#67e8f9", "symbol": "diamond", "line": {"color": "white", "width": 2}},
            name="GUARD-1 now",
            hovertemplate="<b>GUARD-1</b><extra></extra>",
        )
    )
    object_marker_index = len(figure.data)
    first_objects = trajectory[0]["objects"]
    figure.add_trace(
        go.Scatter(
            x=[item["x_km"] for item in first_objects],
            y=[item["y_km"] for item in first_objects],
            mode="markers+text",
            marker={"size": 12, "color": [item["colour"] for item in first_objects], "symbol": "x", "line": {"width": 2}},
            text=[item["object_id"] for item in first_objects],
            textposition="top center",
            textfont={"color": "#f8fafc", "size": 10},
            name="Injected objects now",
            hovertemplate="<b>%{text}</b><extra></extra>",
        )
    )

    frames = []
    for frame_index, point in enumerate(trajectory):
        objects = point["objects"]
        frames.append(
            go.Frame(
                name=str(frame_index),
                data=[
                    go.Scatter(
                        x=[point["satellite"]["x_km"]],
                        y=[point["satellite"]["y_km"]],
                        mode="markers",
                        marker={"size": 16, "color": "#67e8f9", "symbol": "diamond", "line": {"color": "white", "width": 2}},
                    ),
                    go.Scatter(
                        x=[item["x_km"] for item in objects],
                        y=[item["y_km"] for item in objects],
                        mode="markers+text",
                        marker={"size": 12, "color": [item["colour"] for item in objects], "symbol": "x", "line": {"width": 2}},
                        text=[item["object_id"] for item in objects],
                        textposition="top center",
                    ),
                ],
                traces=[satellite_marker_index, object_marker_index],
                layout={
                    "shapes": [
                        {
                            "type": "circle",
                            "xref": "x",
                            "yref": "y",
                            "x0": point["satellite"]["x_km"] - SAFETY_RADIUS_KM,
                            "x1": point["satellite"]["x_km"] + SAFETY_RADIUS_KM,
                            "y0": point["satellite"]["y_km"] - SAFETY_RADIUS_KM,
                            "y1": point["satellite"]["y_km"] + SAFETY_RADIUS_KM,
                            "line": {
                                "color": "rgba(251,191,36,.55)",
                                "width": 1,
                                "dash": "dot",
                            },
                            "fillcolor": "rgba(251,191,36,.05)",
                        }
                    ]
                },
            )
        )
    figure.frames = frames

    circle = go.layout.Shape(
        type="circle",
        xref="x", yref="y",
        x0=-SAFETY_RADIUS_KM, x1=SAFETY_RADIUS_KM,
        y0=-SAFETY_RADIUS_KM, y1=SAFETY_RADIUS_KM,
        line={"color": "rgba(251,191,36,.55)", "width": 1, "dash": "dot"},
        fillcolor="rgba(251,191,36,.05)",
    )
    all_x = satellite_x + [item["x_km"] for point in trajectory for item in point["objects"]]
    all_y = satellite_y + [item["y_km"] for point in trajectory for item in point["objects"]]
    pad = 1.0
    figure.update_layout(
        height=510,
        margin={"l": 55, "r": 25, "t": 74, "b": 55},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(3,10,24,.78)",
        font={"color": "#cbd5e1"},
        title={
            "text": f"POLICY EVOLUTION · GENERATION {generation}<br><sup>SYNTHETIC HILL/LVLH LOCAL OFFSETS · PLAY TO WATCH RESPONSE</sup>",
            "font": {"color": "#f8fafc", "size": 16},
        },
        xaxis={
            "title": "Radial offset x (km)",
            "range": [min(all_x) - pad, max(all_x) + pad],
            "gridcolor": "rgba(148,163,184,.12)",
            "zerolinecolor": "rgba(103,232,249,.4)",
        },
        yaxis={
            "title": "Along-track offset y (km)",
            "range": [min(all_y) - pad, max(all_y) + pad],
            "gridcolor": "rgba(148,163,184,.12)",
            "zerolinecolor": "rgba(103,232,249,.4)",
            "scaleanchor": "x",
            "scaleratio": 1,
        },
        legend={"orientation": "h", "y": -0.22, "font": {"size": 10}},
        shapes=[circle],
        updatemenus=[
            {
                "type": "buttons",
                "direction": "left",
                "x": 0.0,
                "y": 1.03,
                "buttons": [
                    {"label": "▶ PLAY", "method": "animate", "args": [None, {"frame": {"duration": 70, "redraw": False}, "fromcurrent": True, "transition": {"duration": 0}}]},
                    {"label": "❚❚ PAUSE", "method": "animate", "args": [[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}]},
                ],
            }
        ],
        sliders=[
            {
                "active": 0,
                "currentvalue": {"prefix": "T+", "suffix": " step"},
                "pad": {"t": 36},
                "steps": [
                    {
                        "label": str(index),
                        "method": "animate",
                        "args": [[str(index)], {"mode": "immediate", "frame": {"duration": 0, "redraw": False}}],
                    }
                    for index in range(len(trajectory))
                ],
            }
        ],
        uirevision=f"generation-{generation}",
    )
    return figure


def build_training_curve(result: Mapping[str, Any], selected_generation: int) -> go.Figure:
    curve = result["training_curve"]
    generations = [0] + [item["generation"] for item in curve]
    baseline_reward = float(result["baseline_evaluation"]["reward"])
    mean_returns = [baseline_reward] + [float(item["mean_return"]) for item in curve]
    validation = [baseline_reward] + [
        float(result["policy_evolution"][index]["reward"])
        for index in range(1, len(result["policy_evolution"]))
    ]
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=generations, y=mean_returns, mode="lines+markers", name="Population mean", line={"color": "#64748b", "width": 2}))
    figure.add_trace(go.Scatter(x=generations, y=validation, mode="lines+markers", name="Retained policy replay", line={"color": "#22d3ee", "width": 4}, marker={"size": 7}))
    figure.add_vline(x=selected_generation, line_color="#fbbf24", line_width=2, line_dash="dot")
    figure.update_layout(
        height=310,
        margin={"l": 40, "r": 20, "t": 55, "b": 40},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(3,10,24,.78)",
        font={"color": "#cbd5e1"},
        title={"text": "EPISODIC RETURN BY GENERATION", "font": {"size": 14, "color": "#f8fafc"}},
        xaxis={"title": "Generation", "dtick": 1, "gridcolor": "rgba(148,163,184,.1)"},
        yaxis={"title": "Synthetic return", "gridcolor": "rgba(148,163,184,.1)"},
        legend={"orientation": "h", "y": 1.12, "x": 0.42},
    )
    return figure


def action_mix(replay: Mapping[str, Any]) -> dict[str, int]:
    counts = Counter(replay["action_names"])
    return {name: counts.get(name, 0) for name in ACTION_NAMES}
