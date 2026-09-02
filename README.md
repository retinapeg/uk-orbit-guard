# UK Orbit Guard

> **Conjunction-to-Committee:** turn warning lead time into an auditable case for UK
> space resilience.

UK Orbit Guard is a striking, offline policy simulator built for a UK Parliament
hackathon. It demonstrates one bounded idea: in a synthetic conjunction, earlier
actionable warning preserves lower-demand avoidance options. It then turns that result
into concrete questions Parliament can use to scrutinise resilience investment.

**Synthetic · offline · not for flight operations.** The application has no live NSpOC
connection, no restricted or classified data, and no spacecraft-command capability. It
does not claim endorsement by Parliament, the RAF, MOD, NSpOC or UK Space Agency.

## The 60-second result

One deterministic, fictional encounter produces the same numbers every time:

| Option | Actionable lead time | Cross-track Δv | Projected miss | 1 km demo buffer |
|---|---:|---:|---:|---|
| Hold course | 6 h | 0.00 m/s | 120 m | Not met |
| Act now | 6 h | 0.05 m/s | 1.20 km | Met |
| Wait, same burn | 45 min | 0.05 m/s | 255 m | Not met |
| Wait, recover margin | 45 min | 0.40 m/s | 1.20 km | Met |

**Headline:** waiting until 45 minutes requires **8× the manoeuvre-budget demand**
to recover the same projected margin achieved by a 0.05 m/s action at six hours.

The ratio is intentionally constructed from the ideal linear model: required Δv scales
inversely with lead time, and 6 hours ÷ 45 minutes = 8. It is a synthetic teaching result,
not measured operational performance or a universal claim. The 1 km buffer is illustrative
and is not an NSpOC, CAA, RAF or operator threshold.

## Why the UK and RAF should care

The defensive benefit is resilience, not targeting. The RAF describes UK Space Command
as a joint command based at RAF High Wycombe, and says the National Space Operations
Centre combines civil and military space-domain awareness. Satellite services underpin
operations across air, land, sea and cyberspace. Earlier, usable warning can preserve
decision time and lower-demand options for protecting the space services on which both
public services and defence depend.

UK Orbit Guard does **not** replace NSpOC or issue a flight recommendation. It makes the
policy consequence of warning latency visible to Parliament while keeping qualified
operators in authority.

- [Royal Air Force: UK Space Command](https://www.raf.mod.uk/what-we-do/uk-space-command/)
- [UK Government: NSpOC public report for July 2026](https://www.gov.uk/government/news/how-we-protected-the-uk-and-space-in-july-2026)
- [UK Parliament: 2026 Space Resilience inquiry](https://committees.parliament.uk/committee/111/national-security-strategy-joint-committee/news/217022/security-in-space-committee-launches-new-inquiry-on-space-resilience/)

## Run the visual demo

Python 3.10 or newer is required; the frozen demo environment was tested on Python 3.11.5.
Prepare it once before the event using the exact demo lock:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-demo-lock.txt
```

Verify the complete deterministic path:

```bash
python -m pytest -q
python -m orbit_guard.demo --check
```

Launch the command-centre interface:

```bash
./scripts/run_demo.sh
```

Then open <http://localhost:8501>. The interface and fixture work without network
access after dependencies are installed.

## Judge-facing journey

1. **Alert** — establish the synthetic conjunction, protected service and six-hour window.
2. **Manoeuvre options** — compare act-now and delayed outcomes; reveal the 8× penalty.
3. **Committee brief** — show the civil–defence relevance, scrutiny questions, dated public
   evidence and downloadable audit record.

The exact three-minute script, Thursday freeze checklist and Friday recovery plan are in
[JUDGE_DEMO.md](JUDGE_DEMO.md).

## Architecture

```text
Synthetic JSON fixture
        |
        v
Pure local encounter model
(TCA, miss distance, Δv × lead time)
        |
        +---------------------+
        |                     |
        v                     v
CLI + JSON/Markdown      Streamlit + Plotly
fallback                 visual command view
        |                     |
        +----------+----------+
                   v
       Auditable committee questions
```

Key files:

- `app.py` — judge-facing visual interface.
- `scenarios/uk_eo_demo_1.json` — inspectable fictional fixture.
- `src/orbit_guard/conjunction.py` — pure deterministic calculation.
- `src/orbit_guard/demo.py` — CLI check plus JSON/Markdown fallback exports.
- `tests/` — exact headline-number and integrity tests.
- `artifacts/` — pre-generated record, committee brief and known-good Alert, Options
  and Committee visual fallbacks.

## Model boundary

The model uses constant relative velocity in a two-dimensional local encounter plane.
An ideal instantaneous cross-track impulse creates a terminal displacement of:

```text
cross-track displacement = Δv × actionable lead time
```

Excluded from the prototype:

- covariance and collision-probability calculation;
- operational orbit determination or SGP4/TLE conjunction prediction;
- atmospheric drag, J2 perturbation and space weather;
- thruster, attitude, communications and execution uncertainty;
- secondary-conjunction assessment;
- multi-asset scheduling and operator coordination;
- fuel, cost or mission-life estimates.

Public TLE data is deliberately not used to manufacture a “live collision” claim. Actual
conjunction assessment requires precise ephemerides, uncertainty/covariance, object geometry
and validated operational procedures.

## Public evidence, not a live feed

The app embeds a dated, attributed public snapshot:

- NSpOC reported **1,209 collision risks** to UK-licensed satellites for July 2026.
- UKSA reported an average of **1,913 collision warnings per month** during 2025–26.
- The Joint Committee on the National Security Strategy opened a **Space Resilience inquiry**
  in July 2026.

Monitor Space Hazards operational conjunction services and its API are restricted to eligible
UK-licensed operators and government users. This prototype makes no claim to access them.

## Inherited research scaffold

The original `sat_avoid` N-body/Gym/PPO code remains as an **experimental, non-demo research
scaffold** so the upstream history is preserved. It is not used in the Friday critical path:

```bash
python -m pip install -e ".[rl]"
python -m sat_avoid.train --timesteps 1000
```

Its rotating gravitating bodies are a toy environment, not a validated debris-conjunction
model. Do not train PPO or rely on Daytona during the live demonstration.

## Project status

The new work lives on `codex/uk-orbit-guard-demo`. The original repository is retained as the
`upstream` remote; no new public repository or deployment is implied by this local build.
