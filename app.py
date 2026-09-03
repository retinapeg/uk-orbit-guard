"""UK Orbit Guard — public-orbit context and synthetic Parliament policy lab."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from math import pi
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from orbit_guard.conjunction import (
    MODEL_VERSION,
    ManoeuvreOption,
    assess_option,
    required_delta_v,
    result_by_id,
)
from orbit_guard.daytona_rl import runtime_status as daytona_runtime_status
from orbit_guard.debris_catalogue import (
    DebrisLoadResult,
    catalogue_globe_records,
    load_catalogue as load_debris_catalogue,
)
from orbit_guard.demo import (
    ASSUMPTIONS,
    assess_scenario,
    build_committee_brief,
    build_record,
    validate_demo,
)
from orbit_guard.evidence import (
    MONTHLY_COLLISION_RISKS,
    MONTHLY_COLLISION_RISKS_URL,
    PUBLIC_EVIDENCE,
)
from orbit_guard.public_data import (
    DEFAULT_CACHE_PATH,
    DEFAULT_FIXTURE_PATH,
    REFRESH_TTL,
    PublicDataError,
    PublicSnapshotStore,
    SnapshotLoadResult,
    snapshot_to_globe_records,
    snapshot_to_screen_candidates,
    urllib_transport,
)
from orbit_guard.public_visuals import (
    build_public_catalogue_globe,
    build_public_proximity_screen,
)
from orbit_guard.rl_core import (
    DEFAULT_STEPS as RL_DEFAULT_STEPS,
    MAX_OBJECTS as RL_MAX_OBJECTS,
    MODEL_VERSION as RL_MODEL_VERSION,
    SAFETY_RADIUS_KM as RL_SAFETY_RADIUS_KM,
    default_hazards,
    hazards_from_payload,
    make_hazard,
    scenario_fingerprint as rl_scenario_fingerprint,
    simulate_policy,
)
from orbit_guard.rl_visuals import (
    action_mix,
    build_command_globe,
    build_encounter_replay,
    build_training_curve,
)
from orbit_guard.scenario_io import load_scenario, scenario_sha256
from orbit_guard.training_controller import (
    RunHandle,
    TrainingControllerError,
    discover_active,
    load_last_verified,
    load_request as load_training_request,
    load_result as load_training_result,
    read_state as read_training_state,
    start_training,
)

ROOT = Path(__file__).resolve().parent
SCENARIO_PATH = ROOT / "scenarios" / "uk_eo_demo_1.json"
scenario = load_scenario(SCENARIO_PATH)
results = assess_scenario(scenario)
record = build_record(
    scenario,
    results,
    scenario_file_sha256=scenario_sha256(SCENARIO_PATH),
)
brief = build_committee_brief(record)

CELESTRAK_GP_DOCS_URL = (
    "https://celestrak.org/NORAD/documentation/gp-data-formats.php"
)
CELESTRAK_SOCRATES_URL = "https://celestrak.org/SOCRATES/"
CAA_CAP2207_URL = (
    "https://www.caa.co.uk/data-and-publications/publications/documents/content/cap2207/"
)
SPACE_TRACK_DOCS_URL = "https://www.space-track.org/documentation"
UTC = timezone.utc
PUBLIC_REFRESH_COOLDOWN = REFRESH_TTL

UK_PUBLIC_REGISTRY_CONTEXT: dict[int, dict[str, str]] = {
    35_683: {
        "registry": "CAA CAP2207",
        "designation": "2009-041C",
        "function": "Disaster-monitoring catalogue example",
    },
    60_470: {
        "registry": "CAA CAP2207 v17",
        "designation": "2024-149C",
        "function": "Earth observation",
    },
    66_745: {
        "registry": "CAA CAP2207 v17",
        "designation": "2025-276CH",
        "function": "Data collection",
    },
}

st.set_page_config(
    page_title="UK Orbit Guard",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

if "rl_hazards" not in st.session_state:
    st.session_state.rl_hazards = default_hazards()
if "rl_result" not in st.session_state:
    st.session_state.rl_result = None
if "rl_result_mode" not in st.session_state:
    st.session_state.rl_result_mode = None
if "rl_reattach_error" not in st.session_state:
    st.session_state.rl_reattach_error = None
if "rl_terminal_notice" not in st.session_state:
    st.session_state.rl_terminal_notice = None
if "rl_run_handle" not in st.session_state:
    active_run = discover_active()
    if active_run is not None:
        st.session_state.rl_run_handle = {
            "invocation_id": active_run.invocation_id,
            "run_dir": str(active_run.run_dir),
        }
        try:
            active_request = load_training_request(active_run)
            st.session_state.rl_hazards = hazards_from_payload(
                active_request["hazards"]
            )
        except (OSError, ValueError, TrainingControllerError):
            # The status panel will expose the malformed run without inventing
            # a different scenario or starting a replacement process.
            st.session_state.rl_reattach_error = (
                "active controller request could not be validated"
            )
        else:
            st.session_state.rl_reattach_error = None
    else:
        st.session_state.rl_run_handle = None
if "debris_live_tracking" not in st.session_state:
    st.session_state.debris_live_tracking = True
if "debris_result" not in st.session_state:
    try:
        st.session_state.debris_result = load_debris_catalogue(allow_network=False)
        st.session_state.debris_error = None
    except PublicDataError as error:
        st.session_state.debris_result = None
        st.session_state.debris_error = str(error)
if "debris_display_records" not in st.session_state:
    debris_loaded = st.session_state.debris_result
    if debris_loaded is not None:
        display_time = datetime.now(UTC)
        st.session_state.debris_display_records = catalogue_globe_records(
            debris_loaded.catalogue,
            at=display_time,
        )
        st.session_state.debris_displayed_at = display_time
    else:
        st.session_state.debris_display_records = []
        st.session_state.debris_displayed_at = datetime.now(UTC)

st.markdown(
    """
<style>
:root {
  --ink: #030712;
  --panel: rgba(7, 18, 38, 0.88);
  --cyan: #22d3ee;
  --cyan-soft: #67e8f9;
  --red: #fb4b5c;
  --gold: #fbbf24;
  --white: #f8fafc;
  --muted: #9fb1c8;
  --line: rgba(103, 232, 249, 0.18);
}

.stApp {
  background:
    radial-gradient(circle at 77% 8%, rgba(30, 64, 175, 0.22), transparent 27rem),
    radial-gradient(circle at 12% 30%, rgba(8, 145, 178, 0.10), transparent 24rem),
    linear-gradient(145deg, #020617 0%, #071225 52%, #020617 100%);
  color: var(--white);
}

[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu { display:none !important; }
.block-container { max-width: 1440px; padding-top: .7rem; padding-bottom: 4rem; }
html, body, [class*="css"] { font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
h1, h2, h3 { font-family: "Arial Narrow", "Aptos Display", ui-sans-serif, sans-serif !important; letter-spacing: .02em; }

.classification {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: .55rem;
  margin: 0 0 .62rem;
  padding: .36rem .7rem;
  border: 1px solid rgba(34, 211, 238, .44);
  border-radius: 999px;
  color: #cffafe;
  background: linear-gradient(90deg, rgba(8,47,73,.72), rgba(15,23,42,.88), rgba(8,47,73,.72));
  font-family: "Arial Narrow", "Aptos Display", ui-sans-serif, sans-serif;
  font-size: .76rem;
  font-weight: 700;
  letter-spacing: .14em;
  text-transform: uppercase;
  box-shadow: 0 0 30px rgba(34, 211, 238, .10);
}

.classification .pulse {
  width: .48rem; height: .48rem; border-radius: 50%; background: var(--gold);
  box-shadow: 0 0 0 0 rgba(251,191,36,.65); animation: pulse 2s infinite;
}
@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(251,191,36,.6); } 70% { box-shadow: 0 0 0 9px rgba(251,191,36,0); } 100% { box-shadow: 0 0 0 0 rgba(251,191,36,0); } }

.hero {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(34, 211, 238, .28);
  border-radius: 22px;
  padding: .78rem 1.25rem .88rem;
  background:
    linear-gradient(100deg, rgba(6, 16, 35, .97), rgba(8, 47, 73, .68)),
    repeating-linear-gradient(90deg, transparent 0, transparent 39px, rgba(34,211,238,.03) 40px);
  box-shadow: 0 22px 70px rgba(0,0,0,.34), inset 0 1px 0 rgba(255,255,255,.04);
}
.hero:after {
  content: ""; position: absolute; width: 360px; height: 360px; right: -135px; top: -210px;
  border: 1px solid rgba(34,211,238,.28); border-radius: 50%;
  box-shadow: 0 0 0 35px rgba(34,211,238,.035), 0 0 0 85px rgba(34,211,238,.02);
}
.eyebrow { color: var(--cyan-soft); font-size: .78rem; font-weight: 700; letter-spacing: .18em; text-transform: uppercase; }
.hero-title { margin: .04rem 0 0; font-family: "Arial Narrow", "Aptos Display", ui-sans-serif, sans-serif; font-size: clamp(2.25rem, 4vw, 4.15rem); line-height: .92; font-weight: 700; letter-spacing: -.02em; }
.hero-title span { color: var(--cyan); text-shadow: 0 0 24px rgba(34,211,238,.25); }
.hero-sub { margin: .35rem 0 .42rem; max-width: 980px; color: #d8e5f5; font-size: .96rem; line-height: 1.42; }
.hero-meta { color: var(--muted); font-family: monospace; font-size: .77rem; }
.mission-strip { display:flex; flex-wrap:wrap; gap:.38rem; margin-top:.5rem; }
.mission-chip { padding:.25rem .52rem; border:1px solid rgba(34,211,238,.2); border-radius:6px; background:rgba(2,6,23,.48); color:#bfeef6; font-size:.68rem; font-weight:600; letter-spacing:.04em; text-transform:uppercase; }

[data-testid="stMetric"] {
  border: 1px solid rgba(148, 163, 184, .16);
  border-top: 2px solid rgba(34, 211, 238, .55);
  border-radius: 12px;
  padding: .85rem 1rem;
  background: linear-gradient(145deg, rgba(15, 23, 42, .92), rgba(4, 20, 39, .78));
  box-shadow: 0 12px 35px rgba(0,0,0,.18);
}
[data-testid="stMetricLabel"] { color: #9fb1c8; }
[data-testid="stMetricValue"] { font-family: "Arial Narrow", "Aptos Display", ui-sans-serif, sans-serif; color: #f8fafc; letter-spacing: .02em; }

.panel, .defence-panel, .recommendation, .question-card, .source-card {
  border: 1px solid rgba(148, 163, 184, .16);
  border-radius: 14px;
  background: linear-gradient(145deg, rgba(15,23,42,.92), rgba(4,17,34,.88));
  box-shadow: 0 13px 40px rgba(0,0,0,.16);
}
.panel { padding: 1.05rem 1.15rem; }
.panel-kicker { color: var(--cyan); font: 700 .75rem "Inter",sans-serif; letter-spacing:.13em; text-transform:uppercase; }
.panel h3 { margin: .25rem 0 .45rem; font-size: 1.7rem; }
.panel p { color: #c7d5e8; line-height:1.55; margin:.35rem 0; }
.telemetry { display:grid; grid-template-columns:1fr 1fr; gap:.55rem; margin-top:.8rem; }
.telemetry div { padding:.65rem; background:rgba(2,6,23,.42); border-left:2px solid var(--cyan); }
.telemetry small { display:block; color:#7890aa; text-transform:uppercase; letter-spacing:.08em; }
.telemetry strong { font-family:"Arial Narrow","Aptos Display",ui-sans-serif,sans-serif; font-size:1.25rem; }

.recommendation { border-color:rgba(34,211,238,.38); padding:1.05rem 1.2rem; background:linear-gradient(120deg,rgba(8,47,73,.8),rgba(15,23,42,.9)); }
.recommendation strong { color:var(--cyan-soft); }
.recommendation .big { font:700 2rem "Arial Narrow","Aptos Display",ui-sans-serif,sans-serif; color:white; }
.status-met { color:#86efac; }
.status-miss { color:#fda4af; }

.defence-panel { padding:1.2rem 1.3rem; border-color:rgba(251,191,36,.34); background:linear-gradient(120deg,rgba(35,25,6,.72),rgba(6,18,38,.94)); }
.defence-panel .kicker { color:var(--gold); text-transform:uppercase; font-weight:700; letter-spacing:.14em; font-size:.75rem; }
.defence-panel h3 { margin:.25rem 0 .4rem; font-size:2rem; }
.defence-panel p { color:#dae5f2; max-width:1050px; line-height:1.55; }
.defence-panel a { color:#fde68a; }

.question-card { min-height:172px; padding:1rem 1.05rem; border-top:2px solid rgba(34,211,238,.65); }
.question-number { font:700 2rem "Arial Narrow","Aptos Display",ui-sans-serif,sans-serif; color:rgba(34,211,238,.55); }
.question-card p { color:#d5e1ef; line-height:1.45; }
.source-card { min-height:164px; padding:1rem; }
.source-value { font:700 2.15rem "Arial Narrow","Aptos Display",ui-sans-serif,sans-serif; color:white; }
.source-title { color:var(--cyan-soft); text-transform:uppercase; font-size:.7rem; font-weight:700; letter-spacing:.1em; }
.source-card p { color:#aebdd0; font-size:.85rem; line-height:1.45; }
.source-card a { color:#7dd3fc; font-size:.8rem; }

.data-ribbon { display:flex; flex-wrap:wrap; gap:.45rem; align-items:center; margin:.6rem 0 .8rem; padding:.7rem .85rem; border:1px solid rgba(34,211,238,.28); border-left:4px solid var(--cyan); border-radius:10px; background:rgba(4,20,39,.8); color:#dbeafe; font-family:monospace; font-size:.76rem; }
.data-ribbon strong { color:#67e8f9; letter-spacing:.08em; }
.data-pill { padding:.22rem .45rem; border:1px solid rgba(148,163,184,.2); border-radius:999px; color:#b8c7da; background:rgba(2,6,23,.52); }
.orbit-inspector { padding:1.05rem 1.1rem; border:1px solid rgba(34,211,238,.24); border-radius:14px; background:linear-gradient(160deg,rgba(8,47,73,.52),rgba(4,12,28,.94)); min-height:450px; }
.orbit-inspector h3 { margin:.15rem 0 .55rem; font-size:1.65rem; }
.orbit-inspector .object-id { color:#67e8f9; font-family:monospace; font-size:.78rem; }
.orbit-inspector .limit { margin-top:.8rem; padding:.65rem; border:1px solid rgba(251,191,36,.35); background:rgba(69,45,4,.22); color:#fde68a; font-size:.76rem; line-height:1.45; }
.candidate-stack { display:flex; flex-direction:column; gap:.48rem; margin:.4rem 0 .7rem; }
.candidate-row { display:grid; grid-template-columns:2.15rem minmax(0,1fr) auto; gap:.55rem; align-items:center; padding:.6rem .68rem; border:1px solid rgba(148,163,184,.17); border-left:3px solid rgba(34,211,238,.7); border-radius:9px; background:linear-gradient(110deg,rgba(8,47,73,.38),rgba(2,6,23,.78)); }
.candidate-rank { color:#67e8f9; font:700 1.05rem monospace; }
.candidate-pair { min-width:0; color:#eef6ff; font-size:.78rem; font-weight:700; line-height:1.25; }
.candidate-meta { margin-top:.2rem; color:#8297b0; font:500 .64rem monospace; line-height:1.25; }
.candidate-range { color:#fde68a; font:700 1.12rem "Arial Narrow","Aptos Display",sans-serif; text-align:right; white-space:nowrap; }
.candidate-range small { display:block; color:#8fa3bb; font:500 .58rem monospace; letter-spacing:.05em; text-transform:uppercase; }
.method-rail { margin:.75rem 0; padding:.72rem .8rem; border:1px solid rgba(148,163,184,.16); border-radius:10px; background:rgba(2,6,23,.58); color:#9fb1c8; font:600 .72rem monospace; letter-spacing:.035em; text-align:center; }
.method-rail span { color:#22d3ee; padding:0 .25rem; }
.public-boundary { margin:1rem 0 .25rem; padding:1rem 1.1rem; border:1px solid rgba(251,191,36,.48); border-left:5px solid var(--gold); border-radius:12px; background:linear-gradient(100deg,rgba(69,45,4,.28),rgba(4,17,34,.9)); }
.public-boundary strong { color:#fde68a; font:700 1rem "Arial Narrow","Aptos Display",sans-serif; letter-spacing:.13em; }
.public-boundary p { color:#d5e1ef; margin:.35rem 0 0; line-height:1.48; }
.synthetic-badge { margin:.55rem 0 .7rem; padding:.48rem .65rem; border:1px solid rgba(251,75,92,.38); border-radius:8px; background:rgba(127,29,29,.16); color:#fecdd3; font:700 .72rem monospace; letter-spacing:.06em; }
.command-ribbon { display:flex; flex-wrap:wrap; gap:.48rem; align-items:center; margin:.62rem 0 .8rem; padding:.72rem .9rem; border:1px solid rgba(34,211,238,.4); border-left:5px solid #22d3ee; border-radius:10px; background:linear-gradient(90deg,rgba(8,47,73,.84),rgba(2,6,23,.94)); font:700 .72rem monospace; letter-spacing:.055em; }
.command-ribbon .live-dot { width:.58rem; height:.58rem; border-radius:50%; background:#22d3ee; box-shadow:0 0 18px rgba(34,211,238,.9); }
.command-ribbon .warn-dot { background:#fbbf24; box-shadow:0 0 18px rgba(251,191,36,.75); }
.command-ribbon .fail-dot { background:#fb4b5c; box-shadow:0 0 18px rgba(251,75,92,.75); }
.command-ribbon strong { color:#ecfeff; }
.command-ribbon span { color:#9fb1c8; }
.command-panel { padding:1rem; border:1px solid rgba(103,232,249,.22); border-radius:14px; background:linear-gradient(155deg,rgba(8,47,73,.38),rgba(2,6,23,.93)); box-shadow:inset 0 1px 0 rgba(255,255,255,.035); }
.command-panel h3 { margin:.1rem 0 .35rem; font-size:1.45rem; }
.command-panel p { color:#b9c8db; font-size:.82rem; line-height:1.48; }
.status-rail { display:flex; flex-direction:column; gap:.48rem; margin:.65rem 0; }
.status-step { display:grid; grid-template-columns:1rem 1fr auto; gap:.5rem; align-items:center; padding:.48rem .55rem; border:1px solid rgba(148,163,184,.13); border-radius:7px; background:rgba(2,6,23,.58); color:#71849b; font:700 .66rem monospace; }
.status-step.active { color:#e6fbff; border-color:rgba(34,211,238,.5); background:rgba(8,47,73,.5); box-shadow:0 0 22px rgba(34,211,238,.08); }
.status-step.done { color:#86efac; border-color:rgba(74,222,128,.25); }
.status-step.failed { color:#fda4af; border-color:rgba(251,75,92,.4); }
.generation-rail { display:grid; grid-template-columns:repeat(11,1fr); gap:.28rem; margin:.45rem 0 .85rem; }
.generation-node { padding:.45rem .12rem; text-align:center; border:1px solid rgba(148,163,184,.18); border-radius:6px; background:rgba(2,6,23,.58); color:#64748b; font:700 .65rem monospace; }
.generation-node.available { color:#a5f3fc; border-color:rgba(34,211,238,.35); background:rgba(8,47,73,.38); }
.generation-node.selected { color:#111827; border-color:#fbbf24; background:#fbbf24; box-shadow:0 0 22px rgba(251,191,36,.3); }
.model-card { padding:.9rem 1rem; border:1px solid rgba(167,139,250,.25); border-left:4px solid #a78bfa; border-radius:10px; background:linear-gradient(110deg,rgba(46,16,101,.22),rgba(2,6,23,.9)); }
.model-card strong { color:#ddd6fe; }
.model-card p { margin:.3rem 0; color:#b8c7da; font-size:.78rem; line-height:1.48; }
.object-chip { display:inline-block; margin:.16rem .16rem .16rem 0; padding:.25rem .42rem; border:1px solid rgba(251,113,133,.35); border-radius:5px; color:#fecdd3; background:rgba(127,29,29,.2); font:700 .65rem monospace; }

.stTabs [data-baseweb="tab-list"] { gap:.45rem; margin-top:.55rem; }
.stTabs [data-baseweb="tab"] { height:3.2rem; padding:0 1.15rem; color:#9fb1c8; background:rgba(15,23,42,.62); border-radius:9px 9px 0 0; border:1px solid rgba(148,163,184,.12); }
.stTabs [aria-selected="true"] { color:white !important; border-color:rgba(34,211,238,.42) !important; background:rgba(8,47,73,.62) !important; }
.stButton > button, .stDownloadButton > button { border:1px solid rgba(34,211,238,.48); background:linear-gradient(135deg,#0e7490,#155e75); color:white; font-weight:700; }
.stButton > button:hover, .stDownloadButton > button:hover { border-color:#67e8f9; color:white; box-shadow:0 0 24px rgba(34,211,238,.18); }

.smallprint { color:#7890aa; font-size:.75rem; line-height:1.5; }
.footer-rule { height:1px; margin:2rem 0 1rem; background:linear-gradient(90deg,transparent,rgba(34,211,238,.4),transparent); }
@media (max-width: 800px) { .hero-title { font-size:3.2rem; } .telemetry { grid-template-columns:1fr; } }
</style>
""",
    unsafe_allow_html=True,
)


def format_distance(distance_m: float) -> str:
    return f"{distance_m / 1000:.2f} km" if distance_m >= 1_000 else f"{distance_m:.0f} m"


def format_lead(seconds: float) -> str:
    if seconds >= 3600:
        return f"{seconds / 3600:.2g} h"
    return f"{seconds / 60:.0f} min"


def format_public_utc(value: datetime) -> str:
    """Render a provenance timestamp compactly without implying live telemetry."""

    return value.astimezone(UTC).strftime("%d %b %Y · %H:%M:%S UTC")


def public_origin_label(result: SnapshotLoadResult) -> str:
    if result.origin == "network":
        return "LATEST PUBLIC FETCH"
    if result.origin == "cache":
        return "CACHED PUBLIC SNAPSHOT"
    return "BUNDLED PUBLIC SNAPSHOT"


def mean_orbit_summary(mean_motion: float, eccentricity: float) -> tuple[float, int, int]:
    """Return mean-element period and approximate altitude extrema for display."""

    period_minutes = 1_440.0 / mean_motion
    radians_per_second = mean_motion * 2.0 * pi / 86_400.0
    semi_major_axis_km = (398_600.4418 / radians_per_second**2) ** (1.0 / 3.0)
    perigee_km = round(semi_major_axis_km * (1.0 - eccentricity) - 6_371.0)
    apogee_km = round(semi_major_axis_km * (1.0 + eccentricity) - 6_371.0)
    return period_minutes, perigee_km, apogee_km


def public_snapshot_record(result: SnapshotLoadResult) -> str:
    globe_records = snapshot_to_globe_records(result.snapshot)
    screen_candidates = snapshot_to_screen_candidates(result.snapshot)
    displayed_candidates = [
        candidate
        for candidate in screen_candidates
        if 0.0 <= float(candidate["tca_hours"]) <= 168.0
    ]
    payload = {
        "record_type": "uk_orbit_guard_public_context_snapshot",
        "cache_policy": {
            "origin": result.origin,
            "snapshot_within_two_hour_ttl_at_load": result.fresh,
            "ttl_seconds": int(PUBLIC_REFRESH_COOLDOWN.total_seconds()),
        },
        "display_contract": {
            "catalogue_input_count": len(result.snapshot.objects),
            "catalogue_display_count": len(globe_records),
            "catalogue_invalid_count": len(result.snapshot.objects)
            - len(globe_records),
            "globe_coordinate_frame": "TEME for SGP4 records; labelled element-epoch fallback otherwise",
            "globe_position_methods": sorted(
                {str(record["position_model"]) for record in globe_records}
            ),
            "socrates_input_count": len(result.snapshot.events),
            "socrates_display_horizon_hours": 168.0,
            "socrates_displayed_candidate_count": len(displayed_candidates),
            "socrates_outside_horizon_count": len(screen_candidates)
            - len(displayed_candidates),
            "socrates_invalid_count": len(result.snapshot.events)
            - len(screen_candidates),
        },
        "warning": result.warning,
        "human_authority_required": True,
        "operational_collision_assessment": False,
        "flight_decision": False,
        "snapshot": result.snapshot.to_mapping(),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def load_public_context(*, allow_network: bool) -> SnapshotLoadResult:
    store = PublicSnapshotStore(
        cache_path=DEFAULT_CACHE_PATH,
        fixture_path=DEFAULT_FIXTURE_PATH,
        transport=urllib_transport if allow_network else None,
    )
    return store.load(allow_network=allow_network)


def orbit_context_figure() -> go.Figure:
    """Build a dramatic, explicitly contextual 3D orbit view."""

    earth_radius_km = 6_371.0
    orbit_radius_km = earth_radius_km + 550.0
    longitude = np.linspace(0, 2 * pi, 64)
    latitude = np.linspace(0, pi, 32)
    x = earth_radius_km * np.outer(np.cos(longitude), np.sin(latitude))
    y = earth_radius_km * np.outer(np.sin(longitude), np.sin(latitude))
    z = earth_radius_km * np.outer(np.ones_like(longitude), np.cos(latitude))
    theta = np.linspace(0, 2 * pi, 240)

    figure = go.Figure()
    figure.add_surface(
        x=x,
        y=y,
        z=z,
        surfacecolor=np.outer(np.sin(longitude * 2) + 1, np.ones_like(latitude)),
        colorscale=[[0, "#03152f"], [0.45, "#075985"], [1, "#0ea5e9"]],
        showscale=False,
        opacity=0.92,
        hoverinfo="skip",
        lighting={"ambient": 0.55, "diffuse": 0.8, "roughness": 0.75},
    )
    figure.add_trace(
        go.Scatter3d(
            x=orbit_radius_km * np.cos(theta),
            y=orbit_radius_km * np.sin(theta),
            z=np.zeros_like(theta),
            mode="lines",
            line={"color": "#22d3ee", "width": 5},
            name="Protected asset orbit",
            hoverinfo="skip",
        )
    )
    inclination = np.deg2rad(3.2)
    figure.add_trace(
        go.Scatter3d(
            x=(orbit_radius_km + 28) * np.cos(theta),
            y=(orbit_radius_km + 28) * np.sin(theta) * np.cos(inclination),
            z=(orbit_radius_km + 28) * np.sin(theta) * np.sin(inclination),
            mode="lines",
            line={"color": "#fb4b5c", "width": 3, "dash": "dot"},
            name="Synthetic debris track",
            hoverinfo="skip",
        )
    )
    figure.add_trace(
        go.Scatter3d(
            x=[orbit_radius_km],
            y=[0],
            z=[0],
            mode="markers+text",
            marker={"size": 8, "color": "#fbbf24", "symbol": "diamond"},
            text=["CONJUNCTION WINDOW"],
            textposition="top center",
            textfont={"color": "#fde68a", "size": 11},
            name="Synthetic event",
            hovertemplate="Synthetic event context<extra></extra>",
        )
    )
    figure.update_layout(
        height=470,
        margin={"l": 0, "r": 0, "t": 35, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend={"orientation": "h", "y": 0.02, "x": 0.02, "font": {"color": "#cbd5e1"}},
        title={"text": "ORBITAL CONTEXT / 550 KM LEO", "font": {"color": "#9fb1c8", "size": 12}},
        scene={
            "aspectmode": "data",
            "bgcolor": "rgba(0,0,0,0)",
            "xaxis": {"visible": False},
            "yaxis": {"visible": False},
            "zaxis": {"visible": False},
            "camera": {"eye": {"x": 1.45, "y": 1.25, "z": 0.72}},
        },
    )
    return figure


def encounter_figure(selected_result) -> go.Figure:
    buffer_m = scenario.illustrative_buffer_m
    circle = np.linspace(0, 2 * pi, 240)
    baseline_y = scenario.nominal_tca_offset_m[1]
    result_y = selected_result.projected_tca_offset_m[1]

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=buffer_m * np.cos(circle),
            y=buffer_m * np.sin(circle),
            fill="toself",
            fillcolor="rgba(251,75,92,.07)",
            line={"color": "rgba(251,75,92,.55)", "width": 2, "dash": "dot"},
            name="Illustrative 1 km buffer",
            hoverinfo="skip",
        )
    )
    x_path = np.linspace(-1_600, 1_600, 120)
    figure.add_trace(
        go.Scatter(
            x=x_path,
            y=np.full_like(x_path, baseline_y),
            mode="lines",
            line={"color": "#fb4b5c", "width": 4},
            name="Hold-course relative track",
            hoverinfo="skip",
        )
    )
    if selected_result.option.option_id != "hold":
        figure.add_trace(
            go.Scatter(
                x=x_path,
                y=np.full_like(x_path, result_y),
                mode="lines",
                line={"color": "#22d3ee", "width": 4, "dash": "dash"},
                name="Selected projected track",
                hoverinfo="skip",
            )
        )
    figure.add_trace(
        go.Scatter(
            x=[0], y=[0], mode="markers+text",
            marker={"color": "#67e8f9", "size": 16, "symbol": "diamond", "line": {"color": "white", "width": 1}},
            text=[scenario.protected_asset], textposition="bottom right",
            textfont={"color": "#a5f3fc"}, name="Protected asset",
            hovertemplate="Protected synthetic asset<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[0], y=[baseline_y], mode="markers+text",
            marker={"color": "#fb4b5c", "size": 13, "symbol": "x"},
            text=["120 m baseline"], textposition="top left",
            textfont={"color": "#fda4af"}, name="Baseline TCA",
            hovertemplate="Baseline miss: 120 m<extra></extra>",
        )
    )
    if selected_result.option.option_id != "hold":
        figure.add_trace(
            go.Scatter(
                x=[0], y=[result_y], mode="markers+text",
                marker={"color": "#fbbf24", "size": 14, "symbol": "star"},
                text=[format_distance(selected_result.projected_miss_m)], textposition="top right",
                textfont={"color": "#fde68a"}, name="Selected TCA",
                hovertemplate=f"Projected miss: {selected_result.projected_miss_m:.0f} m<extra></extra>",
            )
        )
    figure.update_layout(
        height=510,
        margin={"l": 10, "r": 10, "t": 50, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(3,10,24,.72)",
        title={"text": "LOCAL ENCOUNTER PLANE / NOMINAL TCA", "font": {"color": "#9fb1c8", "size": 12}},
        xaxis={"title": "Along-track offset (m)", "range": [-1_650, 1_650], "gridcolor": "rgba(148,163,184,.10)", "zerolinecolor": "rgba(148,163,184,.25)"},
        yaxis={"title": "Cross-track offset (m)", "range": [-1_350, 1_450], "scaleanchor": "x", "scaleratio": 1, "gridcolor": "rgba(148,163,184,.10)", "zerolinecolor": "rgba(148,163,184,.25)"},
        font={"color": "#b8c7da"},
        legend={"orientation": "h", "y": -0.12, "font": {"size": 10}},
        hoverlabel={"bgcolor": "#0f172a", "font": {"color": "white"}},
    )
    return figure


def lead_time_figure() -> go.Figure:
    act_now = result_by_id(results, "act_now")
    target_m = act_now.projected_miss_m
    minutes = np.arange(15, 361, 5)
    delta_v = [
        required_delta_v(scenario, lead_time_s=float(minute * 60), target_separation_m=target_m)
        for minute in minutes
    ]
    figure = go.Figure(
        go.Scatter(
            x=minutes / 60,
            y=delta_v,
            mode="lines",
            line={"color": "#22d3ee", "width": 4},
            fill="tozeroy",
            fillcolor="rgba(34,211,238,.08)",
            hovertemplate="Lead time %{x:.2f} h<br>Required Δv %{y:.3f} m/s<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[6, .75], y=[.05, .4], mode="markers+text",
            marker={"color": ["#22d3ee", "#fb4b5c"], "size": [13, 13]},
            text=["ACT NOW · 0.05", "WAIT · 0.40"], textposition=["top left", "top right"],
            textfont={"color": ["#a5f3fc", "#fecdd3"], "size": 11},
            hoverinfo="skip",
        )
    )
    figure.update_layout(
        height=390,
        margin={"l": 10, "r": 10, "t": 55, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(3,10,24,.72)",
        title={"text": "MANOEUVRE DEMAND TO RECOVER THE SAME 1.2 KM MARGIN", "font": {"color": "#dbeafe", "size": 14}},
        xaxis={"title": "Actionable warning lead time (hours)", "gridcolor": "rgba(148,163,184,.10)"},
        yaxis={"title": "Required cross-track Δv (m/s)", "gridcolor": "rgba(148,163,184,.10)", "rangemode": "tozero"},
        font={"color": "#b8c7da"},
        showlegend=False,
    )
    return figure


def monthly_evidence_figure() -> go.Figure:
    months = [item[0] for item in MONTHLY_COLLISION_RISKS]
    values = [item[1] for item in MONTHLY_COLLISION_RISKS]
    colours = ["#22d3ee" if month == "Jul 2026" else "#155e75" for month in months]
    figure = go.Figure(
        go.Bar(
            x=months,
            y=values,
            marker={"color": colours},
            text=[f"{value:,}" if month == "Jul 2026" else "" for month, value in MONTHLY_COLLISION_RISKS],
            textposition="outside",
            hovertemplate="%{x}: %{y:,} reported risks<extra></extra>",
        )
    )
    figure.update_layout(
        height=350,
        margin={"l": 10, "r": 10, "t": 50, "b": 10},
        title={"text": "REPORTED COLLISION RISKS TO UK-LICENSED SATELLITES", "font": {"color": "#dbeafe", "size": 14}},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(3,10,24,.72)",
        font={"color": "#b8c7da"},
        xaxis={"gridcolor": "rgba(148,163,184,.08)"},
        yaxis={"title": "Monthly reported risks", "gridcolor": "rgba(148,163,184,.10)"},
    )
    return figure


def reset_judge_scenario() -> None:
    st.session_state.option_label = "Act now"
    st.session_state.custom_lead_min = 45
    st.session_state.custom_delta_v = 0.05


def render_synthetic_badge() -> None:
    st.markdown(
        f'<div class="synthetic-badge">SYNTHETIC OFFLINE FIXTURE · {scenario.scenario_id} · '
        f'SEED {scenario.seed} · MODEL {MODEL_VERSION} · SEPARATE FROM ALL PUBLIC OBJECTS</div>',
        unsafe_allow_html=True,
    )


RL_PHASES = (
    "QUEUED",
    "CREATING",
    "LIVE",
    "TRAINING",
    "VALIDATING",
    "RESULT_COLLECTED",
    "CLEANED",
    "COMPLETE",
)


def run_handle_from_session() -> RunHandle | None:
    raw = st.session_state.get("rl_run_handle")
    if not isinstance(raw, dict):
        return None
    invocation_id = raw.get("invocation_id")
    run_dir = raw.get("run_dir")
    if not isinstance(invocation_id, str) or not isinstance(run_dir, str):
        return None
    return RunHandle(invocation_id, Path(run_dir))


def remember_run_handle(handle: RunHandle) -> None:
    st.session_state.rl_run_handle = {
        "invocation_id": handle.invocation_id,
        "run_dir": str(handle.run_dir),
    }


def training_state_html(state: dict[str, object]) -> str:
    current = str(state["state"])
    active_index = RL_PHASES.index(current) if current in RL_PHASES else -1
    rows: list[str] = []
    for index, phase in enumerate(RL_PHASES):
        css_class = "status-step"
        marker = "○"
        if current == "FAILED" and phase == "TRAINING":
            css_class += " failed"
            marker = "×"
        elif index < active_index or current == "COMPLETE":
            css_class += " done"
            marker = "✓"
        elif index == active_index:
            css_class += " active"
            marker = "●"
        rows.append(
            f'<div class="{css_class}"><span>{marker}</span>'
            f'<span>{escape(phase.replace("_", " "))}</span><span>{index:02d}</span></div>'
        )
    return '<div class="status-rail">' + "".join(rows) + "</div>"


@st.fragment(run_every=1.0)
def render_training_monitor(invocation_id: str, run_dir: str) -> None:
    handle = RunHandle(invocation_id, Path(run_dir))
    try:
        state = read_training_state(handle)
    except (OSError, ValueError, TrainingControllerError) as error:
        st.error(f"Training state could not be validated: {error}")
        return
    st.markdown(training_state_html(state), unsafe_allow_html=True)
    sandbox_id = state.get("sandbox_id")
    st.caption(
        f"{state['message']} · revision {state['revision']}"
        + (f" · sandbox {sandbox_id}" if sandbox_id else "")
    )
    if state["state"] == "FAILED":
        st.error(
            f"DAYTONA FAILED — no local result was substituted. {state.get('error') or ''}"
        )
        # The fragment was mounted while the parent still considered the run
        # active. A full rerun switches the ribbon and controls into the
        # terminal FAILED state and unmounts this polling fragment.
        st.rerun()
    elif state["state"] == "COMPLETE":
        try:
            result = load_training_result(handle)
        except (OSError, ValueError, TrainingControllerError) as error:
            st.error(f"Completed result failed its envelope check: {error}")
            st.rerun()
        previous = st.session_state.get("rl_result")
        if not isinstance(previous, dict) or previous.get("invocation_id") != result.get("invocation_id"):
            st.session_state.rl_result = result
            st.session_state.rl_result_mode = "live"
            st.rerun()


@st.fragment(run_every=5.0)
def render_live_orbit_globe(
    replay: dict[str, object] | None,
    source_label: str,
) -> None:
    """Advance public mean elements at a visible command-centre cadence."""

    loaded: DebrisLoadResult | None = st.session_state.debris_result
    tracking = bool(st.session_state.debris_live_tracking)
    if tracking and loaded is not None:
        displayed_at = datetime.now(UTC)
        records = catalogue_globe_records(loaded.catalogue, at=displayed_at)
        st.session_state.debris_display_records = records
        st.session_state.debris_displayed_at = displayed_at
    else:
        records = st.session_state.debris_display_records
        displayed_at = st.session_state.debris_displayed_at
    status = (
        "5 s DATED-ELEMENT DISPLAY PROPAGATION"
        if tracking
        else "POSITION TRACK PAUSED"
    )
    st.plotly_chart(
        build_command_globe(
            records,
            replay=replay,
            source_label=f"{source_label} · {status}",
            displayed_at=format_public_utc(displayed_at),
        ),
        width="stretch",
        config={"displayModeBar": False},
        key="command_debris_globe",
    )
    st.caption(
        f"● {status} · {len(records):,} public mean-element objects · "
        "not sensor telemetry"
    )


def generation_rail(selected: int, available: int) -> str:
    nodes = []
    for generation in range(11):
        css_class = "generation-node"
        if generation <= available:
            css_class += " available"
        if generation == selected:
            css_class += " selected"
        nodes.append(
            f'<div class="{css_class}">G{generation}</div>'
        )
    return '<div class="generation-rail">' + "".join(nodes) + "</div>"


st.markdown(
    '<div class="classification"><span class="pulse"></span>Public-data prototype · No restricted feeds · No command · Not for flight operations</div>',
    unsafe_allow_html=True,
)
st.markdown(
    f"""
<section class="hero">
  <div class="eyebrow">UK Parliament Hackathon · Defensive Space Resilience</div>
  <div class="hero-title">UK <span>ORBIT GUARD</span></div>
  <div class="hero-sub"><strong>Conjunction-to-Committee.</strong> Protect the orbital services behind UK air and joint operations: thousands of public debris-field objects → constructed synthetic encounters → an optional Daytona Gen 0→10 execution path → an auditable resilience case for Parliament, UK Space Command and the public services that depend on space.</div>
  <div class="hero-meta">PUBLIC ORBIT FIELD + DAYTONA EXECUTION PATH + SYNTHETIC HILL-FRAME TRAINING · HUMAN AUTHORITY REQUIRED</div>
  <div class="mission-strip">
    <div class="mission-chip">Space-domain awareness</div>
    <div class="mission-chip">Asset protection</div>
    <div class="mission-chip">RAF &amp; joint-force resilience</div>
    <div class="mission-chip">Civil–defence coordination</div>
    <div class="mission-chip">Evidence for scrutiny</div>
  </div>
</section>
""",
    unsafe_allow_html=True,
)

if "public_context_result" not in st.session_state:
    try:
        st.session_state.public_context_result = load_public_context(
            allow_network=False
        )
        st.session_state.public_context_error = None
    except PublicDataError as error:
        st.session_state.public_context_result = None
        st.session_state.public_context_error = str(error)
if "public_refresh_blocked_until" not in st.session_state:
    st.session_state.public_refresh_blocked_until = None

refresh_checked_at = datetime.now(UTC)
refresh_blocked_until = st.session_state.public_refresh_blocked_until
if isinstance(refresh_blocked_until, datetime) and refresh_blocked_until <= refresh_checked_at:
    st.session_state.public_refresh_blocked_until = None
    refresh_blocked_until = None
public_refresh_blocked = isinstance(refresh_blocked_until, datetime)

public_result: SnapshotLoadResult | None = st.session_state.public_context_result

tab_command, tab_public, tab_alert, tab_options, tab_brief = st.tabs(
    [
        "00  SPACE COMMAND",
        "01  PUBLIC ORBIT PICTURE",
        "02  SYNTHETIC ALERT",
        "03  MANOEUVRE OPTIONS",
        "04  COMMITTEE BRIEF",
    ]
)

with tab_command:
    daytona_status = daytona_runtime_status()
    run_handle = run_handle_from_session()
    reattach_error = st.session_state.get("rl_reattach_error")
    run_state: dict[str, object] | None = None
    run_state_error: str | None = None
    if run_handle is not None:
        try:
            run_state = read_training_state(run_handle)
        except (OSError, ValueError, TrainingControllerError) as error:
            reattach_error = (
                "active controller state could not be validated: " + str(error)
            )
            st.session_state.rl_reattach_error = reattach_error
        else:
            phase = str(run_state["state"])
            if phase == "FAILED":
                st.session_state.rl_terminal_notice = {
                    "kind": "failed",
                    "detail": str(run_state.get("error") or run_state["message"]),
                }
                st.session_state.rl_run_handle = None
                st.session_state.rl_reattach_error = None
                run_handle = None
                reattach_error = None
            elif phase == "COMPLETE":
                try:
                    frozen_request = load_training_request(run_handle)
                    frozen_hazards = hazards_from_payload(
                        frozen_request["hazards"]
                    )
                    completed_result = load_training_result(run_handle)
                except (OSError, ValueError, TrainingControllerError) as error:
                    run_state_error = str(error)
                    st.session_state.rl_result = None
                    st.session_state.rl_result_mode = None
                    st.session_state.rl_terminal_notice = {
                        "kind": "rejected",
                        "detail": run_state_error,
                    }
                else:
                    st.session_state.rl_hazards = frozen_hazards
                    st.session_state.rl_result = completed_result
                    st.session_state.rl_result_mode = "live"
                    st.session_state.rl_terminal_notice = None
                st.session_state.rl_run_handle = None
                st.session_state.rl_reattach_error = None
                run_handle = None
                reattach_error = None
            else:
                try:
                    frozen_request = load_training_request(run_handle)
                    frozen_hazards = hazards_from_payload(
                        frozen_request["hazards"]
                    )
                except (OSError, ValueError, TrainingControllerError) as error:
                    reattach_error = (
                        "active controller request could not be validated: "
                        + str(error)
                    )
                    st.session_state.rl_reattach_error = reattach_error
                else:
                    st.session_state.rl_hazards = frozen_hazards
                    st.session_state.rl_reattach_error = None
                    st.session_state.rl_terminal_notice = None
                    reattach_error = None
    rl_hazards = (
        [] if reattach_error else list(st.session_state.rl_hazards)
    )
    current_scenario_hash = rl_scenario_fingerprint(rl_hazards, RL_DEFAULT_STEPS)
    run_active = bool(
        run_state and run_state.get("state") not in {"COMPLETE", "FAILED"}
    ) or bool(run_handle is not None and reattach_error)
    training_result = st.session_state.get("rl_result")
    result_matches_scenario = bool(
        not reattach_error
        and isinstance(training_result, dict)
        and training_result.get("scenario_sha256") == current_scenario_hash
        and training_result.get("model_version") == RL_MODEL_VERSION
    )
    result_mode = st.session_state.get("rl_result_mode")
    terminal_notice = st.session_state.get("rl_terminal_notice")

    if reattach_error:
        ribbon_title = "INCOHERENT ACTIVE RUN"
        ribbon_detail = "FROZEN REQUEST INVALID · SCENARIO DISPLAY WITHHELD"
        ribbon_class = "live-dot warn-dot"
    elif isinstance(terminal_notice, dict) and terminal_notice.get("kind") == "failed":
        ribbon_title = "DAYTONA FAILED"
        ribbon_detail = "NO RESULT ACCEPTED · NO LOCAL TRAINING SUBSTITUTED"
        ribbon_class = "live-dot warn-dot"
    elif isinstance(terminal_notice, dict) and terminal_notice.get("kind") == "rejected":
        ribbon_title = "RESULT REJECTED"
        ribbon_detail = "CONTROLLER OR RESULT EVIDENCE FAILED VALIDATION"
        ribbon_class = "live-dot warn-dot"
    elif run_active and run_state is not None:
        ribbon_title = "LIVE DAYTONA COMPUTE"
        ribbon_detail = (
            f"{run_state['state']} · SANDBOX "
            f"{run_state.get('sandbox_id') or 'AWAITING ID'}"
        )
        ribbon_class = "live-dot"
    elif result_matches_scenario and result_mode == "live":
        ribbon_title = "VERIFIED DAYTONA RESULT"
        ribbon_detail = "GEN 0→10 · RESULT VALIDATED · SANDBOX DELETED"
        ribbon_class = "live-dot"
    elif result_matches_scenario and result_mode == "recorded":
        ribbon_title = "RECORDED DAYTONA REPLAY"
        ribbon_detail = "VALIDATED PRIOR RUN · NOT CURRENT LIVE COMPUTE"
        ribbon_class = "live-dot warn-dot"
    elif daytona_status["ready"]:
        ribbon_title = "DAYTONA READY"
        ribbon_detail = "SYNTHETIC INPUT · PRESS TRAIN TO CREATE ONE PRIVATE SANDBOX"
        ribbon_class = "live-dot"
    else:
        ribbon_title = "LOCAL GEN 0 PREVIEW"
        if not daytona_status["sdk_installed"]:
            readiness_detail = "DAYTONA SDK NOT INSTALLED"
        elif not daytona_status["version_compatible"]:
            readiness_detail = "PINNED DAYTONA SDK VERSION NOT ACTIVE"
        else:
            readiness_detail = "DAYTONA CREDENTIAL NOT PRESENT IN THIS APP PROCESS"
        ribbon_detail = readiness_detail + " · NO TRAINING SUBSTITUTED"
        ribbon_class = "live-dot warn-dot"
    st.markdown(
        f'<div class="command-ribbon"><span class="{ribbon_class}"></span>'
        f'<strong>{escape(ribbon_title)}</strong><span>{escape(ribbon_detail)}</span>'
        f'<span>SCENARIO {"WITHHELD" if reattach_error else current_scenario_hash[:12] + "…"}</span></div>',
        unsafe_allow_html=True,
    )
    if reattach_error:
        st.error(
            "ACTIVE CONTROLLER REQUEST INVALID — its frozen scenario could not be "
            "validated, so the synthetic encounter display and result matching are "
            "withheld. No replacement run will be started while this run remains active."
        )
    elif isinstance(terminal_notice, dict):
        if terminal_notice.get("kind") == "failed":
            st.error(
                "DAYTONA FAILED — no local result was substituted. "
                + str(terminal_notice.get("detail") or "")
            )
        elif terminal_notice.get("kind") == "rejected":
            st.error(
                "RESULT REJECTED — controller or result evidence did not validate. "
                + str(terminal_notice.get("detail") or "")
            )

    debris_result: DebrisLoadResult | None = st.session_state.debris_result
    debris_records = st.session_state.debris_display_records
    if reattach_error:
        baseline_replay = None
        available_generation = 0
        evolution = []
    else:
        baseline_replay = simulate_policy(rl_hazards, max_steps=RL_DEFAULT_STEPS)
        if result_matches_scenario:
            available_generation = int(training_result["generations"])
            evolution = training_result["policy_evolution"]
        else:
            available_generation = 0
            evolution = [
                {
                    "generation": 0,
                    "success": baseline_replay["success"],
                    "termination": baseline_replay["termination"],
                    "reward": baseline_replay["reward"],
                    "min_clearance_km": baseline_replay["min_clearance_km"],
                    "fuel_impulse_m_s": baseline_replay["fuel_impulse_m_s"],
                    "steps": baseline_replay["steps"],
                    "actions": baseline_replay["actions"],
                    "action_names": baseline_replay["action_names"],
                    "trajectory": baseline_replay["trajectory"],
                }
            ]
    if st.session_state.get("rl_generation", 0) > available_generation:
        st.session_state.rl_generation = available_generation

    globe_col, command_col = st.columns([1.72, 0.72], gap="large")
    with globe_col:
        if debris_result is None:
            globe_source = "NO VALIDATED PUBLIC CATALOGUE"
        elif debris_result.origin == "network":
            globe_source = "CURRENT-SESSION CELESTRAK GP FETCH"
        elif debris_result.origin == "cache":
            globe_source = "CACHED CELESTRAK GP SNAPSHOT"
        elif debris_result.origin == "stale cache":
            globe_source = "STALE CACHED CELESTRAK GP SNAPSHOT"
        else:
            globe_source = "BUNDLED CELESTRAK GP REPLAY"
        selected_for_globe = (
            None
            if reattach_error
            else evolution[
                min(st.session_state.get("rl_generation", 0), available_generation)
            ]
        )
        render_live_orbit_globe(selected_for_globe, globe_source)
        sync_col, refresh_debris_col, provenance_col = st.columns([0.75, 0.85, 1.4])
        with sync_col:
            tracking_label = (
                "❚❚ PAUSE TRACK"
                if st.session_state.debris_live_tracking
                else "▶ RESUME TRACK"
            )
            if st.button(tracking_label, width="stretch", disabled=run_active):
                st.session_state.debris_live_tracking = not bool(
                    st.session_state.debris_live_tracking
                )
                st.rerun()
        with refresh_debris_col:
            if st.button("⇣ REFRESH IF DUE", width="stretch", disabled=run_active):
                with st.spinner(
                    "Checking the 12-hour cache and fetching public groups only if due…"
                ):
                    try:
                        refreshed = load_debris_catalogue(allow_network=True)
                    except (PublicDataError, OSError) as error:
                        st.session_state.debris_error = str(error)
                    else:
                        sync_time = datetime.now(UTC)
                        st.session_state.debris_result = refreshed
                        st.session_state.debris_display_records = catalogue_globe_records(
                            refreshed.catalogue, at=sync_time
                        )
                        st.session_state.debris_displayed_at = sync_time
                        st.session_state.debris_error = None
                st.rerun()
        with provenance_col:
            if debris_result is not None:
                st.caption(
                    f"{len(debris_result.catalogue.records):,} records · catalogue "
                    f"{debris_result.catalogue.content_sha256[:12]}… · positions "
                    "propagated with SGP4 for display"
                )
        if st.session_state.get("debris_error"):
            st.warning(
                "Debris refresh failed; the last validated catalogue remains on screen. "
                + str(st.session_state.debris_error)
            )
        elif debris_result is not None and debris_result.warning:
            st.warning(debris_result.warning)
        elif debris_result is not None and not debris_result.fresh:
            st.info(
                "The validated catalogue is older than the 12-hour freshness window. "
                "Position propagation is current to the displayed clock; the source "
                "mean elements are not."
            )

    with command_col:
        st.markdown(
            """
<div class="command-panel">
  <div class="panel-kicker">Encounter injection console</div>
  <h3>GUARD-1 / POLICY LAB</h3>
  <p>Add synthetic local encounters to the controlled satellite. The thousands of public objects remain a separate context layer and are never treated as training truth.</p>
</div>
""",
            unsafe_allow_html=True,
        )
        inject_disabled = run_active or len(rl_hazards) >= RL_MAX_OBJECTS
        if st.button("＋ HEAD-ON OBJECT", width="stretch", disabled=inject_disabled):
            st.session_state.rl_hazards = [
                *rl_hazards,
                make_hazard("head_on", len(rl_hazards)),
            ]
            st.session_state.rl_result = None
            st.session_state.rl_result_mode = None
            st.session_state.rl_generation = 0
            st.rerun()
        if st.button("＋ CROSSING OBJECT", width="stretch", disabled=inject_disabled):
            st.session_state.rl_hazards = [
                *rl_hazards,
                make_hazard("crossing", len(rl_hazards)),
            ]
            st.session_state.rl_result = None
            st.session_state.rl_result_mode = None
            st.session_state.rl_generation = 0
            st.rerun()
        if st.button("＋ FAST DEBRIS", width="stretch", disabled=inject_disabled):
            st.session_state.rl_hazards = [
                *rl_hazards,
                make_hazard("fast_debris", len(rl_hazards)),
            ]
            st.session_state.rl_result = None
            st.session_state.rl_result_mode = None
            st.session_state.rl_generation = 0
            st.rerun()
        chip_html = "".join(
            f'<span class="object-chip">{escape(item.object_id)} · {escape(item.kind.upper().replace("_", " "))}</span>'
            for item in rl_hazards
        ) or '<span class="object-chip">NO LOCAL OBJECTS</span>'
        st.markdown(chip_html, unsafe_allow_html=True)
        clear_col, reset_col = st.columns(2)
        with clear_col:
            if st.button("CLEAR", width="stretch", disabled=run_active or not rl_hazards):
                st.session_state.rl_hazards = []
                st.session_state.rl_result = None
                st.session_state.rl_result_mode = None
                st.session_state.rl_generation = 0
                st.rerun()
        with reset_col:
            if st.button("RESET", width="stretch", disabled=run_active):
                st.session_state.rl_hazards = default_hazards()
                st.session_state.rl_result = None
                st.session_state.rl_result_mode = None
                st.session_state.rl_generation = 0
                st.session_state.rl_run_handle = None
                st.session_state.rl_reattach_error = None
                st.session_state.rl_terminal_notice = None
                st.rerun()

        st.markdown(
            f"""
<div class="model-card">
  <strong>DAYTONA TRAINING CONTRACT (WHEN RUN)</strong>
  <p>{RL_MODEL_VERSION} · 10 generations · 24 candidate policies · 3 perturbed episodes each · 720 requested remote search episodes · seed 42.</p>
  <p>5 mm/s² synthetic acceleration · 20 s hold · 0.10 m/s impulse per commanded step · {RL_SAFETY_RADIUS_KM:.2f} km illustrative keep-out radius.</p>
</div>
""",
            unsafe_allow_html=True,
        )
        st.caption(
            f"Host SDK: {daytona_status['sdk_version'] or 'not installed'} · "
            f"credential: {'present' if daytona_status['credential_present'] else 'missing'}"
        )
        train_disabled = run_active or not rl_hazards or not daytona_status["ready"]
        if st.button(
            "▶ TRAIN GEN 0 → 10 ON DAYTONA",
            type="primary",
            width="stretch",
            disabled=train_disabled,
        ):
            try:
                launched = start_training(
                    rl_hazards,
                    seed=42,
                    generations=10,
                    population=24,
                    episodes_per_candidate=3,
                    max_steps=RL_DEFAULT_STEPS,
                )
            except TrainingControllerError as error:
                st.error(str(error))
            else:
                remember_run_handle(launched)
                st.session_state.rl_result = None
                st.session_state.rl_result_mode = None
                st.session_state.rl_terminal_notice = None
                st.rerun()
        if st.button("↻ LOAD LAST VERIFIED REPLAY", width="stretch", disabled=run_active):
            recorded_result = load_last_verified()
            if recorded_result is None:
                st.warning("No host-validated Daytona replay has been recorded yet.")
            else:
                st.session_state.rl_result = recorded_result
                st.session_state.rl_result_mode = "recorded"
                st.session_state.rl_hazards = hazards_from_payload(
                    recorded_result["hazards"]
                )
                st.session_state.rl_generation = int(recorded_result["generations"])
                # A replay is an explicit operator-selected mode. Detach the
                # terminal controller handle so an earlier FAILED/REJECTED
                # ribbon cannot be paired with this separate recorded result.
                # The original run directory remains on disk for inspection.
                st.session_state.rl_run_handle = None
                st.session_state.rl_reattach_error = None
                st.session_state.rl_terminal_notice = None
                st.rerun()
        if run_handle is not None and run_active:
            render_training_monitor(run_handle.invocation_id, str(run_handle.run_dir))
        elif run_state is not None:
            st.markdown(training_state_html(run_state), unsafe_allow_html=True)
            st.caption(
                f"{run_state['message']} · revision {run_state['revision']}"
                + (
                    f" · sandbox {run_state['sandbox_id']}"
                    if run_state.get("sandbox_id")
                    else ""
                )
            )
            if run_state["state"] == "FAILED":
                st.error(
                    "DAYTONA FAILED — no local result was substituted. "
                    + str(run_state.get("error") or "")
                )
            elif run_state_error:
                st.error(
                    "Completed result failed strict validation: "
                    + run_state_error
                )
        elif run_state_error:
            st.error("Training state could not be reconciled: " + run_state_error)
        elif not daytona_status["ready"]:
            if not daytona_status["sdk_installed"]:
                readiness_fix = "install requirements-live.txt in this environment"
            elif not daytona_status["version_compatible"]:
                readiness_fix = "launch the environment pinned to daytona==0.207.0"
            else:
                readiness_fix = "set DAYTONA_API_KEY in the Streamlit process, then restart"
            st.warning(
                "Live training is correctly locked: " + readiness_fix + ". The Gen 0 "
                "preview is local; no local training result is presented as Daytona."
            )

    if reattach_error:
        st.markdown(
            """
<div class="command-panel">
  <div class="panel-kicker">Synthetic evidence withheld</div>
  <h3>ACTIVE RUN CANNOT BE JOINED TO A VALIDATED SCENARIO.</h3>
  <p>No generation rail, clearance metric, trajectory, action mix, learning curve or run passport is rendered. Preserve the controller record for operator review; do not substitute a new local scenario.</p>
</div>
""",
            unsafe_allow_html=True,
        )
    else:
        if available_generation == 0:
            selected_generation = st.slider(
                "POLICY GENERATION — Gen 1–10 unlock after validated Daytona training",
                min_value=0,
                max_value=10,
                value=0,
                step=1,
                disabled=True,
            )
        else:
            selected_generation = st.slider(
                "POLICY GENERATION — scrub from the untrained baseline to the retained policy",
                min_value=0,
                max_value=available_generation,
                value=min(
                    st.session_state.get("rl_generation", 0), available_generation
                ),
                step=1,
                key="rl_generation",
            )
        st.markdown(
            generation_rail(selected_generation, available_generation),
            unsafe_allow_html=True,
        )
        selected_replay = evolution[selected_generation]
        metric_cols = st.columns(5)
        metric_cols[0].metric(
            "PUBLIC DEBRIS FIELD",
            f"{len(debris_records):,}",
            "3 CELESTRAK GROUPS",
        )
        metric_cols[1].metric(
            "LOCAL OBJECTS", len(rl_hazards), "SYNTHETIC INJECTIONS"
        )
        metric_cols[2].metric(
            "POLICY", f"GEN {selected_generation}", "0 = COAST"
        )
        metric_cols[3].metric(
            "MIN SIMULATED CLEARANCE",
            f"{float(selected_replay['min_clearance_km']):.3f} km",
            "LOCAL TEACHING CASE",
        )
        metric_cols[4].metric(
            "CONTROL IMPULSE",
            f"{float(selected_replay['fuel_impulse_m_s']):.2f} m/s",
            "ACCUMULATED SYNTHETIC",
        )

        replay_col, learning_col = st.columns([1.55, 0.95], gap="large")
        with replay_col:
            st.plotly_chart(
                build_encounter_replay(
                    selected_replay,
                    generation=selected_generation,
                    baseline=evolution[0],
                ),
                width="stretch",
                config={"displayModeBar": False},
                key=f"rl_encounter_gen_{selected_generation}",
            )
            st.caption(
                "Magnified local Hill/LVLH encounter view: x is radial offset and y is "
                "along-track offset. This is not an Earth-centred ephemeris, collision "
                "probability, manoeuvre plan or command link."
            )
        with learning_col:
            if result_matches_scenario:
                st.plotly_chart(
                    build_training_curve(training_result, selected_generation),
                    width="stretch",
                    config={"displayModeBar": False},
                    key="rl_training_curve",
                )
                before = training_result["baseline_evaluation"]
                after = training_result["trained_evaluation"]
                st.markdown(
                    f"""
<div class="recommendation">
  <div class="panel-kicker">Frozen nominal replay · not a safety claim</div>
  <div class="big">{float(before['min_clearance_km']):.3f} → {float(after['min_clearance_km']):.3f} km</div>
  <p>On this one declared synthetic case, the retained Gen 10 checkpoint changed the trajectory from <strong>{escape(str(before['termination']).replace('_', ' '))}</strong> to <strong>{escape(str(after['termination']).replace('_', ' '))}</strong>.</p>
</div>
""",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    """
<div class="command-panel">
  <div class="panel-kicker">Generation evidence awaiting Daytona</div>
  <h3>GEN 0 IS VISIBLE. GEN 1–10 ARE LOCKED.</h3>
  <p>The UI will not invent a learning curve. Once a real sandbox returns a validated changed checkpoint, every retained generation and its trajectory appears here.</p>
</div>
""",
                    unsafe_allow_html=True,
                )
            mix = action_mix(selected_replay)
            st.dataframe(
                pd.DataFrame(
                    {"Action": list(mix), "Held steps": list(mix.values())}
                ),
                hide_index=True,
                width="stretch",
            )

        if result_matches_scenario:
            execution = training_result["daytona_execution"]
            with st.expander("Verified Daytona run passport"):
                st.code(
                    json.dumps(
                        {
                            "invocation_id": execution["invocation_id"],
                            "sandbox_id": execution["sandbox_id"],
                            "sandbox_deleted": execution["sandbox_deleted"],
                            "local_training_fallback_used": execution[
                                "local_training_fallback_used"
                            ],
                            "scenario_sha256": training_result["scenario_sha256"],
                            "runtime_bundle_sha256": execution[
                                "runtime_bundle_sha256"
                            ],
                            "initial_checkpoint_sha256": training_result[
                                "initial_checkpoint_sha256"
                            ],
                            "trained_checkpoint_sha256": training_result[
                                "trained_checkpoint_sha256"
                            ],
                            "training_episodes": training_result[
                                "training_episodes"
                            ],
                            "completed_at_utc": training_result[
                                "completed_at_utc"
                            ],
                        },
                        indent=2,
                    ),
                    language="json",
                )

    st.markdown(
        """
<div class="public-boundary">
  <strong>COMMAND-VIEW BOUNDARY</strong>
  <p>The debris globe is public GP/OMM catalogue context, propagated for display—not live sensor telemetry. The RL encounter is a separate synthetic planar teaching model. Public objects are screened conceptually, never injected as asserted conjunctions. No RAF, MOD, NSpOC or spacecraft system is connected; human authority is required.</p>
</div>
""",
        unsafe_allow_html=True,
    )

with tab_public:
    control_col, source_col = st.columns([0.75, 2.25], gap="large")
    with control_col:
        refresh_requested = st.button(
            "↻  REFRESH PUBLIC DATA IF DUE",
            width="stretch",
            disabled=public_refresh_blocked,
            help=(
                "Explicitly checks the two-hour cache, then makes one bounded request "
                "per allowlisted CelesTrak feed only when the cache is due. A failed "
                "network attempt pauses this control for two hours."
            ),
        )
    with source_col:
        st.caption(
            "Offline cache-first default: a verified cache when present, otherwise the "
            "validated bundled snapshot. Network access occurs only after this control "
            "is pressed; failed refreshes retain the last-known-good record."
        )

    if refresh_requested:
        with st.spinner("Checking cache policy and public CelesTrak feeds…"):
            try:
                st.session_state.public_context_result = load_public_context(
                    allow_network=True
                )
                st.session_state.public_context_error = None
                refreshed_result = st.session_state.public_context_result
                if refreshed_result.origin == "network" or (
                    refreshed_result.warning
                    and "network refresh failed" in refreshed_result.warning.lower()
                ):
                    st.session_state.public_refresh_blocked_until = (
                        datetime.now(UTC) + PUBLIC_REFRESH_COOLDOWN
                    )
            except (PublicDataError, OSError) as error:
                st.session_state.public_context_error = str(error)
                st.session_state.public_refresh_blocked_until = (
                    datetime.now(UTC) + PUBLIC_REFRESH_COOLDOWN
                )
        public_result = st.session_state.public_context_result

    refresh_blocked_until = st.session_state.public_refresh_blocked_until
    if isinstance(refresh_blocked_until, datetime):
        st.info(
            "Public-source refresh is paused for this session until "
            f"{format_public_utc(refresh_blocked_until)} after the last network attempt. "
            "The verified cache/replay remains available; do not retry at the venue."
        )

    public_error = st.session_state.public_context_error
    if public_error:
        st.error(
            "Public context could not be validated. The synthetic policy lab remains "
            f"available and isolated. Detail: {public_error}"
        )

    if public_result is not None:
        public_snapshot = public_result.snapshot
        source_label = public_origin_label(public_result)
        source_timestamp = format_public_utc(public_snapshot.retrieved_at_utc)
        source_hash = public_snapshot.snapshot_sha256
        degraded_message = (
            public_result.warning
            if public_result.warning
            and (
                not public_result.fresh
                or "failed" in public_result.warning.lower()
                or "invalid" in public_result.warning.lower()
            )
            else None
        )
        warning_html = (
            f'<span class="data-pill">{escape(public_result.warning)}</span>'
            if public_result.warning
            else ""
        )
        st.markdown(
            f"""
<div class="data-ribbon">
  <strong>{escape(source_label)}</strong>
  <span class="data-pill">CELESTRAK PUBLIC GP/OMM + SOCRATES</span>
  <span class="data-pill">RECORDED {escape(source_timestamp)}</span>
  <span class="data-pill">SHA-256 {source_hash[:12]}…</span>
  {warning_html}
</div>
""",
            unsafe_allow_html=True,
        )

        element_ages_hours = [
            max(
                0.0,
                (
                    public_snapshot.retrieved_at_utc - object_record.epoch
                ).total_seconds()
                / 3_600.0,
            )
            for object_record in public_snapshot.objects
        ]
        metric_cols = st.columns(4)
        metric_cols[0].metric(
            "PUBLIC OMM OBJECTS", len(public_snapshot.objects), "ALLOWLISTED SUBSET"
        )
        metric_cols[1].metric(
            "SOCRATES ROWS", len(public_snapshot.events), "CANDIDATES FOR REVIEW"
        )
        metric_cols[2].metric(
            "MEDIAN ELEMENT AGE",
            f"{float(np.median(element_ages_hours)):.1f} h",
            "AT SNAPSHOT FETCH",
        )
        metric_cols[3].metric(
            "DECISION AUTHORITY", "HUMAN", "NO COMMAND LINK"
        )

        public_view = st.segmented_control(
            "PUBLIC CONTEXT VIEW",
            options=["Catalogue", "Proximity screen"],
            default="Catalogue",
            key="public_view_mode",
        ) or "Catalogue"

        if public_view == "Catalogue":
            object_ids = [item.norad_catalog_id for item in public_snapshot.objects]
            default_object_id = 35_683 if 35_683 in object_ids else object_ids[0]
            selected_object_id = st.selectbox(
                "SELECT A PUBLIC CATALOGUE OBJECT",
                options=object_ids,
                index=object_ids.index(default_object_id),
                format_func=lambda catalogue_id: (
                    f"{next(item.object_name for item in public_snapshot.objects if item.norad_catalog_id == catalogue_id)} "
                    f"· NORAD {catalogue_id}"
                ),
            )
            selected_object = next(
                item
                for item in public_snapshot.objects
                if item.norad_catalog_id == selected_object_id
            )
            globe_records = snapshot_to_globe_records(
                public_snapshot, selected_id=selected_object_id
            )
            sgp4_record_count = sum(
                item["position_model"] == "SGP4/TEME at snapshot retrieval time"
                for item in globe_records
            )
            if sgp4_record_count == len(globe_records):
                globe_source_label = "CELESTRAK GP/OMM · SGP4/TEME DISPLAY REPLAY"
                globe_degraded_message = degraded_message
            elif sgp4_record_count:
                globe_source_label = "CELESTRAK GP/OMM · MIXED DISPLAY METHODS"
                fallback_message = (
                    f"{len(globe_records) - sgp4_record_count} object(s) use a labelled "
                    "two-body element-epoch fallback"
                )
                globe_degraded_message = " · ".join(
                    item for item in (degraded_message, fallback_message) if item
                )
            else:
                globe_source_label = "CELESTRAK GP/OMM · TWO-BODY DISPLAY FALLBACK"
                globe_degraded_message = " · ".join(
                    item
                    for item in (
                        degraded_message,
                        "SGP4 unavailable; all positions use the labelled element-epoch fallback",
                    )
                    if item
                )
            selected_globe_record = next(
                item
                for item in globe_records
                if item["norad_id"] == selected_object_id
            )
            visual_col, inspector_col = st.columns([1.65, 0.72], gap="large")
            with visual_col:
                st.plotly_chart(
                    build_public_catalogue_globe(
                        globe_records,
                        selected_id=selected_object_id,
                        title="PUBLIC ORBIT PICTURE / RECORDED SNAPSHOT",
                        source_label=globe_source_label,
                        retrieved_at=source_timestamp,
                        degraded_message=globe_degraded_message,
                        height=560,
                    ),
                    width="stretch",
                    config={"displayModeBar": False},
                )
                st.caption(
                    "Earth-centred catalogue display replayed at the recorded snapshot time. "
                    "Positions are propagated public mean elements—not live sensor telemetry."
                )
            with inspector_col:
                period_minutes, perigee_km, apogee_km = mean_orbit_summary(
                    selected_object.mean_motion, selected_object.eccentricity
                )
                age_hours = max(
                    0.0,
                    (
                        public_snapshot.retrieved_at_utc - selected_object.epoch
                    ).total_seconds()
                    / 3_600.0,
                )
                registry_context = UK_PUBLIC_REGISTRY_CONTEXT.get(selected_object_id)
                if registry_context:
                    registry_html = (
                        f'<p><strong>UK registry context</strong><br>{escape(registry_context["registry"])} · '
                        f'{escape(registry_context["designation"])}<br>{escape(registry_context["function"])}</p>'
                    )
                    registry_boundary = (
                        "Public UK-registered catalogue example; no claim of current "
                        "operational status, ownership, manoeuvrability or defence role."
                    )
                else:
                    registry_html = "<p><strong>UK registry context</strong><br>Not asserted</p>"
                    registry_boundary = (
                        "Public catalogue context only; no claim of ownership, status, "
                        "mission, vulnerability or defence relevance."
                    )
                st.markdown(
                    f"""
<div class="orbit-inspector">
  <div class="panel-kicker">Selected public object</div>
  <h3>{escape(selected_object.object_name)}</h3>
  <div class="object-id">NORAD {selected_object.norad_catalog_id} · {escape(selected_object.object_id or "NO INTERNATIONAL DESIGNATOR")}</div>
  <div class="telemetry">
    <div><small>Element epoch</small><strong>{escape(selected_object.epoch.strftime("%d %b · %H:%M"))}</strong></div>
    <div><small>Age at fetch</small><strong>{age_hours:.1f} h</strong></div>
    <div><small>Inclination</small><strong>{selected_object.inclination:.2f}°</strong></div>
    <div><small>Mean period</small><strong>{period_minutes:.1f} min</strong></div>
    <div><small>Approx perigee</small><strong>{perigee_km:,} km</strong></div>
    <div><small>Approx apogee</small><strong>{apogee_km:,} km</strong></div>
  </div>
  {registry_html}
  <p><strong>Display model</strong><br>{escape(str(selected_globe_record["position_model"]))}</p>
  <p><strong>Snapshot fingerprint</strong><br><span class="object-id">{source_hash[:24]}…</span></p>
  <div class="limit">{escape(registry_boundary)} No covariance, precision ephemeris, hard-body radius or operator intent is available here.</div>
</div>
""",
                    unsafe_allow_html=True,
                )
        else:
            candidates = snapshot_to_screen_candidates(public_snapshot)
            socrates_as_of = public_snapshot.provenance.socrates_data_as_of
            socrates_as_of_label = (
                format_public_utc(socrates_as_of)
                if socrates_as_of is not None
                else "NOT RECORDED"
            )
            visual_col, list_col = st.columns([1.38, 1.02], gap="large")
            with visual_col:
                st.plotly_chart(
                    build_public_proximity_screen(
                        candidates,
                        selected_name="BOUNDED SOCRATES PAIR SET",
                        centre_role="Aggregate public screening result",
                        horizon_hours=168.0,
                        top_n=12,
                        title="PUBLIC-ELEMENT PROXIMITY SCREEN / 7-DAY WINDOW",
                        source_label="CELESTRAK SOCRATES · PUBLIC GP MODEL",
                        degraded_message=degraded_message,
                        height=560,
                    ),
                    width="stretch",
                    config={"displayModeBar": False},
                )
                st.caption(
                    "Radius is CelesTrak's published source-model minimum range; angle is "
                    "source-model TCA relative to SOCRATES source as-of "
                    f"{socrates_as_of_label}."
                )
            with list_col:
                st.markdown("### Candidates for further review")
                candidate_cards: list[str] = []
                for rank, item in enumerate(
                    sorted(
                        candidates, key=lambda candidate: candidate["minimum_range_km"]
                    ),
                    start=1,
                ):
                    tca_display = (
                        str(item["tca_utc"])
                        .replace("T", " · ")
                        .replace("Z", " UTC")
                    )
                    candidate_cards.append(
                        '<div class="candidate-row">'
                        f'<div class="candidate-rank">#{rank:02d}</div>'
                        '<div>'
                        f'<div class="candidate-pair">{escape(str(item["first_object_name"]))} ↔ {escape(str(item["second_object_name"]))}</div>'
                        f'<div class="candidate-meta">NORAD {int(item["first_norad_catalog_id"])} / {int(item["second_norad_catalog_id"])} · {escape(tca_display)} · {float(item["relative_speed_km_s"]):.3f} km/s</div>'
                        '</div>'
                        f'<div class="candidate-range">{float(item["minimum_range_km"]):.3f} km<small>source-model min</small></div>'
                        '</div>'
                    )
                st.markdown(
                    '<div class="candidate-stack">'
                    + "".join(candidate_cards)
                    + "</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    """
<div class="panel">
  <div class="panel-kicker">What this screen means</div>
  <p>These are bounded rows parsed from the public CelesTrak SOCRATES model. They are <strong>review candidates</strong>, not UK-DMC 2 events, alerts, threats or declarations of safety.</p>
  <p>No locally calculated probability or pairwise detector is being presented.</p>
</div>
""",
                    unsafe_allow_html=True,
                )

        st.markdown(
            """
<div class="method-rail">PUBLIC GP/OMM <span>→</span> SGP4/TEME ORBIT PICTURE <span>→</span> SOCRATES PUBLIC SCREEN <span>→</span> CANDIDATES FOR REVIEW <span>→</span> STOP: PRECISION OPERATIONAL ASSESSMENT REQUIRED</div>
<div class="public-boundary">
  <strong>PUBLIC SCREEN ENDS HERE</strong>
  <p>Public mean elements do not provide the precision ephemerides, covariance, object geometry, operator intent or validated procedures needed for an operational collision-risk decision. Nothing in this tab selects or recommends a manoeuvre. The separate synthetic policy views are a fictional resilience case.</p>
</div>
""",
            unsafe_allow_html=True,
        )
        action_col, link_col = st.columns([0.8, 2.2], gap="large")
        with action_col:
            st.download_button(
                "↓  DOWNLOAD PUBLIC SNAPSHOT RECORD",
                data=public_snapshot_record(public_result),
                file_name="orbitguard_public_snapshot_record.json",
                mime="application/json",
                width="stretch",
            )
        with link_col:
            st.markdown(
                f"[CelesTrak GP data format ↗]({CELESTRAK_GP_DOCS_URL}) · "
                f"[CelesTrak SOCRATES ↗]({CELESTRAK_SOCRATES_URL}) · "
                f"[CAA UK space-object register ↗]({CAA_CAP2207_URL}) · "
                f"[Public-element operational warning ↗]({SPACE_TRACK_DOCS_URL})"
            )
            st.caption(
                "Source links are provided for scrutiny. The bundled record keeps the "
                "demo repeatable if venue Wi-Fi or a public endpoint is unavailable."
            )
    else:
        st.markdown(
            """
<div class="public-boundary">
  <strong>PUBLIC SCREEN UNAVAILABLE</strong>
  <p>No unvalidated value is substituted. The synthetic command, alert, options and brief views remain self-contained and do not depend on public-object data.</p>
</div>
""",
            unsafe_allow_html=True,
        )

with tab_alert:
    render_synthetic_badge()
    metric_cols = st.columns(4)
    metric_cols[0].metric("TIME TO CLOSEST APPROACH", "06:00:00", "ACTION WINDOW")
    metric_cols[1].metric("PROJECTED MISS", "120 m", "BELOW 1 KM", delta_color="inverse")
    metric_cols[2].metric("ILLUSTRATIVE BUFFER", "1.0 km", "DEMO ONLY")
    metric_cols[3].metric("PROTECTED SERVICE", "EARTH OBS", "FICTIONAL ASSET")

    visual_col, incident_col = st.columns([1.6, 0.75], gap="large")
    with visual_col:
        st.plotly_chart(orbit_context_figure(), width="stretch", config={"displayModeBar": False})
        st.caption("Context visual only — orbital planes are illustrative and not to conjunction-analysis scale.")
    with incident_col:
        st.markdown(
            f"""
<div class="panel" style="margin-top:2.2rem">
  <div class="panel-kicker">Priority conjunction · review required</div>
  <h3>{scenario.protected_asset} / {scenario.secondary_object}</h3>
  <p>A fictional UK Earth-observation asset has a projected <strong>120 m</strong> closest approach in six hours. The decision question is how warning latency changes the manoeuvre budget needed to reach an illustrative 1 km buffer.</p>
  <div class="telemetry">
    <div><small>Relative speed</small><strong>12.0 m/s</strong></div>
    <div><small>Orbit context</small><strong>550 km LEO</strong></div>
    <div><small>Data class</small><strong>Synthetic</strong></div>
    <div><small>Command link</small><strong>None</strong></div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
        if st.button("▶  RUN DETERMINISTIC SCENARIO", type="primary", width="stretch"):
            try:
                validate_demo(record)
            except (KeyError, TypeError, ValueError) as error:
                st.error(f"Scenario integrity check failed: {error}")
            else:
                st.success(
                    "Scenario integrity verified: classification, buffer, 8× fixture and "
                    "human-approval guards passed. No network or API call was made."
                )
        st.markdown(
            '<div class="smallprint">This prototype deliberately contains no real asset identifiers, live NSpOC feed, restricted data, or spacecraft-command capability.</div>',
            unsafe_allow_html=True,
        )

with tab_options:
    render_synthetic_badge()
    if "option_label" not in st.session_state:
        st.session_state.option_label = "Act now"
    if "custom_lead_min" not in st.session_state:
        st.session_state.custom_lead_min = 45
    if "custom_delta_v" not in st.session_state:
        st.session_state.custom_delta_v = 0.05

    top_left, top_right = st.columns([3, 1])
    with top_left:
        option_labels = [result.option.label for result in results]
        selected_label = st.radio(
            "COMPARE THE OPERATOR'S SYNTHETIC OPTIONS",
            option_labels,
            horizontal=True,
            key="option_label",
        )
    with top_right:
        st.write("")
        st.button("↺  RESTORE JUDGE SCENARIO", on_click=reset_judge_scenario, width="stretch")

    selected_result = next(result for result in results if result.option.label == selected_label)
    output_cols = st.columns(4)
    output_cols[0].metric("PROJECTED SEPARATION", format_distance(selected_result.projected_miss_m))
    output_cols[1].metric(
        "ILLUSTRATIVE BUFFER",
        "MET" if selected_result.buffer_met else "NOT MET",
        "1.0 km demo target",
        delta_color="normal" if selected_result.buffer_met else "inverse",
    )
    output_cols[2].metric("MANOEUVRE DEMAND", f"{selected_result.option.cross_track_delta_v_mps:.2f} m/s Δv")
    demand_ratio = selected_result.option.cross_track_delta_v_mps / 0.05
    output_cols[3].metric(
        "DEMAND VS ACT NOW",
        "—" if selected_result.option.option_id == "hold" else f"{demand_ratio:.1f}×",
        format_lead(selected_result.option.lead_time_s),
        delta_color="inverse" if demand_ratio > 1 else "off",
    )

    plot_col, table_col = st.columns([1.35, 1], gap="large")
    with plot_col:
        st.plotly_chart(encounter_figure(selected_result), width="stretch", config={"displayModeBar": False})
        st.caption("Synthetic local encounter geometry — not a complete orbital propagation or safety assessment.")
    with table_col:
        option_rows = []
        for result in results:
            option_rows.append(
                {
                    "Option": result.option.label,
                    "Warning used": format_lead(result.option.lead_time_s),
                    "Δv": f"{result.option.cross_track_delta_v_mps:.2f} m/s",
                    "Projected miss": format_distance(result.projected_miss_m),
                    "1 km buffer": "MET" if result.buffer_met else "NOT MET",
                }
            )
        st.markdown("### Four auditable options")
        st.dataframe(pd.DataFrame(option_rows), hide_index=True, width="stretch")
        st.markdown(
            f"""
<div class="panel">
  <div class="panel-kicker">Selected path</div>
  <h3>{selected_result.option.label}</h3>
  <p>{selected_result.option.description}</p>
  <p><strong class="{'status-met' if selected_result.buffer_met else 'status-miss'}">{'Illustrative buffer met' if selected_result.buffer_met else 'Illustrative buffer not met'}</strong></p>
</div>
""",
            unsafe_allow_html=True,
        )

    st.markdown(
        """
<div class="recommendation">
  <div class="panel-kicker">Scenario recommendation · qualified operator review required</div>
  <div class="big">ACT EARLY: 8× LOWER MANOEUVRE DEMAND</div>
  <p>A 0.05 m/s manoeuvre at six hours reaches 1.20 km projected separation. Waiting until 45 minutes requires 0.40 m/s—eight times the manoeuvre demand—to recover the same margin in this synthetic model.</p>
  <p><strong>Why exactly 8×?</strong> In this ideal linear illustration, required Δv scales inversely with lead time: 6 hours ÷ 45 minutes = 8. This is a constructed comparison, not measured operational performance.</p>
</div>
""",
        unsafe_allow_html=True,
    )

    curve_col, explorer_col = st.columns([1.45, 0.8], gap="large")
    with curve_col:
        st.plotly_chart(lead_time_figure(), width="stretch", config={"displayModeBar": False})
    with explorer_col:
        st.markdown("### Explore the warning window")
        custom_lead_min = st.slider(
            "Actionable warning lead time",
            min_value=15,
            max_value=360,
            step=15,
            key="custom_lead_min",
            format="%d min",
        )
        custom_delta_v = st.slider(
            "Cross-track manoeuvre demand",
            min_value=0.0,
            max_value=0.5,
            step=0.01,
            key="custom_delta_v",
            format="%.2f m/s",
        )
        custom_option = ManoeuvreOption(
            option_id="custom",
            label="Custom policy counterfactual",
            lead_time_s=float(custom_lead_min * 60),
            cross_track_delta_v_mps=float(custom_delta_v),
            description="User-selected synthetic comparison.",
        )
        custom_result = assess_option(scenario, custom_option)
        st.metric("PROJECTED SEPARATION", format_distance(custom_result.projected_miss_m))
        st.metric("1 KM BUFFER", "MET" if custom_result.buffer_met else "NOT MET")
        st.markdown(
            '<div class="smallprint">Changing these controls changes a transparent linear counterfactual, not a spacecraft plan.</div>',
            unsafe_allow_html=True,
        )

    with st.expander("Model assumptions and exclusions"):
        for assumption in ASSUMPTIONS:
            st.markdown(f"- {assumption}")
        st.markdown("- No atmospheric drag, J2 perturbation, space weather, thruster dynamics, attitude limits, communications delay or secondary-conjunction analysis.")

with tab_brief:
    st.markdown(
        """
<div class="defence-panel">
  <div class="kicker">Defence benefit · resilient space support to air and joint operations</div>
  <h3>Earlier warning preserves choices before a hazard becomes a crisis.</h3>
  <p>The RAF describes UK Space Command as a joint command based at RAF High Wycombe and says NSpOC combines civil and military space-domain awareness. Space systems underpin operations across air, land, sea and cyberspace. This prototype's bounded defence case is simple: earlier actionable warning can preserve lower-demand avoidance options, asset availability and command decision time.</p>
  <p><a href="https://www.raf.mod.uk/what-we-do/uk-space-command/" target="_blank">Official RAF source: UK Space Command ↗</a> · No RAF, MOD or UK Government endorsement is claimed.</p>
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown("## Evidence confidence ladder")
    confidence_rows = [
        {
            "Evidence layer": "Public GP/OMM catalogue",
            "Available here": "YES",
            "Supports": "Approximate recorded-time orbit context",
            "Does not support": "Operational miss distance or manoeuvre",
        },
        {
            "Evidence layer": "Public SOCRATES model rows",
            "Available here": "YES",
            "Supports": "Candidates for qualified further review",
            "Does not support": "UK operator alert, threat or safety declaration",
        },
        {
            "Evidence layer": "Precision ephemeris + covariance + geometry",
            "Available here": "NO",
            "Supports": "Would support operational risk assessment",
            "Does not support": "No substitute is inferred by this prototype",
        },
        {
            "Evidence layer": "Qualified operator decision + command authority",
            "Available here": "NO",
            "Supports": "Required before any operational action",
            "Does not support": "No autonomous command or recommendation",
        },
    ]
    st.dataframe(
        pd.DataFrame(confidence_rows),
        hide_index=True,
        width="stretch",
    )
    if public_result is not None:
        committee_snapshot = public_result.snapshot
        st.markdown(
            f"""
<div class="data-ribbon">
  <strong>PUBLIC CONTEXT RECORD</strong>
  <span class="data-pill">{len(committee_snapshot.objects)} OMM OBJECTS</span>
  <span class="data-pill">{len(committee_snapshot.events)} SOCRATES REVIEW CANDIDATES</span>
  <span class="data-pill">RECORDED {escape(format_public_utc(committee_snapshot.retrieved_at_utc))}</span>
  <span class="data-pill">SHA-256 {committee_snapshot.snapshot_sha256[:12]}…</span>
</div>
""",
            unsafe_allow_html=True,
        )
    st.caption(
        "The public evidence chain stops before operational assessment. The policy "
        "counterfactual below begins from an independent synthetic fixture."
    )

    render_synthetic_badge()
    st.markdown("## Synthetic committee headline")
    st.markdown(
        """
<div class="recommendation">
  <div class="big">SIX-HOUR WARNING REDUCES MANOEUVRE DEMAND EIGHTFOLD</div>
  <p>…versus acting at 45 minutes in this synthetic event. In the ideal linear illustration, required Δv scales inversely with lead time: 6 hours ÷ 45 minutes = 8. This is a constructed comparison, not measured operational performance. The investment question is whether tracking, data exchange and operator readiness turn warnings into usable decision time.</p>
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown("## Three questions Parliament can ask")
    questions = (
        "What proportion of priority UK space assets receive an actionable warning at least six hours before projected closest approach?",
        "How quickly is tracking information refreshed, shared with operators, acknowledged and updated as uncertainty changes?",
        "Are manoeuvre decisions and outcomes recorded consistently enough to test whether public investment improves resilience?",
    )
    question_cols = st.columns(3)
    for index, (column, question) in enumerate(zip(question_cols, questions), start=1):
        column.markdown(
            f'<div class="question-card"><div class="question-number">0{index}</div><p>{question}</p></div>',
            unsafe_allow_html=True,
        )
    st.caption("Proposed scrutiny metrics—not measured national performance statistics.")

    download_col, record_col, note_col = st.columns([1, 1, 1.7])
    with download_col:
        st.download_button(
            "↓  DOWNLOAD COMMITTEE BRIEF",
            data=brief,
            file_name="orbitguard_committee_brief.md",
            mime="text/markdown",
            width="stretch",
        )
    with record_col:
        st.download_button(
            "↓  DOWNLOAD EVIDENCE RECORD",
            data=json.dumps(record, indent=2) + "\n",
            file_name="orbitguard_reproducibility_record.json",
            mime="application/json",
            width="stretch",
        )
    with note_col:
        st.markdown(
            '<div class="smallprint">Both exports carry the synthetic flag, model version, seed, assumptions, human-approval gate and scenario SHA-256 fingerprint.</div>',
            unsafe_allow_html=True,
        )

    st.markdown("## Current public evidence")
    evidence_cols = st.columns(len(PUBLIC_EVIDENCE))
    for column, item in zip(evidence_cols, PUBLIC_EVIDENCE):
        column.markdown(
            f"""
<div class="source-card">
  <div class="source-title">{item.title}</div>
  <div class="source-value">{item.value}</div>
  <p>{item.detail}</p>
  <a href="{item.source_url}" target="_blank">{item.source_label} · {item.source_date} ↗</a>
</div>
""",
            unsafe_allow_html=True,
        )

    st.plotly_chart(monthly_evidence_figure(), width="stretch", config={"displayModeBar": False})
    st.markdown(
        f"Source: [NSpOC, *How we protected the UK and space in July 2026* — published 20 August 2026]({MONTHLY_COLLISION_RISKS_URL}). Dated public aggregate, not a live feed; NSpOC notes catalogue figures may be revised."
    )

    with st.expander("Read the full integrity boundary before reusing this prototype"):
        st.markdown(
            """
- No real asset, debris object, conjunction alert or service profile is used.
- No live NSpOC connection, restricted data, classified information or command link exists.
- The model uses constant relative velocity and an ideal instantaneous cross-track impulse.
- The 1 km buffer is illustrative and is not an NSpOC, CAA, RAF or operator threshold.
- The app calculates miss-distance counterfactuals, not collision probability.
- It does not model orbit perturbations, covariance, execution error or secondary conjunctions.
- Delta-v is a manoeuvre-resource proxy, not fuel percentage, cost or mission-life impact.
- A qualified operator must perform operational analysis and retain every manoeuvre decision.
- UK Orbit Guard is a hackathon prototype and is not endorsed by Parliament, RAF, MOD, NSpOC or UKSA.
"""
        )

st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    "**UK Orbit Guard** · From conjunction to committee · Built for defensive resilience, transparent scrutiny and human authority.",
)
st.markdown(
    '<div class="smallprint">Public GP catalogue visualisation plus a separately fingerprinted synthetic policy fixture. No restricted service, collision probability, autonomous command or operational recommendation.</div>',
    unsafe_allow_html=True,
)
