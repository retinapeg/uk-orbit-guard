"""Generate the deterministic OrbitGuard UK demo record and committee brief."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from .conjunction import (
    MODEL_VERSION,
    ConjunctionScenario,
    OptionResult,
    assess_option,
    choose_recommendation,
    result_by_id,
)
from .scenario_io import load_scenario, scenario_sha256

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO_PATH = PROJECT_ROOT / "scenarios" / "uk_eo_demo_1.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "artifacts"

ASSUMPTIONS = (
    "All asset, debris, alert and service identifiers are fictional.",
    "Constant relative velocity in a two-dimensional local encounter plane.",
    "Instantaneous ideal cross-track impulse with no execution uncertainty.",
    "The 1 km separation buffer is illustrative, not an NSpOC or operator threshold.",
    "No covariance or collision-probability calculation is performed.",
    "No post-manoeuvre secondary-conjunction screening is performed.",
    "Delta-v is a manoeuvre-resource proxy, not a fuel, cost or mission-life estimate.",
)


def assess_scenario(scenario: ConjunctionScenario) -> list[OptionResult]:
    return [assess_option(scenario, option) for option in scenario.options]


def build_record(
    scenario: ConjunctionScenario,
    results: Iterable[OptionResult],
    *,
    scenario_file_sha256: str,
) -> dict[str, object]:
    results = list(results)
    recommendation = choose_recommendation(results)
    act_now = result_by_id(results, "act_now")
    delayed = result_by_id(results, "wait_recover_margin")
    delay_penalty = (
        delayed.option.cross_track_delta_v_mps
        / act_now.option.cross_track_delta_v_mps
    )

    return {
        "prototype": "UK Orbit Guard — Conjunction-to-Committee",
        "scenario_id": scenario.scenario_id,
        "synthetic": scenario.synthetic,
        "operational_use": False,
        "model": MODEL_VERSION,
        "seed": scenario.seed,
        "scenario_file_sha256": scenario_file_sha256,
        "protected_asset": scenario.protected_asset,
        "protected_service": scenario.protected_service,
        "secondary_object": scenario.secondary_object,
        "orbit_context": scenario.orbit_context,
        "tca_seconds": scenario.time_to_closest_approach_s,
        "baseline_miss_m": scenario.baseline_miss_m,
        "illustrative_buffer_m": scenario.illustrative_buffer_m,
        "recommended_option_id": recommendation.option.option_id,
        "recommended_option": recommendation.option.label,
        "recommended_delta_v_mps": recommendation.option.cross_track_delta_v_mps,
        "recommended_miss_m": recommendation.projected_miss_m,
        "delayed_delta_v_mps": delayed.option.cross_track_delta_v_mps,
        "delayed_miss_m": delayed.projected_miss_m,
        "delay_penalty": delay_penalty,
        "human_operator_approval_required": True,
        "options": [
            {
                "option_id": result.option.option_id,
                "label": result.option.label,
                "lead_time_s": result.option.lead_time_s,
                "cross_track_delta_v_mps": result.option.cross_track_delta_v_mps,
                "projected_miss_m": result.projected_miss_m,
                "illustrative_buffer_met": result.buffer_met,
                "description": result.option.description,
            }
            for result in results
        ],
        "assumptions": list(ASSUMPTIONS),
    }


def build_committee_brief(record: dict[str, object]) -> str:
    return f"""# UK Orbit Guard — synthetic committee brief

> **SYNTHETIC · OFFLINE · POLICY SIMULATOR · NOT FOR FLIGHT OPERATIONS**

Scenario `{record['scenario_id']}` uses model `{record['model']}` and seed
`{record['seed']}`. The protected asset and debris object are fictional.

## Headline finding

In this synthetic event, acting with six hours of warning reaches approximately
**{record['recommended_miss_m'] / 1000:.2f} km** projected separation using a
**{record['recommended_delta_v_mps']:.2f} m/s** cross-track manoeuvre. Waiting until
45 minutes before closest approach requires **{record['delayed_delta_v_mps']:.2f} m/s**
to recover the same margin: **{record['delay_penalty']:.1f}× the manoeuvre-budget demand**.

In this ideal linear illustration, required delta-v scales inversely with lead time:
six hours divided by 45 minutes equals eight. The ratio is a constructed model
comparison, not measured operational performance.

This is a transparent policy counterfactual, not a flight command or safety guarantee.

## Why Parliament should care

- **Operational consequence:** delayed warning reduces the usefulness of small corrective manoeuvres.
- **Public-service dependency:** Earth-observation services can support environmental monitoring and emergency response.
- **Policy implication:** tracking coverage, warning latency, data exchange and auditable operator response are resilience investments.

Parliament should scrutinise capability and outcomes; qualified operators and NSpOC remain
responsible for operational assessment and any spacecraft manoeuvre.

## Three scrutiny questions

1. What proportion of priority UK space assets receive an actionable warning at least six hours before projected closest approach?
2. How quickly is tracking information refreshed, shared with operators, acknowledged and updated as uncertainty changes?
3. Are manoeuvre decisions and outcomes recorded consistently enough to evaluate whether public investment improves resilience?

These are proposed scrutiny metrics, not measured national performance statistics.

## Public evidence snapshot

- NSpOC reported 1,209 collision risks to UK-licensed satellites in July 2026.
  Source: [NSpOC, published 20 August 2026](https://www.gov.uk/government/news/how-we-protected-the-uk-and-space-in-july-2026)
- NSpOC issued an average of 1,913 collision warnings per month in 2025–26.
  Source: [UK Space Agency Annual Report 2025–26, published 14 July 2026](https://www.gov.uk/government/publications/uk-space-agency-annual-report-and-accounts-2025-2026/uk-space-agency-annual-report-2025-2026)
- Parliament's Joint Committee on the National Security Strategy opened a space-resilience inquiry on 16 July 2026.
  Source: [UK Parliament](https://committees.parliament.uk/committee/111/national-security-strategy-joint-committee/news/217022/security-in-space-committee-launches-new-inquiry-on-space-resilience/)

## Model boundary

{chr(10).join(f'- {item}' for item in record['assumptions'])}

Reproducibility fingerprint: `{record['scenario_file_sha256']}`
"""


def validate_demo(record: dict[str, object]) -> None:
    if record["synthetic"] is not True or record["operational_use"] is not False:
        raise ValueError("demo classification guard failed")
    if record["baseline_miss_m"] >= record["illustrative_buffer_m"]:  # type: ignore[operator]
        raise ValueError("fixture must begin below the illustrative buffer")
    if record["recommended_miss_m"] < record["illustrative_buffer_m"]:  # type: ignore[operator]
        raise ValueError("recommended option must meet the illustrative buffer")
    if abs(float(record["delay_penalty"]) - 8.0) > 1e-9:
        raise ValueError("judge fixture must retain the 8x delay result")
    if record["human_operator_approval_required"] is not True:
        raise ValueError("human approval gate must remain explicit")


def write_outputs(
    output_dir: Path,
    record: dict[str, object],
    brief: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "demo_result.json"
    brief_path = output_dir / "committee_brief.md"
    json_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    brief_path.write_text(brief, encoding="utf-8")
    return json_path, brief_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--check", action="store_true", help="Fail if demo invariants drift.")
    parser.add_argument("--json", action="store_true", help="Print the record to stdout.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    scenario = load_scenario(args.scenario)
    results = assess_scenario(scenario)
    record = build_record(
        scenario,
        results,
        scenario_file_sha256=scenario_sha256(args.scenario),
    )
    if args.check:
        validate_demo(record)
    brief = build_committee_brief(record)
    json_path, brief_path = write_outputs(args.out_dir, record, brief)

    if args.json:
        print(json.dumps(record, indent=2))
    else:
        print("ORBITGUARD UK — SYNTHETIC / NOT FOR FLIGHT OPERATIONS")
        print(
            f"{record['scenario_id']}: {record['baseline_miss_m']:.0f} m baseline → "
            f"{record['recommended_miss_m']:.0f} m with {record['recommended_delta_v_mps']:.2f} m/s"
        )
        print(
            f"Delay to 45 minutes: {record['delay_penalty']:.1f}× manoeuvre-budget demand"
        )
        print("Decision gate: qualified operator approval required")
        print(f"Wrote {json_path}")
        print(f"Wrote {brief_path}")
        if args.check:
            print("DEMO CHECK: PASS")


if __name__ == "__main__":
    main()
