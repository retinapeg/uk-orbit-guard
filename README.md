# UK Orbit Guard

> **Conjunction-to-Committee:** make public orbital context legible, show why
> warning lead time matters, and give Parliament an auditable resilience question.

UK Orbit Guard is a visual UK Parliament hackathon prototype with two deliberately
separate layers:

1. a **public-orbit picture** combining a dated CelesTrak public GP-element snapshot,
   approximately propagated with SGP4 for the globe, with dated CelesTrak SOCRATES Plus
   public conjunction-candidate records for the radial screen; and
2. a **deterministic synthetic policy lab** showing how earlier actionable warning can
   preserve lower-demand manoeuvre options.

The public layer never becomes the synthetic encounter. It does not identify a live
collision, calculate collision probability, recommend a manoeuvre or command a
spacecraft. The global interface boundary is explicit:

> **PUBLIC-DATA PROTOTYPE · NO RESTRICTED FEEDS · NO COMMAND · NOT FOR FLIGHT OPERATIONS**

No endorsement, ownership or operational use by Parliament, the RAF, MOD, the National
Space Operations Centre (NSpOC), the UK Space Agency (UKSA), the Civil Aviation
Authority (CAA), CelesTrak or any satellite operator is claimed.

## The stage story in 60 seconds

Start with a dated, inspectable public picture. The civil example is **UK-DMC-2**:
the CAA's March 2026 UK Registry records designation `2009-041C`, catalogue number
`35683` and the function “Disaster Monitoring”; CelesTrak publishes a corresponding
public GP record named `UK-DMC 2`. This is a regulatory and catalogue link only—not a
claim about current mission status, protection priority, military ownership or RAF use.

Then cross the visible boundary into the fictional encounter. One deterministic fixture
produces the same numbers every time:

| Synthetic option | Actionable lead time | Cross-track Δv | Projected miss | 1 km demo buffer |
|---|---:|---:|---:|---|
| Hold course | 6 h | 0.00 m/s | 120 m | Not met |
| Act now | 6 h | 0.05 m/s | 1.20 km | Met |
| Wait, same burn | 45 min | 0.05 m/s | 255 m | Not met |
| Wait, recover margin | 45 min | 0.40 m/s | 1.20 km | Met |

**Headline:** waiting until 45 minutes requires **8× the manoeuvre-budget demand**
to recover the same projected margin achieved by a 0.05 m/s action at six hours.

That ratio is deliberately constructed from the ideal linear teaching model: required
Δv scales inversely with lead time, and `6 hours ÷ 45 minutes = 8`. It is not measured
operational performance, a universal law of avoidance manoeuvres or a claimed benefit
delivered by the public screen. The 1 km buffer is illustrative—not an NSpOC, CAA, RAF,
CelesTrak or operator threshold.

## What the audience sees

The interface has four numbered tabs so the presenter can keep provenance visible:

| Tab | Visual | Honest interpretation |
|---|---|---|
| **00 PUBLIC ORBIT PICTURE** | **Catalogue** mode places the declared public subset around a 3D Earth. Display types inferred from public names use diamonds for payloads, squares for rocket bodies, crosses for debris and open circles for unknowns. Trails appear only for selected/review roles. | Earth-centred positions propagated approximately from public elements; display type is not an authoritative source classification, and this is not a complete catalogue, sensor picture or conjunction alert. |
| **00 PUBLIC ORBIT PICTURE** | **Proximity screen** mode uses radius for SOCRATES's source-modelled minimum range and clockwise angle for its reported TCA relative to the stored SOCRATES data-as-of time. The display uses a logarithmic radial transform but labels physical km/m values. | Parsed, dated public candidates ranked for further review. Shape is a display class inferred from the public name. Outside-horizon rows are separate from invalid rows. No local detector, covariance calculation, probability conclusion or safety decision. |
| **01 SYNTHETIC ALERT** | A fictional Earth-observation service and fictional secondary object establish a 120 m miss counterfactual at six hours. | Synthetic fixture, separate from every public object. |
| **02 MANOEUVRE OPTIONS** | Four fixed options, a lead-time curve and an optional transparent explorer reveal the constructed 8× comparison. | Policy teaching model—not an orbit plan, fuel estimate or flight recommendation. |
| **03 COMMITTEE BRIEF** | An evidence confidence ladder stops public context before the `SYNTHETIC OFFLINE FIXTURE` badge and `Synthetic committee headline`; dated aggregates, scrutiny questions and downloads follow. | Shows what evidence is present, what is absent and exactly where the constructed policy result begins; not measured national performance. |

The public visuals carry their own method boundaries:

- `PUBLIC ORBIT PICTURE / RECORDED SNAPSHOT`
- `CELESTRAK GP/OMM · SGP4/TEME DISPLAY REPLAY`
- `PUBLIC-ELEMENT CONTEXT · APPROXIMATE PROPAGATION · NO RESTRICTED DATA`
- `PUBLIC-ELEMENT PROXIMITY SCREEN / 7-DAY WINDOW`
- `CELESTRAK SOCRATES · PUBLIC GP MODEL`
- `CANDIDATES FOR FURTHER REVIEW · NO COVARIANCE · NOT A FLIGHT DECISION`
- `PUBLIC SCREEN ENDS HERE`

[CelesTrak SOCRATES Plus](https://celestrak.org/SOCRATES/) is the source of the dated
public candidate records in the radial display. UK Orbit Guard parses and visualises its
reported object identities, minimum range, TCA and relative speed; it does not perform a
second catalogue-wide pairwise detector. SOCRATES's probability field and 5 km setting
remain source-model context—not a locally calculated conclusion, imported operational
threshold or validation of this prototype.

## Public data, cache and offline replay

The default Friday path is **offline and cache-first**: it uses a verified local cache
when one exists, otherwise the committed dated replay. Startup makes **zero network
calls** in either case, and the visible provenance ribbon identifies which record won.
The public tab exposes a manual **↻ REFRESH PUBLIC DATA IF DUE** action for rehearsal or
development. It respects a two-hour time-to-live because CelesTrak states that it checks
for new GP data once every two hours. The control reuses a verified cache while it is
within that TTL; it is not a force-refresh control. More frequent source requests do not
improve freshness and can trigger source limits.

The globe is deliberately bounded to UK-DMC 2 (`35683`), ISS (`25544`), PHISAT 2
(`60470`) and AC1-002 (`66745`). The radial screen is a separate bounded SOCRATES
OneWeb query (`NAME=oneweb,&ORDER=TCA&MAX=5`); it is not a locally computed screen of
UK-DMC-2 against those four globe objects. The committed replay is
`data/public_orbit_snapshot_2026-09-03.json`; a verified rehearsal refresh may use the
uncommitted runtime cache `.cache/public_orbit_snapshot.json`.

Read the visible ribbon/inspector together with **DOWNLOAD PUBLIC SNAPSHOT RECORD**;
the download carries fields that are deliberately too detailed for the stage surface:

- source and exact CelesTrak URLs, integrity-bound with the retrieval metadata;
- retrieval time in UTC and GP element epoch;
- cache/replay state and the two-hour TTL status captured when the record was loaded;
- the four-object globe set and bounded SOCRATES query;
- globe propagation method and coordinate frame, plus the SOCRATES data-current
  timestamp and the display horizon;
- rejected/invalid, outside-horizon and displayed candidate counts; and
- `operational_collision_assessment: false`, with no local collision probability or
  manoeuvre recommendation.

If refresh is unavailable, malformed or rate-limited, the app keeps the last verified
cache or the committed historical replay and labels the degraded state. It does not
silently substitute stale elements into a “current” screen. See
[DATA_AND_LIMITATIONS.md](DATA_AND_LIMITATIONS.md) for the complete data contract.

## Why Parliament, defence and industry should care

[NSpOC describes itself](https://www.gov.uk/government/organisations/national-space-operations-centre/about)
as jointly led by UKSA and UK Space Command, combining civil and military space-domain
awareness capabilities. The bounded defence case here is service resilience, not
targeting: earlier usable warning can preserve decision time and lower-demand options
for qualified operators protecting space-enabled services on which public services,
industry and defence depend.

UK Orbit Guard does not replace NSpOC or an operator's flight-dynamics process. It makes
three investment questions easy to see:

1. Is the observation and catalogue coverage good enough to create actionable warning?
2. Does trusted information reach the responsible operator with useful lead time?
3. Are decisions and outcomes recorded well enough for Parliament to scrutinise whether
   resilience investment works?

## Run the demo

Python 3.10 or newer is required; the frozen demo environment was tested on Python
3.11.5. Prepare it before the event using the exact lock:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-demo-lock.txt
```

Verify the deterministic critical path:

```bash
python -m pytest -q
python -m orbit_guard.demo --check
```

Launch the command-centre interface:

```bash
./scripts/run_demo.sh
```

Open <http://127.0.0.1:8501>. The launcher refuses to attach to an occupied port because
it cannot prove which app owns it. If port 8501 is genuinely unavailable, start a fresh
verified instance with:

```bash
ORBITGUARD_PORT=8502 ./scripts/run_demo.sh
```

Then open <http://127.0.0.1:8502>.

Use [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for the exact three-minute narration and safe
question branches. Use [RUNBOOK.md](RUNBOOK.md) for the Thursday freeze, Friday
preflight, offline fallback and recovery order.

## Architecture

```text
PUBLIC CONTEXT                                      SYNTHETIC POLICY LAB

CAA public register                                  Versioned JSON fixture
        |                                                      |
        v                                                      v
CAA-linked example ----> CelesTrak public sources     Pure local encounter model
                              |                        (Δv × actionable lead time)
                 +------------+-------------+                    |
                 |                          |                   +--------+
                 v                          v                   |        |
          GP/OMM object set          SOCRATES Plus              v        v
                 |                  candidate records     CLI record   Streamlit
                 +------------+-------------+              fallback    visuals
                              v
                     Two-hour cache /
                     historical replay
                 +------------+-------------+
                 |                          |
                 v                          v
          SGP4/TEME globe          radial candidate screen
                                   (not a flight decision)

                              +-------------+-------------+
                                            v
                                auditable scrutiny questions
```

The public and synthetic paths meet only at the policy narrative. No public candidate is
fed into the manoeuvre model.

Key files:

- `app.py` — four-tab Parliament presentation surface.
- `scenarios/uk_eo_demo_1.json` — inspectable fictional scenario.
- `src/orbit_guard/conjunction.py` — deterministic teaching calculation.
- `src/orbit_guard/public_data.py` — bounded public-source parsing, provenance,
  two-hour cache/fallback and SGP4 state propagation.
- `src/orbit_guard/public_visuals.py` — feed-agnostic public catalogue and proximity figures.
- `data/public_orbit_snapshot_2026-09-03.json` — committed public historical replay.
- `src/orbit_guard/demo.py` — CLI check plus JSON/Markdown synthetic fallbacks.
- `tests/` — deterministic headline, schema, integrity and visual-contract checks.
- `artifacts/` — pre-generated synthetic record and committee brief, three dated
  public-context captures with visible provenance, and three known-good synthetic
  presentation images.

## Hard stop before any operational decision

A public-element proximity candidate is the end of this prototype's authority. It must
not be turned into “safe”, “collision”, “threat” or “manoeuvre” language. An operational
process would need current validated observations or ephemerides, covariance/uncertainty,
object size and geometry, a properly computed time of closest approach and collision
probability, execution constraints, secondary-conjunction analysis, coordination with the
other operator, and a decision by the authorised spacecraft operator using appropriate
NSpOC/Monitor Space Hazards or equivalent services.

## Authoritative public sources

- [CAA: licences granted and registers of space objects](https://www.caa.co.uk/space/about-the-space-team/licences-granted-and-registers-of-space-objects/)
- [CAA CAP 2207: UK Registry of Outer Space Objects](https://www.caa.co.uk/data-and-publications/publications/documents/content/cap2207/)
- [CelesTrak GP data formats and query documentation](https://celestrak.org/NORAD/documentation/gp-data-formats.php)
- [CelesTrak public GP record for catalogue number 35683](https://celestrak.org/NORAD/elements/gp.php?CATNR=35683&FORMAT=JSON-PRETTY)
- [CelesTrak SOCRATES Plus methodology and results](https://celestrak.org/SOCRATES/)
- [Python SGP4 implementation and accuracy notes](https://github.com/brandon-rhodes/python-sgp4/blob/master/README.rst)
- [NSpOC: role and mission sets](https://www.gov.uk/government/organisations/national-space-operations-centre/about)
- [RAF: UK Space Command](https://www.raf.mod.uk/what-we-do/uk-space-command/)
- [UK Parliament: Space Resilience inquiry](https://committees.parliament.uk/committee/111/national-security-strategy-joint-committee/news/217022/security-in-space-committee-launches-new-inquiry-on-space-resilience/)

## Inherited research scaffold

The original `sat_avoid` N-body/Gym/PPO code remains an **experimental, non-demo
research scaffold** so upstream history is preserved. It is not in the Friday critical
path:

```bash
python -m pip install -e ".[rl]"
python -m sat_avoid.train --timesteps 1000
```

Its rotating gravitating bodies are a toy environment, not a validated debris-conjunction
model. Do not train PPO, call Daytona or depend on Rote during the live demonstration.

The new work is on `codex/uk-orbit-guard-demo`. The original repository is retained as
the `upstream` remote; this local build does not imply publication or deployment.
