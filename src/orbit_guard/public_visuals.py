"""Reusable Plotly figures for the public orbital-element context layer.

The functions in this module deliberately accept plain mappings or attribute
objects.  They do not depend on a feed client, cache implementation, or a
particular public catalogue schema.  Coordinates supplied to the catalogue
globe are Earth-centred kilometres; proximity candidates use source-modelled
minimum ranges and closest-approach times within a declared screening horizon.

Both figures are presentation surfaces for public-element context.  Their
visible labels keep candidate screening separate from any operational flight
decision.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from html import escape
from math import isfinite, log10, pi
from typing import Any

import numpy as np
import plotly.graph_objects as go

EARTH_RADIUS_KM = 6_371.0

_CYAN = "#22d3ee"
_CYAN_SOFT = "#67e8f9"
_GOLD = "#fbbf24"
_PURPLE = "#a78bfa"
_WHITE = "#f8fafc"
_MUTED = "#94a3b8"
_TEXT = "#b8c7da"
_PLOT_BG = "rgba(3,10,24,.78)"
_GRID = "rgba(148,163,184,.13)"

_TYPE_STYLE: dict[str, tuple[str, str]] = {
    "PAYLOAD": ("diamond", _CYAN),
    "ROCKET BODY": ("square", _GOLD),
    "DEBRIS": ("x", _PURPLE),
    "UNKNOWN": ("circle-open", _MUTED),
}

_ID_FIELDS = ("object_id", "norad_id", "norad_cat_id", "catalog_id", "id")
_NAME_FIELDS = ("name", "object_name", "label")
_TYPE_FIELDS = ("object_type", "type", "category")


def _value(record: object, names: Sequence[str], default: Any = None) -> Any:
    if isinstance(record, Mapping):
        for name in names:
            if name in record:
                return record[name]
        return default
    for name in names:
        if hasattr(record, name):
            return getattr(record, name)
    return default


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _object_type(value: object) -> str:
    text = str(value or "").strip().upper().replace("_", " ")
    if "DEB" in text or "FRAGMENT" in text:
        return "DEBRIS"
    if text in {"R/B", "RB"} or "ROCKET" in text or "BOOSTER" in text:
        return "ROCKET BODY"
    if "PAYLOAD" in text or "SATELLITE" in text or text in {"PL", "ACTIVE"}:
        return "PAYLOAD"
    return "UNKNOWN"


def _record_id(record: object, index: int) -> str:
    value = _value(record, _ID_FIELDS)
    return str(value) if value is not None and str(value).strip() else f"record-{index + 1}"


def _position_km(record: object) -> tuple[float, float, float] | None:
    packed_km = _value(record, ("position_km", "xyz_km", "current_xyz_km"))
    if isinstance(packed_km, Sequence) and not isinstance(packed_km, (str, bytes)):
        if len(packed_km) == 3:
            values = tuple(_number(item) for item in packed_km)
            if all(value is not None for value in values):
                return values  # type: ignore[return-value]

    x_km = _number(_value(record, ("x_km", "current_x_km")))
    y_km = _number(_value(record, ("y_km", "current_y_km")))
    z_km = _number(_value(record, ("z_km", "current_z_km")))
    if x_km is not None and y_km is not None and z_km is not None:
        return x_km, y_km, z_km

    packed_m = _value(record, ("position_m", "xyz_m", "current_xyz_m"))
    if isinstance(packed_m, Sequence) and not isinstance(packed_m, (str, bytes)):
        if len(packed_m) == 3:
            values_m = tuple(_number(item) for item in packed_m)
            if all(value is not None for value in values_m):
                return tuple(value / 1_000.0 for value in values_m)  # type: ignore[misc,return-value]
    return None


def _trail_km(record: object) -> tuple[tuple[float, float, float], ...]:
    raw = _value(record, ("orbit_trail_km", "trail_km", "orbit_trail"))
    if raw is None:
        return ()

    if isinstance(raw, Mapping):
        x_values = raw.get("x", raw.get("x_km"))
        y_values = raw.get("y", raw.get("y_km"))
        z_values = raw.get("z", raw.get("z_km"))
        if all(
            isinstance(values, Sequence) and not isinstance(values, (str, bytes))
            for values in (x_values, y_values, z_values)
        ):
            return tuple(
                point
                for point in (
                    (_number(x), _number(y), _number(z))
                    for x, y, z in zip(x_values, y_values, z_values)  # type: ignore[arg-type]
                )
                if all(value is not None for value in point)
            )  # type: ignore[return-value]

    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        points: list[tuple[float, float, float]] = []
        for item in raw:
            if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) != 3:
                continue
            point = tuple(_number(value) for value in item)
            if all(value is not None for value in point):
                points.append(point)  # type: ignore[arg-type]
        return tuple(points)
    return ()


def _metadata(record: object, names: Sequence[str], default: str = "Not supplied") -> str:
    value = _value(record, names)
    if value is None or not str(value).strip():
        return default
    return str(value)


@dataclass(frozen=True)
class _CataloguePoint:
    object_id: str
    name: str
    object_type: str
    x_km: float
    y_km: float
    z_km: float
    trail_km: tuple[tuple[float, float, float], ...]
    element_epoch: str
    source_group: str
    orbit_regime: str
    selected: bool
    review_candidate: bool


def _catalogue_points(
    records: Iterable[object],
    *,
    selected_id: object | None,
    review_candidate_ids: Iterable[object],
) -> tuple[list[_CataloguePoint], int]:
    selected_text = None if selected_id is None else str(selected_id)
    review_ids = {str(item) for item in review_candidate_ids}
    points: list[_CataloguePoint] = []
    invalid = 0

    for index, record in enumerate(records):
        position = _position_km(record)
        if position is None:
            invalid += 1
            continue
        object_id = _record_id(record, index)
        selected = object_id == selected_text or _truthy(
            _value(record, ("selected", "is_selected"), False)
        )
        review_candidate = object_id in review_ids or _truthy(
            _value(record, ("review_candidate", "is_review_candidate"), False)
        )
        points.append(
            _CataloguePoint(
                object_id=object_id,
                name=_metadata(record, _NAME_FIELDS, f"Object {object_id}"),
                object_type=_object_type(_value(record, _TYPE_FIELDS)),
                x_km=position[0],
                y_km=position[1],
                z_km=position[2],
                trail_km=_trail_km(record),
                element_epoch=_metadata(record, ("element_epoch", "epoch", "epoch_utc")),
                source_group=_metadata(record, ("source_group", "group", "dataset")),
                orbit_regime=_metadata(record, ("orbit_regime", "regime")),
                selected=selected,
                review_candidate=review_candidate and not selected,
            )
        )
    return points, invalid


def _earth_surface() -> go.Surface:
    longitude = np.linspace(0, 2 * pi, 64)
    latitude = np.linspace(0, pi, 32)
    x = EARTH_RADIUS_KM * np.outer(np.cos(longitude), np.sin(latitude))
    y = EARTH_RADIUS_KM * np.outer(np.sin(longitude), np.sin(latitude))
    z = EARTH_RADIUS_KM * np.outer(np.ones_like(longitude), np.cos(latitude))
    texture = np.outer(np.sin(longitude * 2.0) + 1.0, np.ones_like(latitude))
    return go.Surface(
        x=x,
        y=y,
        z=z,
        surfacecolor=texture,
        colorscale=[[0, "#03152f"], [0.45, "#075985"], [1, "#0ea5e9"]],
        showscale=False,
        opacity=0.94,
        hoverinfo="skip",
        lighting={"ambient": 0.52, "diffuse": 0.82, "roughness": 0.78},
        name="Earth",
        showlegend=False,
    )


def _catalogue_hover(point: _CataloguePoint, role: str) -> str:
    return (
        f"<b>{escape(point.name)}</b>"
        f"<br>Catalogue ID: {escape(point.object_id)}"
        f"<br>Display role: {escape(role)}"
        f"<br>Object class: {escape(point.object_type.title())}"
        f"<br>Orbit regime: {escape(point.orbit_regime)}"
        f"<br>Element epoch: {escape(point.element_epoch)}"
        f"<br>Source group: {escape(point.source_group)}"
        "<br>Position units: Earth-centred km"
    )


def _add_globe_trail(figure: go.Figure, point: _CataloguePoint) -> None:
    if len(point.trail_km) < 2:
        return
    selected = point.selected
    role = "Selected object" if selected else "Review candidate"
    x, y, z = zip(*point.trail_km)
    figure.add_trace(
        go.Scatter3d(
            x=x,
            y=y,
            z=z,
            mode="lines",
            line={
                "color": _CYAN_SOFT if selected else _GOLD,
                "width": 5 if selected else 3,
                "dash": "solid" if selected else "dot",
            },
            name=f"{role} · orbit trail",
            legendgroup="selected-trail" if selected else "review-trail",
            hovertemplate=(
                f"<b>{escape(point.name)}</b><br>{role} orbit trail"
                "<br>Public-element context<extra></extra>"
            ),
        )
    )


def _globe_role(point: _CataloguePoint) -> str:
    if point.selected:
        return "Selected object"
    if point.review_candidate:
        return "Review candidate"
    return "Catalogue context"


def build_public_catalogue_globe(
    records: Iterable[object],
    *,
    selected_id: object | None = None,
    review_candidate_ids: Iterable[object] = (),
    title: str = "PUBLIC ORBIT PICTURE",
    source_label: str = "LATEST PUBLIC GP/OMM SNAPSHOT",
    retrieved_at: str | None = None,
    degraded_message: str | None = None,
    height: int = 540,
) -> go.Figure:
    """Build a dark 3D Earth view from generic public-element records.

    A record may be a mapping or an attribute object.  Accepted position forms
    are ``position_km=[x, y, z]`` or ``x_km``/``y_km``/``z_km``; metre-based
    packed positions are also converted when supplied as ``position_m``.
    Optional ``orbit_trail_km`` values are rendered only for the selected
    object and review candidates.
    """

    points, invalid_count = _catalogue_points(
        records,
        selected_id=selected_id,
        review_candidate_ids=review_candidate_ids,
    )
    figure = go.Figure()
    figure.add_trace(_earth_surface())

    for point in points:
        if point.selected or point.review_candidate:
            _add_globe_trail(figure, point)

    grouped: dict[tuple[str, str], list[_CataloguePoint]] = defaultdict(list)
    for point in points:
        grouped[(_globe_role(point), point.object_type)].append(point)

    role_order = {"Catalogue context": 0, "Review candidate": 1, "Selected object": 2}
    for role, object_type in sorted(
        grouped,
        key=lambda key: (role_order[key[0]], key[1]),
    ):
        group = grouped[(role, object_type)]
        symbol, class_colour = _TYPE_STYLE[object_type]
        selected = role == "Selected object"
        review = role == "Review candidate"
        colour = _WHITE if selected else class_colour
        marker: dict[str, object] = {
            "size": 13 if selected else (8 if review else 3.4),
            "color": colour,
            "symbol": symbol,
            "opacity": 1.0 if selected else (0.96 if review else 0.62),
        }
        if selected or review:
            marker["line"] = {
                "color": _CYAN_SOFT if selected else _GOLD,
                "width": 3 if selected else 2,
            }
        figure.add_trace(
            go.Scatter3d(
                x=[point.x_km for point in group],
                y=[point.y_km for point in group],
                z=[point.z_km for point in group],
                mode="markers+text" if selected else "markers",
                text=[escape(point.name) for point in group] if selected else None,
                textposition="top center",
                textfont={"color": _WHITE, "size": 11},
                marker=marker,
                name=f"{role} · {object_type.title()}",
                legendgroup=f"{role}-{object_type}",
                hovertext=[_catalogue_hover(point, role) for point in group],
                hovertemplate="%{hovertext}<extra></extra>",
            )
        )

    title_detail = source_label
    if retrieved_at:
        title_detail += f" · retrieved {retrieved_at}"
    figure.update_layout(
        height=height,
        margin={"l": 0, "r": 0, "t": 72, "b": 35},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": _TEXT},
        title={
            "text": f"<b>{escape(title)}</b><br><sup>{escape(title_detail)}</sup>",
            "font": {"color": _WHITE, "size": 15},
            "x": 0.01,
            "xanchor": "left",
        },
        legend={
            "orientation": "h",
            "y": -0.04,
            "x": 0.01,
            "font": {"color": _TEXT, "size": 10},
            "bgcolor": "rgba(0,0,0,0)",
        },
        hoverlabel={"bgcolor": "#0f172a", "font": {"color": _WHITE}},
        scene={
            "aspectmode": "data",
            "bgcolor": "rgba(0,0,0,0)",
            "xaxis": {"visible": False},
            "yaxis": {"visible": False},
            "zaxis": {"visible": False},
            "camera": {"eye": {"x": 1.42, "y": 1.25, "z": 0.74}},
        },
        meta={
            "valid_record_count": len(points),
            "invalid_record_count": invalid_count,
            "selected_id": None if selected_id is None else str(selected_id),
            "review_candidate_count": sum(point.review_candidate for point in points),
        },
    )
    figure.add_annotation(
        x=0.01,
        y=0.01,
        xref="paper",
        yref="paper",
        xanchor="left",
        yanchor="bottom",
        showarrow=False,
        text="PUBLIC-ELEMENT CONTEXT · APPROXIMATE PROPAGATION · NO RESTRICTED DATA",
        font={"color": _MUTED, "size": 10},
        bgcolor="rgba(3,10,24,.72)",
        borderpad=5,
    )

    selected_found = any(point.selected for point in points)
    if selected_id is not None and not selected_found:
        figure.add_annotation(
            x=0.99,
            y=0.98,
            xref="paper",
            yref="paper",
            xanchor="right",
            yanchor="top",
            showarrow=False,
            text="SELECTED OBJECT NOT PRESENT IN THIS SNAPSHOT",
            font={"color": _GOLD, "size": 11},
            bgcolor="rgba(35,25,6,.84)",
            bordercolor="rgba(251,191,36,.45)",
            borderwidth=1,
            borderpad=6,
        )
    if not points:
        figure.add_annotation(
            x=0.5,
            y=0.54,
            xref="paper",
            yref="paper",
            showarrow=False,
            text=(
                "<b>NO VALID PUBLIC ELEMENT POSITIONS</b>"
                "<br><span style='font-size:11px'>Catalogue view unavailable; "
                "the separate synthetic policy fixture remains independent.</span>"
            ),
            align="center",
            font={"color": _WHITE, "size": 16},
            bgcolor="rgba(3,10,24,.86)",
            bordercolor="rgba(148,163,184,.28)",
            borderwidth=1,
            borderpad=12,
        )
    if invalid_count:
        figure.add_annotation(
            x=0.99,
            y=0.02,
            xref="paper",
            yref="paper",
            xanchor="right",
            showarrow=False,
            text=f"{invalid_count:,} RECORDS OMITTED · POSITION UNAVAILABLE",
            font={"color": _MUTED, "size": 10},
        )
    if degraded_message:
        figure.add_annotation(
            x=0.99,
            y=0.98,
            xref="paper",
            yref="paper",
            xanchor="right",
            yanchor="top",
            showarrow=False,
            text=f"CACHED / DEGRADED · {escape(degraded_message)}",
            font={"color": _GOLD, "size": 11},
            bgcolor="rgba(35,25,6,.84)",
            bordercolor="rgba(251,191,36,.45)",
            borderwidth=1,
            borderpad=6,
        )
    return figure


@dataclass(frozen=True)
class _ScreenCandidate:
    object_id: str
    name: str
    object_type: str
    min_range_km: float
    tca_hours: float
    tca_utc: str
    element_age: str
    source_group: str


def _range_km(record: object) -> float | None:
    kilometres = _number(
        _value(
            record,
            ("min_range_km", "minimum_range_km", "min_separation_km", "closest_range_km"),
        )
    )
    if kilometres is not None:
        return kilometres
    metres = _number(
        _value(
            record,
            ("min_range_m", "minimum_range_m", "min_separation_m", "closest_range_m"),
        )
    )
    return None if metres is None else metres / 1_000.0


def _tca_hours(record: object) -> float | None:
    hours = _number(_value(record, ("tca_hours", "hours_to_tca", "sampled_tca_hours")))
    if hours is not None:
        return hours
    seconds = _number(
        _value(record, ("tca_seconds", "seconds_to_tca", "sampled_tca_seconds"))
    )
    return None if seconds is None else seconds / 3_600.0


def _screen_candidates(
    records: Iterable[object],
    *,
    horizon_hours: float,
) -> tuple[list[_ScreenCandidate], int, int]:
    candidates: list[_ScreenCandidate] = []
    invalid = 0
    outside_horizon = 0
    for index, record in enumerate(records):
        minimum_range = _range_km(record)
        tca_hours = _tca_hours(record)
        if minimum_range is None or tca_hours is None or minimum_range < 0 or tca_hours < 0:
            invalid += 1
            continue
        if tca_hours > horizon_hours:
            outside_horizon += 1
            continue
        object_id = _record_id(record, index)
        candidates.append(
            _ScreenCandidate(
                object_id=object_id,
                name=_metadata(record, _NAME_FIELDS, f"Object {object_id}"),
                object_type=_object_type(_value(record, _TYPE_FIELDS)),
                min_range_km=minimum_range,
                tca_hours=tca_hours,
                tca_utc=_metadata(record, ("tca_utc", "sampled_tca_utc", "tca")),
                element_age=_metadata(
                    record,
                    ("element_age", "element_age_hours", "gp_age", "gp_age_days"),
                ),
                source_group=_metadata(record, ("source_group", "group", "dataset")),
            )
        )
    candidates.sort(
        key=lambda candidate: (
            candidate.min_range_km,
            candidate.tca_hours,
            candidate.name,
            candidate.object_id,
        )
    )
    return candidates, invalid, outside_horizon


def _format_range_km(value: float) -> str:
    if value < 1:
        return f"{value * 1_000:.0f} m"
    if value < 100:
        return f"{value:.2f} km"
    return f"{value:,.0f} km"


def _format_hours(value: float) -> str:
    total_minutes = round(value * 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"+{hours} h {minutes} min"
    if hours:
        return f"+{hours} h"
    return f"+{minutes} min"


def _radial_value(range_km: float) -> float:
    return log10(1.0 + max(range_km, 0.0))


def _candidate_hover(candidate: _ScreenCandidate, rank: int) -> str:
    return (
        f"<b>{escape(candidate.name)}</b>"
        f"<br>Candidate ID: {escape(candidate.object_id)}"
        f"<br>Display role: Review candidate #{rank}"
        f"<br>Object class: {escape(candidate.object_type.title())}"
        f"<br>Source-model minimum range: {_format_range_km(candidate.min_range_km)}"
        f"<br>Source-model TCA: {_format_hours(candidate.tca_hours)}"
        f"<br>TCA UTC: {escape(candidate.tca_utc)}"
        f"<br>Element age: {escape(candidate.element_age)}"
        f"<br>Source group: {escape(candidate.source_group)}"
    )


def _radial_ticks(max_range_km: float) -> tuple[list[float], list[str]]:
    candidates = (0.1, 1.0, 10.0, 100.0, 1_000.0, 10_000.0, 100_000.0)
    ceiling = max(1.0, max_range_km * 1.2)
    chosen = [value for value in candidates if value <= ceiling]
    next_values = [value for value in candidates if value > ceiling]
    if next_values:
        chosen.append(next_values[0])
    if not chosen:
        chosen = [1.0]
    return [_radial_value(value) for value in chosen], [_format_range_km(value) for value in chosen]


def build_public_proximity_screen(
    candidates: Iterable[object],
    *,
    selected_name: str = "Public screening set",
    centre_role: str = "Screening basis",
    horizon_hours: float = 6.0,
    top_n: int = 12,
    title: str = "PUBLIC-ELEMENT PROXIMITY SCREEN",
    source_label: str = "PUBLIC SOURCE-MODEL CANDIDATES",
    degraded_message: str | None = None,
    height: int = 540,
) -> go.Figure:
    """Build a radial candidate screen with declared range and time encodings.

    Candidate records may be mappings or attribute objects.  They need a
    source-model minimum range in kilometres (``min_range_km`` and common
    aliases) and relative time to closest approach (``tca_hours`` or
    ``tca_seconds`` and common aliases). Radius uses a logarithmic display
    transform and angle maps zero through the declared horizon clockwise.
    ``selected_name`` names the centre marker, while ``centre_role`` makes clear
    whether that marker represents an object or an aggregate source result.
    """

    if not isfinite(horizon_hours) or horizon_hours <= 0:
        raise ValueError("horizon_hours must be a finite value greater than zero")
    if top_n <= 0:
        raise ValueError("top_n must be greater than zero")

    all_candidates, invalid_count, outside_horizon_count = _screen_candidates(
        candidates,
        horizon_hours=horizon_hours,
    )
    displayed = all_candidates[:top_n]
    figure = go.Figure()

    edge_theta: list[float | None] = []
    edge_radius: list[float | None] = []
    for candidate in displayed:
        theta = min(359.9, 360.0 * candidate.tca_hours / horizon_hours)
        radius = _radial_value(candidate.min_range_km)
        edge_theta.extend([theta, theta, None])
        edge_radius.extend([0.0, radius, None])
    if displayed:
        figure.add_trace(
            go.Scatterpolar(
                theta=edge_theta,
                r=edge_radius,
                mode="lines",
                line={"color": "rgba(148,163,184,.25)", "width": 1},
                hoverinfo="skip",
                name="Candidate link",
                showlegend=False,
            )
        )

    figure.add_trace(
        go.Scatterpolar(
            theta=[0],
            r=[0],
            mode="markers+text",
            marker={
                "size": 18,
                "symbol": "diamond",
                "color": _WHITE,
                "line": {"color": _CYAN_SOFT, "width": 3},
            },
            text=[escape(selected_name)],
            textposition="middle right",
            textfont={"color": _WHITE, "size": 11},
            name=f"{escape(centre_role)} · centre diamond",
            hovertemplate=(
                f"<b>{escape(selected_name)}</b>"
                f"<br>Display role: {escape(centre_role)}"
                "<br>Screen centre<extra></extra>"
            ),
        )
    )

    grouped: dict[str, list[tuple[int, _ScreenCandidate]]] = defaultdict(list)
    for rank, candidate in enumerate(displayed, start=1):
        grouped[candidate.object_type].append((rank, candidate))

    for object_type in sorted(grouped):
        group = grouped[object_type]
        symbol, colour = _TYPE_STYLE[object_type]
        figure.add_trace(
            go.Scatterpolar(
                theta=[
                    min(359.9, 360.0 * candidate.tca_hours / horizon_hours)
                    for _, candidate in group
                ],
                r=[_radial_value(candidate.min_range_km) for _, candidate in group],
                mode="markers+text",
                marker={
                    "size": [12 if rank <= 3 else 9 for rank, _ in group],
                    "symbol": symbol,
                    "color": colour,
                    "opacity": 0.98,
                    "line": {"color": _GOLD, "width": 1.5},
                },
                text=[f"#{rank}" if rank <= 3 else "" for rank, _ in group],
                textposition="middle right",
                textfont={"color": _WHITE, "size": 10},
                name=f"Review candidate · {object_type.title()} · {symbol}",
                legendgroup=f"candidate-{object_type}",
                hovertext=[_candidate_hover(candidate, rank) for rank, candidate in group],
                hovertemplate="%{hovertext}<extra></extra>",
            )
        )

    max_range = max((candidate.min_range_km for candidate in displayed), default=1.0)
    radial_tick_values, radial_tick_text = _radial_ticks(max_range)
    quarter = horizon_hours / 4.0
    figure.update_layout(
        height=height,
        margin={"l": 35, "r": 35, "t": 88, "b": 55},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=_PLOT_BG,
        font={"color": _TEXT},
        title={
            "text": (
                f"<b>{escape(title)}</b>"
                "<br><sup>Radius = source-model minimum range · "
                f"angle = source-model TCA · {escape(source_label)}</sup>"
            ),
            "font": {"color": _WHITE, "size": 15},
            "x": 0.01,
            "xanchor": "left",
        },
        polar={
            "bgcolor": _PLOT_BG,
            "radialaxis": {
                "range": [0, max(radial_tick_values[-1], _radial_value(max_range) + 0.08)],
                "tickmode": "array",
                "tickvals": radial_tick_values,
                "ticktext": radial_tick_text,
                "gridcolor": _GRID,
                "linecolor": _GRID,
                "tickfont": {"color": _MUTED, "size": 10},
                "angle": 90,
            },
            "angularaxis": {
                "rotation": 90,
                "direction": "clockwise",
                "tickmode": "array",
                "tickvals": [0, 90, 180, 270],
                "ticktext": [
                    "SOURCE AS-OF",
                    _format_hours(quarter),
                    _format_hours(quarter * 2),
                    _format_hours(quarter * 3),
                ],
                "gridcolor": _GRID,
                "linecolor": _GRID,
                "tickfont": {"color": _MUTED, "size": 10},
            },
        },
        legend={
            "orientation": "h",
            "y": -0.12,
            "x": 0.01,
            "font": {"color": _TEXT, "size": 10},
            "bgcolor": "rgba(0,0,0,0)",
        },
        hoverlabel={"bgcolor": "#0f172a", "font": {"color": _WHITE}},
        meta={
            "valid_candidate_count": len(all_candidates),
            "displayed_candidate_count": len(displayed),
            "invalid_candidate_count": invalid_count,
            "outside_horizon_count": outside_horizon_count,
            "horizon_hours": horizon_hours,
            "top_n": top_n,
        },
    )
    figure.add_annotation(
        x=0.5,
        y=-0.08,
        xref="paper",
        yref="paper",
        showarrow=False,
        text="CANDIDATES FOR FURTHER REVIEW · NO COVARIANCE · NOT A FLIGHT DECISION",
        font={"color": _MUTED, "size": 10},
        bgcolor="rgba(3,10,24,.72)",
        borderpad=5,
    )
    if not displayed:
        figure.add_annotation(
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            text=(
                "<b>NO VALID PUBLIC SCREENING CANDIDATES</b>"
                "<br><span style='font-size:11px'>No conclusion can be drawn from "
                "an empty or unavailable public subset.</span>"
            ),
            align="center",
            font={"color": _WHITE, "size": 16},
            bgcolor="rgba(3,10,24,.88)",
            bordercolor="rgba(148,163,184,.28)",
            borderwidth=1,
            borderpad=12,
        )
    if invalid_count:
        figure.add_annotation(
            x=0.99,
            y=0.01,
            xref="paper",
            yref="paper",
            xanchor="right",
            showarrow=False,
            text=f"{invalid_count:,} CANDIDATES OMITTED · RANGE OR TIME UNAVAILABLE",
            font={"color": _MUTED, "size": 10},
        )
    if outside_horizon_count:
        figure.add_annotation(
            x=0.99,
            y=0.045 if invalid_count else 0.01,
            xref="paper",
            yref="paper",
            xanchor="right",
            showarrow=False,
            text=(
                f"{outside_horizon_count:,} CANDIDATES OMITTED · "
                f"OUTSIDE {horizon_hours:g} H DECLARED HORIZON"
            ),
            font={"color": _MUTED, "size": 10},
        )
    if degraded_message:
        figure.add_annotation(
            x=0.99,
            y=0.99,
            xref="paper",
            yref="paper",
            xanchor="right",
            yanchor="top",
            showarrow=False,
            text=f"CACHED / DEGRADED · {escape(degraded_message)}",
            font={"color": _GOLD, "size": 11},
            bgcolor="rgba(35,25,6,.84)",
            bordercolor="rgba(251,191,36,.45)",
            borderwidth=1,
            borderpad=6,
        )
    return figure


__all__ = [
    "EARTH_RADIUS_KM",
    "build_public_catalogue_globe",
    "build_public_proximity_screen",
]
