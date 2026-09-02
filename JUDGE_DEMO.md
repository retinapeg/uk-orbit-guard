# UK Orbit Guard — Friday demo runbook

## The line to remember

> In this synthetic event, six hours of actionable warning achieves the same
> 1.2 km projected margin with one-eighth of the manoeuvre demand required at 45 minutes.

Always say **synthetic event**, **illustrative margin**, and **manoeuvre-budget demand**.
Never call the output an operational threshold, fuel percentage, collision probability,
flight command or RAF-endorsed system.

## Three-minute script

### 0:00–0:20 — Why this matters

> “The UK National Space Operations Centre issued an average of 1,913 collision
> warnings per month during 2025–26. Parliament has an active Space Resilience inquiry.
> UK Orbit Guard turns one conjunction alert into an auditable policy counterfactual.”

Point to the permanent red classification ribbon: synthetic, offline, not for flight operations.

### 0:20–0:50 — Show the alert

Open **01 Alert**.

> “This is a fictional UK Earth-observation asset and a fictional debris object in a
> synthetic near-co-orbital encounter. The projected miss is 120 metres in six hours.
> The one-kilometre buffer is illustrative; nothing here is live, restricted or a command.”

Rotate the 3D Earth once, then click **Run deterministic scenario**.

### 0:50–1:35 — Reveal the lead-time advantage

Open **02 Manoeuvre Options**.

1. Select **Act now**: 0.05 m/s at six hours gives 1.20 km.
2. Select **Wait: same burn**: 0.05 m/s at 45 minutes gives only 255 m.
3. Select **Wait: recover margin**: 0.40 m/s at 45 minutes restores 1.20 km.

> “Delay costs eight times the manoeuvre budget in this scenario. Warning latency is
> therefore a resilience lever, not merely a flight-dynamics detail.”

Point at the curve; do not improvise new physical claims.

### 1:35–2:30 — Make the RAF and Parliament relevance explicit

Open **03 Committee Brief**.

> “The RAF describes UK Space Command as a joint command based at RAF High Wycombe,
> and NSpOC combines civil and military space-domain awareness. Earlier actionable
> warning can preserve decision time, lower-demand avoidance options and availability
> of the space services supporting air and joint operations.”

> “Parliament should not fly satellites. It should ask whether capability investment
> produces usable lead time, whether data reaches operators quickly, and whether decisions
> and outcomes are auditable.”

Show the three scrutiny questions and the official RAF source.

### 2:30–3:00 — Close on credibility

Download the committee brief or evidence record.

> “UK Orbit Guard does not replace NSpOC. It makes the defensive value of earlier,
> auditable warning visible—from conjunction to committee in under a minute, with a
> human operator always in authority.”

## Expected numbers — do not change on stage

| Option | Expected projected miss | Expected Δv |
|---|---:|---:|
| Hold course | 120 m | 0.00 m/s |
| Act now | 1.20 km | 0.05 m/s |
| Wait: same burn | 255 m | 0.05 m/s |
| Wait: recover margin | 1.20 km | 0.40 m/s |

Delay penalty: **8.0×**.

## Thursday freeze

From the project root:

```bash
source .venv/bin/activate
python --version  # tested: Python 3.11.5
python -m pip install -r requirements-demo-lock.txt
python -m pytest -q
python -m orbit_guard.demo --check
./scripts/run_demo.sh
```

Then:

1. Open all three tabs and exercise all four fixed options.
2. Test the custom sliders and both downloads.
3. Disconnect the network, refresh, and repeat the judge path.
4. Confirm the three known-good screenshots exist in `artifacts/` for Alert, Options and Committee views.
5. Test at the actual presentation resolution and browser zoom.
6. Keep `requirements-demo-lock.txt` unchanged after the final rehearsal. Do not train PPO.

## Friday — 30 minutes before presenting

```bash
cd "/Users/leonardaarons-ditson/Documents/ChatGPT/parliament hackathon/uk-orbit-guard"
git status --short --branch
source .venv/bin/activate
python -m pytest -q
python -m orbit_guard.demo --check
./scripts/run_demo.sh
```

Presentation setup:

- open all three tabs once;
- select **Act now**, then return to **01 Alert**;
- close notifications and disable sleep;
- set browser zoom so the four KPIs and orbital view fit;
- keep the CLI result open behind the browser;
- keep `artifacts/committee_brief.md` ready as the second fallback;
- do not install packages, call an API, train PPO, use Daytona, or depend on Rote on stage.

## Recovery order

1. Refresh Streamlit and click **Restore judge scenario**.
2. If the UI fails, show `python -m orbit_guard.demo --check` in the terminal.
3. If the process will not restart, show `artifacts/demo_result.json` and
   `artifacts/committee_brief.md`.
4. Use the known-good images if necessary: `orbitguard_alert_fallback.jpg`,
   `orbitguard_options_fallback.jpg` and `orbitguard_committee_fallback.jpg`.
5. Keep the same 120 m → 1.20 km → 255 m → 1.20 km → 8× narrative.

## Hard integrity boundary

- No real satellite or debris object.
- No NSpOC login, API or restricted feed.
- No collision probability.
- No autonomous manoeuvre or command link.
- No hostile-object identification, interception or targeting.
- No RAF, MOD, Parliament, NSpOC or UKSA endorsement claim.
- No guarantee of safety or collision prevention.
