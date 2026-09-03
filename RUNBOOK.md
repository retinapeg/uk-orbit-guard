# UK Orbit Guard — Friday runbook

## Mission for the room

Show one defensible pipeline:

> A dated public debris field establishes scale. A separately declared
> synthetic encounter is frozen and trained in one private Daytona sandbox.
> The host accepts the result only after identity, scenario, runtime,
> checkpoint, replay and cleanup checks. Parliament sees the evidence boundary
> and the questions that remain for an authorised operator.

The remote policy run and the fixed 8× lead-time counterfactual are two separate
synthetic demonstrations. Neither is a claim about a real public object. The
2,661-object CelesTrak fixture is context only and is never training input.

## Evidence states: choose before presenting

| Branch | Required visible state | What may be said |
|---|---|---|
| **L — verified current-session result** | `VERIFIED DAYTONA RESULT`, matching scenario, Gen 0→10 unlocked and run passport present | “This result was returned and validated in this app session; the sandbox was deleted.” |
| **R — recorded prior result** | `RECORDED DAYTONA REPLAY` after pressing **LOAD LAST VERIFIED REPLAY** | “This is a host-validated prior Daytona run, replayed locally—not current live compute.” |
| **G — Gen 0 only** | `LOCAL GEN 0 PREVIEW`, missing readiness, failed run or no recorded replay | “This is the local untrained synthetic baseline. No remote training result is being substituted.” |

`DAYTONA READY` proves only that the SDK imports and a credential is present. An
active phase proves work is in progress, not success. Repository files, tests,
screenshots and this document are not evidence that a live run occurred.

## Thursday freeze

Run from the exact project root:

```bash
cd "/Users/leonardaarons-ditson/Documents/ChatGPT/parliament hackathon/uk-orbit-guard"
git status --short --branch
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-demo-lock.txt
python -m pip install -r requirements-live.txt
python -m compileall -q app.py src scripts
python -m pytest -q
python -m orbit_guard.demo --check
git diff --exit-code -- artifacts/demo_result.json artifacts/committee_brief.md
```

The base lock was prepared on Python 3.11.5. `requirements-live.txt` separately
pins the host Daytona SDK. Do not upgrade packages or regenerate a lock at the
venue. Rote is not part of the runtime and does not need installing.

### Set `DAYTONA_API_KEY` without exposing it

Obtain the key through the user's normal Daytona account process. In the same
zsh session that will launch Streamlit, use hidden input:

```zsh
read -s "DAYTONA_API_KEY?Paste Daytona API key (input hidden): "
export DAYTONA_API_KEY
printf '\n'
test -n "${DAYTONA_API_KEY:-}" && echo "DAYTONA_API_KEY is set"
```

Never print, hash, paste into a command argument, commit, screenshot or save the
value in this repository. The app displays presence only. Leave
`DAYTONA_API_URL` unset unless the user's Daytona configuration explicitly
requires an endpoint override.

Start the app from that shell:

```bash
./scripts/run_demo.sh
```

Open <http://127.0.0.1:8501>. The **00 SPACE COMMAND** ribbon must say
`DAYTONA READY`; if it says `LOCAL GEN 0 PREVIEW`, stop and fix SDK/key visibility
before attempting a live rehearsal. Restart Streamlit after changing an
environment variable.

### Live Daytona rehearsal

Use the default single `H-01` head-on synthetic template so the scenario hash
will match the fallback rehearsal:

1. Read the command ribbon and the 12-character scenario-hash prefix aloud.
2. Confirm the model card says `hill-cem-v1`, 10 generations, 24 candidates,
   3 perturbed episodes each, 720 remote search episodes and seed 42.
3. Press **TRAIN GEN 0 → 10 ON DAYTONA** exactly once.
4. Watch the state ledger. The successful contract advances through
   `QUEUED`, `CREATING`, `LIVE`, `TRAINING`, `VALIDATING`,
   `RESULT_COLLECTED`, `CLEANED`, then `COMPLETE`. A fast run can make some
   states brief.
5. Do not say “completed” until the ribbon says `VERIFIED DAYTONA RESULT` and
   the generation rail unlocks.
6. Scrub generation 0, an intermediate generation and generation 10. Confirm
   the animated replay and training curve render.
7. Open **Verified Daytona run passport**. Confirm it shows a sandbox ID,
   invocation ID, scenario and runtime-bundle hashes, different initial and
   trained checkpoint hashes, `training_episodes: 720`,
   `local_training_fallback_used: false`, and `sandbox_deleted: true`.
8. Treat any missing or contradictory field as a failed proof, even if a curve
   is visible.
9. Confirm the recorded envelope now exists without printing it:

   ```bash
   test -s .cache/daytona_rl/last_verified.json && echo "recorded replay present"
   ```

10. Restart the app, press **LOAD LAST VERIFIED REPLAY**, and confirm the ribbon
    says `RECORDED DAYTONA REPLAY` with the detail “validated prior run · not
    current live compute”.

The controller creates one private, ephemeral, network-blocked sandbox with a
12-minute TTL. Its create timeout is two minutes, worker timeout five minutes,
and delete timeout two minutes. Venue latency can therefore exceed the speaking
slot. Rehearse on the actual network; do not promise an exact completion time.

If the run fails, the UI must say `DAYTONA FAILED — no local result was
substituted`. If deletion is not confirmed, the collected output is rejected.
Use the Daytona account/dashboard to inspect or clean up any uncertain sandbox;
do not call the run verified.

The single-run lock at `.cache/daytona_rl/active.json` protects fresh and
partially written launch state from a second controller. A lock older than 20
minutes is reclaimed automatically only when no live controller PID can be
validated. If a lock still blocks rehearsal, inspect `active.json`, the named
run directory, `controller_pid.json`, `live_state.json` and the Daytona
dashboard. Only after confirming that no controller or sandbox remains should
an operator move the lock aside for diagnosis; never delete an unexplained
fresh lock on stage.

### Public-data rehearsal

There are two independent public-data loaders.

#### Command-centre debris field

The committed file `data/debris_catalogue_snapshot_2026-09-03.json` contains
2,661 de-duplicated public OMM records from:

- FENGYUN-1C-DEBRIS: 1,963;
- IRIDIUM-33-DEBRIS: 111; and
- COSMOS-2251-DEBRIS: 587.

Startup makes no network request. It uses a validated cache and labels it
fresh or stale against the 12-hour retrieval TTL; when no valid cache exists,
it uses the bundled replay. Check the exact globe source label:

- `CURRENT-SESSION CELESTRAK GP FETCH` — a validated network response was used;
- `CACHED CELESTRAK GP SNAPSHOT` — a validated cache was used; or
- `STALE CACHED CELESTRAK GP SNAPSHOT` — a validated cache exists but is beyond
  the 12-hour retrieval window; or
- `BUNDLED CELESTRAK GP REPLAY` — the committed historical source record was
  used.

The default globe position track re-evaluates the loaded mean elements every
five seconds and says `5 s DATED-ELEMENT DISPLAY PROPAGATION`. **PAUSE TRACK** freezes
that visual clock; **RESUME TRACK** restarts it. `DISPLAYED` is the SGP4
evaluation time, not proof that the underlying public elements are current.
The source records have mixed epochs. Do not call the animation live telemetry,
a complete catalogue or a conjunction screen.

Use **REFRESH IF DUE** only during connected rehearsal and only when a refresh
is genuinely needed. It requests the three allowlisted groups with a 15-second
timeout each (45 seconds maximum serial request wait). Never repeatedly retry a
403, 404, malformed response or venue failure. Keep the last validated record
on screen.

#### Four-object public audit view

On **01 PUBLIC ORBIT PICTURE**:

1. Read the source, retrieval UTC, content-hash prefix and cache/replay state.
2. In **Catalogue**, confirm UK-DMC-2 is joined by international designation
   `2009-041C` and catalogue number `35683`. It is a CAA-linked civil public
   example, not a current-status or ownership claim.
3. Confirm the inspector reports `SGP4/TEME at snapshot retrieval time`. If it
   reports a fallback model, call the view degraded or skip it.
4. In **Proximity screen**, read the separate SOCRATES source-as-of timestamp and
   the labels `PUBLIC-ELEMENT PROXIMITY SCREEN / 7-DAY WINDOW` and
   `CANDIDATES FOR FURTHER REVIEW · NO COVARIANCE · NOT A FLIGHT DECISION`.
5. Confirm the radial zero point says `SOURCE AS-OF`, not “now”.
6. Use **REFRESH PUBLIC DATA IF DUE** only during rehearsal. Its cache TTL and
   session cooldown are two hours. If CelesTrak returns 403/404, stop; do not
   retry.
7. Download the public snapshot record and confirm its source URLs, retrieval
   time, OMM epoch range, SOCRATES data-as-of time, hash, counts and
   `operational_collision_assessment: false` flag.

The four-object GP view and bounded SOCRATES OneWeb query are separate from the
2,661-object command globe. The SOCRATES rows are not locally recomputed and are
never passed to the RL worker.

### Offline and recorded rehearsal

This is mandatory even if the connected run succeeds:

1. Keep `.cache/daytona_rl/last_verified.json` only if it came from a result that
   passed the live rehearsal checks above.
2. Stop Streamlit with `Ctrl-C` and start it again with the network disconnected.
3. Complete all five tabs.
4. Confirm the command globe says cached or bundled replay, never live fetch.
5. Press **LOAD LAST VERIFIED REPLAY**. If no record exists, accept branch G and
   show Gen 0 only; never manufacture or hand-edit a result.
6. Run the separate deterministic scenario and confirm its integrity message.
7. Exercise the four fixed 8× options and **RESTORE JUDGE SCENARIO**.
8. Download the committee brief and synthetic evidence record.
9. Keep the network disconnected through one full timed narration using branch
   R or G.

The Daytona SDK needs host connectivity to create a live sandbox, but recorded
replay and Gen 0 do not. Public startup is offline by design.

## Friday: 30 minutes before the slot

```bash
cd "/Users/leonardaarons-ditson/Documents/ChatGPT/parliament hackathon/uk-orbit-guard"
git status --short --branch
source .venv/bin/activate
python -m pytest -q
python -m orbit_guard.demo --check
./scripts/run_demo.sh
```

If branch L is intended, set the hidden credential before the last command and
start the real run with enough time for creation, training, validation and
cleanup. Do not begin the spoken demo while deletion is still unconfirmed.

If port 8501 is occupied, the launcher refuses to guess which process owns it.
Close only a known stale process, or use:

```bash
ORBITGUARD_PORT=8502 ./scripts/run_demo.sh
```

Then present the matching 8502 browser tab.

### Browser state

1. Open all five tabs once.
2. Return to **00 SPACE COMMAND** with the default single `H-01` scenario.
3. Choose branch L, R or G from the visible evidence—not from intention.
4. For branch L, leave generation 0 selected so the Gen 0→10 story can be
   scrubbed forward on stage.
5. For branch R, load the record and verify the recorded ribbon before judges
   arrive.
6. Leave **Act now** selected on **03 MANOEUVRE OPTIONS**.
7. Run one timed rehearsal, then stop changing code, packages, fixtures and
   cache files.

Do not refresh CelesTrak on stage. A Daytona run may be demonstrated on stage if
the slot and venue network permit, but never trade the whole story for waiting:
name the current phase, continue through the other tabs, then return. If it is
not complete, leave it labelled in progress and use the deterministic policy
story without claiming a trained result.

## Stage flow

1. **Space Command:** name the 2,661-object public replay and the separate
   synthetic `GUARD-1` encounter.
2. **Training evidence:** show branch L, R or G exactly as labelled. If Gen 1–10
   are available, scrub 0 → intermediate → 10 and show the passport.
3. **Public Orbit Picture:** show the small CAA-linked example and bounded
   SOCRATES candidates as public audit context.
4. **Synthetic Alert:** cross the visible synthetic boundary.
5. **Manoeuvre Options:** deliver the independent, constructed 8× lead-time
   comparison.
6. **Committee Brief:** close on coverage, delivery time, operator readiness,
   auditability and human authority.

## Recovery order

Recover the evidence story, not every visual:

1. **Wrong UI state:** refresh the correct browser tab. Restore the default
   command scenario or fixed judge scenario as appropriate.
2. **Daytona not ready:** state branch G. Do not type or expose a credential in
   front of the room.
3. **Daytona run failed:** read the failure label. Use branch R only if a prior
   verified replay already exists and can be loaded; otherwise remain on Gen 0.
4. **Daytona still running:** name the visible phase, continue the other tabs,
   and return once. Do not repeatedly click Train or call it complete.
5. **Public source failure:** retain the cached/bundled view or skip to the
   synthetic path. Never manufacture freshness.
6. **Streamlit failed:** stop only the known process, relaunch, or use the
   verified alternate-port command.
7. **Visual app unavailable:** run `python -m orbit_guard.demo --check` and show
   the deterministic evidence record.
8. **Terminal unavailable:** use `artifacts/demo_result.json` and
   `artifacts/committee_brief.md` for the independent 8× story.

The committed screenshots cover the older public and deterministic synthetic
tabs, not a current Daytona run. Never use a screenshot as proof of live compute.

## Incident phrases

| Situation | Safe sentence | Next action |
|---|---|---|
| `LOCAL GEN 0 PREVIEW` | “The untrained synthetic baseline is local; no Daytona result is being implied.” | Continue with Gen 0 or the deterministic policy tabs. |
| `DAYTONA READY` | “The host can request a sandbox, but no run has started.” | Start only if the slot permits. |
| Active run | “The sandbox workflow is currently in the visible **phase**; completion has not yet been claimed.” | Continue the narrative and return once. |
| Daytona failed | “The remote run failed and the prototype did not substitute local training.” | Use recorded replay if already verified, otherwise Gen 0. |
| Recorded replay | “This is a validated prior Daytona replay, not current live compute.” | Show passport provenance and keep the label visible. |
| Public replay is old | “The source record is historical; SGP4 display propagation does not manufacture current telemetry.” | Point to origin, retrieval time and element epochs. |
| Candidate looks close | “That is a dated public source-modelled minimum range, not our collision probability or a flight decision.” | Point to the no-covariance boundary. |
| Asked for a manoeuvre | “This prototype issues none; current validated data and the authorised operator are required.” | Show the hard-stop language. |

## Close-down

1. Confirm any branch-L passport says `sandbox_deleted: true`.
2. Stop Streamlit with `Ctrl-C`.
3. Remove the credential from the shell:

   ```bash
   unset DAYTONA_API_KEY
   ```

4. Do not delete a verified recorded replay needed for the event. Do not commit
   `.cache/` or any credential-bearing file.

## Non-negotiable boundaries

- The 2,661 records are a dated subset from three public debris-event groups,
  not all tracked objects and not 2,661 collision threats.
- Public mean elements are not sensor telemetry or precise operator ephemerides.
- The RL input is synthetic and independent from all public records.
- CEM reward improvement is not collision-probability reduction, safety
  assurance, manoeuvre advice or national-performance evidence.
- No covariance, hard-body radius, validated real TCA, secondary screening,
  thruster constraints, command link, targeting or hostile attribution exists.
- No RAF, MOD, Parliament, NSpOC, UKSA, CAA, CelesTrak, Daytona or operator
  endorsement is claimed.
- Human operational authority is required before every real decision.
