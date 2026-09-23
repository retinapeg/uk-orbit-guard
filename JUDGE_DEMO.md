# UK Orbit Guard — judge demo card

## Start

```bash
cd uk-orbit-guard
source .venv/bin/activate
python -m pytest -q
python -m orbit_guard.demo --check
./scripts/run_demo.sh
```

Open <http://127.0.0.1:8501>. If the verified port is occupied:

```bash
ORBITGUARD_PORT=8502 ./scripts/run_demo.sh
```

For the live branch, install the separate host SDK once before the event:

```bash
python -m pip install -r requirements-live.txt
```

Set the credential in the same zsh process before launching, with hidden input:

```zsh
read -s "DAYTONA_API_KEY?Paste Daytona API key (input hidden): "
export DAYTONA_API_KEY
printf '\n'
test -n "${DAYTONA_API_KEY:-}" && echo "DAYTONA_API_KEY is set"
```

Never print or store the value. Rote is not a runtime dependency.

## Read the evidence state first

| Ribbon | Say this |
|---|---|
| `VERIFIED DAYTONA RESULT` | “Validated result from this app session; sandbox deletion confirmed.” |
| `RECORDED DAYTONA REPLAY` | “Host-validated prior replay—not current live compute.” |
| `LOCAL GEN 0 PREVIEW` | “Local untrained synthetic baseline; no Daytona result substituted.” |
| `DAYTONA READY` | “Ready to request a sandbox; no run has occurred yet.” |
| `LIVE DAYTONA COMPUTE` | “The run is in the visible phase; completion is not yet claimed.” |
| `DAYTONA FAILED` | “The remote run failed; no local training result was substituted.” |

Files and tests alone never prove a live Daytona run.

## Three-minute route

1. **00 SPACE COMMAND** — “The committed public replay contains 2,661 unique
   CelesTrak GP/OMM records: 1,963 returned by the FENGYUN-1C-DEBRIS query, 111
   by IRIDIUM-33-DEBRIS and 587 by COSMOS-2251-DEBRIS. Each group includes its
   named parent object as well as debris. They are public mean-element context,
   not telemetry, a complete catalogue or conjunction threats.”
2. Point to `GUARD-1` and `H-01` — “This local encounter is synthetic and
   separate. No public object is training input.”
3. Point to the contract — “CEM policy search: Gen 0→10, 24 candidates, three
   perturbed episodes each, 720 remote search episodes, seed 42.”
4. Use the ribbon branch. If Gen 1–10 are unlocked, scrub **0 → intermediate →
   10**. For a verified current-session result, show the passport fields
   `sandbox_deleted: true` and `local_training_fallback_used: false`.
5. **01 PUBLIC ORBIT PICTURE** — show UK-DMC-2 / `2009-041C` / `35683`, then the
   separate bounded SOCRATES screen. Say “candidate for further review; no local
   covariance or collision probability.”
6. **02 SYNTHETIC ALERT** — cross the synthetic badge. This fictional fixture is
   separate from both the public data and the RL reward.
7. **03 MANOEUVRE OPTIONS** — “Six hours and 0.05 m/s gives the same illustrative
   1.2 km projected margin as 45 minutes and 0.40 m/s. That is a constructed 8×
   demand comparison, not measured performance.”
8. **04 COMMITTEE BRIEF** — close on warning coverage, delivery lead time,
   operator readiness, auditability and human authority.

## Optional live run

Only if `DAYTONA READY` is visible and time permits:

1. keep the default single `H-01` scenario;
2. press **TRAIN GEN 0 → 10 ON DAYTONA** once;
3. name only the visible phase;
4. continue tabs 01–04 while it runs; and
5. return once. Use the result only after `VERIFIED DAYTONA RESULT` and confirmed
   cleanup appear.

If it does not finish, leave it labelled in progress. If it fails, load a prior
verified replay only if one already exists; otherwise remain at Gen 0.

## Numbers that must not drift

| Evidence | Value | Boundary |
|---|---:|---|
| Committed command catalogue | 2,661 unique records | Dated public subset from 3 debris-event groups |
| RL search | 10 × 24 × 3 = 720 episodes | Synthetic remote training, plus validations |
| RL model | `hill-cem-v1` | Planar Hill/LVLH teaching model |
| RL actions | 5 | Coast, radial out/in, prograde/retrograde |
| RL horizon | 72 × 20 s = 24 min | Synthetic only |
| RL keep-out radius | 0.35 km | Illustrative only |
| Fixed policy fixture | 6 h vs 45 min = 8× | Separate ideal linear counterfactual |

The 2,661 count applies to the committed debris fixture only; a later validated
refresh may have a different count. Do not merge it with the four-object public
audit set or bounded SOCRATES rows.

## Hard-stop line

> “This prototype's authority stops at candidate for further review. Current
> validated observations, covariance, object geometry, collision probability,
> secondary screening, coordination and the authorised human operator are
> required before any real decision.”

## Recovery

- Daytona absent/failed: Gen 0 or explicitly recorded prior replay; never a
  disguised local trained result.
- Public refresh failed: keep the labelled cache/replay or skip it; never retry
  repeatedly at the venue.
- UI failed: `python -m orbit_guard.demo --check`, then
  `artifacts/demo_result.json` and `artifacts/committee_brief.md` for the separate
  deterministic 8× story.
- Port occupied: use the verified alternate port; do not kill an unknown
  process.

## Never claim

- 2,661 collision threats or a complete/current sensor picture;
- public catalogue objects were screened into the RL job;
- reward or clearance is collision probability or safety assurance;
- a manoeuvre recommendation, command, interception or hostile attribution;
- a recorded replay is current live compute;
- a sandbox succeeded before validation and confirmed deletion; or
- Parliament, NSpOC, UKSA, CAA, RAF, MOD, CelesTrak, Daytona or an operator
  endorses or operates the prototype.
