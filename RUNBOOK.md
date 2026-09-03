# UK Orbit Guard — Friday runbook

## Demo objective

Deliver one clear argument without depending on the network:

> In the deterministic synthetic event, acting at six hours reaches the same illustrative
> 1.2 km margin with one-eighth of the manoeuvre demand required at 45 minutes.

The optional public-orbit picture adds provenance and scale. It is not allowed to become
the critical path, and it must never be described as operational collision detection.

## Thursday freeze

Run these commands from the project root:

```bash
cd "/Users/leonardaarons-ditson/Documents/ChatGPT/parliament hackathon/uk-orbit-guard"
git status --short --branch
source .venv/bin/activate
python --version
python -m pip install -r requirements-demo-lock.txt
python -m compileall -q app.py src
python -m pytest -q
python -m orbit_guard.demo --check
git diff --exit-code -- artifacts/demo_result.json artifacts/committee_brief.md
```

The frozen environment was tested on Python 3.11.5. Do not regenerate the exact lock,
upgrade a package or train the inherited PPO scaffold after the final rehearsal.

### Connected public-data rehearsal

Do this once while a network is available, before the event—not on stage:

1. Start the app with `./scripts/run_demo.sh` and open <http://127.0.0.1:8501>.
2. Open **00 PUBLIC ORBIT PICTURE** and read the displayed source, retrieval time,
   content-hash prefix and cache/replay state.
3. If a refresh is needed, press **↻ REFRESH PUBLIC DATA IF DUE** once. Do not press it again
   inside two hours. After any network attempt the app disables that control for two
   hours in the current session. CelesTrak says new GP data is checked once every two
   hours and may rate-limit excessive or erroneous requests.
4. Confirm UK-DMC-2 is joined by `2009-041C` and catalogue `35683`; do not rely on name
   spelling alone.
5. In **Catalogue**, confirm the inferred display-type legend, selected object and
   exact `PUBLIC ORBIT PICTURE / RECORDED SNAPSHOT` and
   `CELESTRAK GP/OMM · SGP4/TEME DISPLAY REPLAY` labels; never present the shapes as
   authoritative catalogue classifications. The inspector's **Display model** must say
   `SGP4/TEME at snapshot retrieval time`; if it says two-body fallback, treat the globe
   as degraded and skip it on stage.
6. In **Proximity screen**, confirm the display is labelled as the separate bounded
   SOCRATES OneWeb query—not a UK-DMC-2 encounter screen. Check the exact
   `PUBLIC-ELEMENT PROXIMITY SCREEN / 7-DAY WINDOW` and
   `CELESTRAK SOCRATES · PUBLIC GP MODEL` labels, source-modelled minimum-range/TCA
   values, candidate counts, invalid counts and outside-horizon counts.
7. Download **DOWNLOAD PUBLIC SNAPSHOT RECORD** and confirm it contains the full
   source URLs, retrieval UTC, OMM epoch range, SOCRATES data-as-of UTC, canonical hash,
   human-authority flag and `operational_collision_assessment: false`.
8. Confirm any source error remains visible as `CACHED / DEGRADED` and does not clear a
   last verified display or manufacture a current result.
9. If CelesTrak returns HTTP 403/404, stop. Do not retry; use the replay and investigate
   after the demo.

The committed fallback is `data/public_orbit_snapshot_2026-09-03.json`. A successful
manual refresh may write `.cache/public_orbit_snapshot.json`; that uncommitted cache must
remain self-validating and visibly distinguished from the committed historical replay.
If the cache cannot be written, the app retains the verified in-memory refresh, labels
the persistence failure and leaves the committed replay untouched.

SOCRATES Plus is the public-record input to the radial visual, but the web page is not a
stage dependency. Do not present its probability field as a UK Orbit Guard calculation,
adopt its 5 km setting as a UK threshold or claim the bounded query reproduces its
catalogue-wide computation.

### Offline rehearsal—the required proof

After the connected check:

1. stop the Streamlit process cleanly with `Ctrl-C`;
2. disconnect Wi-Fi/network access;
3. start again with `./scripts/run_demo.sh`;
4. refresh the browser and complete all four tabs;
5. verify the public area visibly says cache/replay rather than live/current;
6. switch between **Catalogue** and **Proximity screen**;
7. click **RUN DETERMINISTIC SCENARIO** and wait for the integrity confirmation;
8. exercise all four fixed synthetic options and **RESTORE JUDGE SCENARIO**;
9. download the committee brief and synthetic evidence record; and
10. keep the network disconnected through one full timed three-minute run.

If the public replay cannot render offline, accept presenter branch C: skip the public
visual and use the synthetic lab. Do not weaken or postpone the deterministic path to
repair an optional source on stage.

### Visual and room check

- Use the actual laptop, charger, display adaptor, screen resolution and browser zoom.
- Confirm the four tab names fit and the global provenance ribbon remains visible.
- Check both public modes, the 3D controls, radio options, sliders and downloads.
- Turn off notifications, automatic updates, screen sleep and battery-saving dimming.
- Keep the pointer large enough to follow from the back of the room.
- Test without browser developer tools, terminal overlays or personal tabs visible.
- Open the dated public-context captures in advance:
  `orbit-guard-public-catalogue.png`, `orbit-guard-public-globe.png` and
  `orbit-guard-public-screen.png`.
- Open the three synthetic fallbacks in advance:
  `orbitguard_alert_fallback.jpg`, `orbitguard_options_fallback.jpg` and
  `orbitguard_committee_fallback.jpg`.
- Keep `artifacts/committee_brief.md` and `artifacts/demo_result.json` open locally.

The public captures are fixed evidence of the visibly dated 3 September 2026 snapshot,
not a current source. Use them only with that historical-replay description and their
visible provenance; otherwise skip the public view. The synthetic screenshots remain the
network-independent critical-path fallback.

## Friday—30 minutes before presenting

Use the frozen checkout and environment:

```bash
cd "/Users/leonardaarons-ditson/Documents/ChatGPT/parliament hackathon/uk-orbit-guard"
git status --short --branch
source .venv/bin/activate
python -m pytest -q
python -m orbit_guard.demo --check
./scripts/run_demo.sh
```

The launcher checks port 8501 before starting. If the port is occupied, it refuses to
guess which application owns it. Do not kill an unknown process. Either close the known
old Streamlit process or launch a fresh instance on a verified alternate port:

```bash
ORBITGUARD_PORT=8502 ./scripts/run_demo.sh
```

Then open <http://127.0.0.1:8502>. Do not accidentally keep presenting the old 8501 tab.

### Browser state

1. Open each of the four tabs once.
2. Put **00 PUBLIC ORBIT PICTURE** in **Catalogue** mode with UK-DMC-2 selected.
3. Read the visible cache/replay state and choose presenter branch A, B or C from
   [DEMO_SCRIPT.md](DEMO_SCRIPT.md).
4. Leave **Act now** selected on **02 MANOEUVRE OPTIONS**.
5. Return to **00 PUBLIC ORBIT PICTURE**.
6. Keep the terminal check, CLI result and local fallback files behind the browser.
7. Run one timed rehearsal, then stop touching the environment.

Do not on stage:

- press **↻ REFRESH PUBLIC DATA IF DUE**;
- install or upgrade packages;
- change the comparison set, cache, fixture, clock or screen parameters;
- open NSpOC/Monitor Space Hazards, CAA or CelesTrak web pages as a dependency;
- claim a cache is live, or hide an expired/degraded label;
- call Daytona, depend on Rote, train PPO or invoke any external model;
- edit the app, docs, scenarios or artefacts; or
- improvise physical, national-performance, fuel-saving or ownership claims.

Rote is not a runtime dependency for this demo and does not need to be installed for the
Friday path.

## Recovery order

Recover the story, not every feature:

1. **UI state only:** refresh the browser, return to the correct verified port and click
   **RESTORE JUDGE SCENARIO**.
2. **Public source/replay failure:** state presenter branch C and move to
   **01 SYNTHETIC ALERT**. Never refresh repeatedly.
3. **Streamlit process failed:** return to the terminal, stop the known process with
   `Ctrl-C`, then run `./scripts/run_demo.sh`. If port 8501 is occupied, use the verified
   8502 command above.
4. **Visual app unavailable:** run `python -m orbit_guard.demo --check` and show the
   verified 120 m → 1.20 km → 255 m → 1.20 km → 8× record.
5. **Terminal unavailable:** show `artifacts/demo_result.json`, then
   `artifacts/committee_brief.md`.
6. **Public visual fallback:** only if useful, show Public Catalogue, Public Globe and
   Public Screen with the words “dated public-context capture”; never call them current.
7. **Last synthetic visual fallback:** show Alert, Options and Committee in order and
   deliver the same deterministic narration.

Never substitute a random web orbit visual, make a last-minute API call or describe a
stale screenshot as current.

## Incident phrases

| Situation | Safe sentence | Next action |
|---|---|---|
| Public cache/replay is degraded | “The optional public source is unavailable, and the prototype refuses to manufacture freshness.” | Go to **01 SYNTHETIC ALERT**. |
| No candidates display | “An empty bounded display is not proof of safety; the source query, time window and method are limited.” | Show provenance briefly, then continue. |
| Candidate looks extremely close | “That is SOCRATES's public source-modelled minimum range, not a UK Orbit Guard collision probability or safety decision.” | Point to the no-covariance boundary. |
| Someone calls UK-DMC-2 an RAF asset | “It is a CAA-linked civil public example; we make no military ownership or current-status claim.” | Move to the synthetic boundary. |
| Asked for a manoeuvre | “This prototype issues none; current validated data and the authorised operator are required.” | Show the hard-stop language. |
| Display or app fails | “The core result is deterministic and independently verified; I’ll show the local evidence record.” | Use recovery steps 4–6. |

## Integrity boundary—read before presenting

- Public GP elements, bounded SOCRATES public model rows and CAA metadata only; no
  restricted, classified or live sensor feed.
- Declared comparison set only; no complete-catalogue or custody claim.
- Approximate SGP4/TEME positions for the four-object globe; no local pairwise detector.
- Parsed, bounded SOCRATES Plus candidate rows for the radial display; no reproduction
  of the source service's catalogue-wide computation.
- No covariance, hard-body radius, collision probability or safety classification.
- No real protected asset and no public object in the synthetic 8× encounter.
- No autonomous manoeuvre, command link, interception, targeting or hostile attribution.
- No RAF, MOD, Parliament, NSpOC, UKSA, CAA, CelesTrak or operator endorsement.
- No guarantee of safety, collision prevention, fuel saving or service availability.
- Human operational authority is required before every real decision.
