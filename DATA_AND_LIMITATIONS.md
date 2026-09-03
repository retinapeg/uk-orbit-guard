# Data, provenance and limitations

UK Orbit Guard joins several evidence classes in one interface without merging
their authority. The command globe is public catalogue context. The local
encounter, policy search and fixed lead-time comparison are synthetic. Daytona
is an execution boundary, not an operational data source or an accuracy claim.

Nothing in the prototype is a collision alert, collision-probability
calculation, manoeuvre recommendation, command link or safety certification.

## Evidence classes

| Evidence class | What is present | What it can support | What it cannot support |
|---|---|---|---|
| Command-centre CelesTrak debris catalogue | Dated GP/OMM records from three named debris-event groups | Visual public-orbit scale and approximate SGP4 display positions | A complete catalogue, sensor custody, a local conjunction screen, current precise ephemerides, covariance, safety status or manoeuvre advice |
| Four-object CelesTrak GP/OMM snapshot | Bounded public records including UK-DMC-2 | Inspectable small public catalogue example | Representation of the 2,661-record debris field or a claim that the four objects encounter one another |
| CAA register metadata | UK-DMC-2 identifiers and public function description | A defensible UK-linked civil regulatory/catalogue example | Current mission status, protected priority, military ownership, control or endorsement |
| CelesTrak SOCRATES Plus rows | Dated, bounded public source-report records | Visualise source-reported object identity, TCA, minimum range and relative speed | Reproduce the source's catalogue-wide computation, become a local collision probability, establish safety or trigger a manoeuvre |
| Synthetic Hill/LVLH RL encounter | One to six deterministic injection templates, controlled satellite state, actions and rewards | Demonstrate a small auditable policy-search workflow | Describe a real object, real orbit, real conjunction, mission constraint or operational manoeuvre |
| Daytona execution evidence | Captured worker bundle, frozen synthetic request, sandbox identity, result and cleanup fields | Show that a bounded synthetic job ran inside the identified sandbox when the current run passport proves it | Validate the physics, convert synthetic results into operational advice, or prove that a run occurred merely because code exists |
| Synthetic lead-time fixture | Versioned fictional alert and four fixed options | Demonstrate the constructed 8× manoeuvre-demand comparison | Represent the RL reward, any public object, measured performance or fuel/risk saving |
| NSpOC, UKSA and Parliament publications | Dated policy context and published aggregates | Motivate resilience and scrutiny questions | Provide a live feed, operational access or endorsement of this prototype |

The demo uses no restricted or classified data, Space-Track credentials, NSpOC
or Monitor Space Hazards account, operator telemetry, command link, hostile
attribution or targeting data.

## The three sets that must never be conflated

1. **2,661 command-globe records** — a committed public CelesTrak debris-event
   snapshot. These objects provide visual context only.
2. **Four public catalogue records plus three stored SOCRATES candidates** — the
   separate audit view under **01 PUBLIC ORBIT PICTURE**.
3. **One to six synthetic hazards** — deterministic local templates created by
   the command buttons and used by the RL worker.

No identifier or orbit is copied from sets 1 or 2 into set 3. The phrase
“screened synthetic encounter” describes the UI workflow, not a claim that the
public catalogue was screened into a real encounter.

## Public pipeline A: command-centre debris catalogue

### Committed fixture

`data/debris_catalogue_snapshot_2026-09-03.json` is a strict, integrity-bound
snapshot constructed from these exact CelesTrak public GP endpoints:

- `https://celestrak.org/NORAD/elements/gp.php?GROUP=FENGYUN-1C-DEBRIS&FORMAT=JSON`
- `https://celestrak.org/NORAD/elements/gp.php?GROUP=IRIDIUM-33-DEBRIS&FORMAT=JSON`
- `https://celestrak.org/NORAD/elements/gp.php?GROUP=COSMOS-2251-DEBRIS&FORMAT=JSON`

| Fixture field | Committed value |
|---|---|
| Record type | `uk-orbit-guard-public-debris-catalogue` |
| Schema version | `1` |
| Retrieval UTC | `2026-09-03T12:01:51Z` |
| Unique records after NORAD-ID de-duplication | `2,661` |
| Display classification from the returned names | `2,658` names ending ` DEB`; `3` named parent objects |
| FENGYUN-1C-DEBRIS | `1,963` |
| IRIDIUM-33-DEBRIS | `111` |
| COSMOS-2251-DEBRIS | `587` |
| Earliest OMM epoch in the fixture | `2026-08-04T16:45:09.696960Z` |
| Latest OMM epoch in the fixture | `2026-09-03T05:27:55.916928Z` |
| Canonical content SHA-256 | `e16d8db7f52ebecebfbd6d6d20bef570e1bddd25042238fafbce2f944a9df398` |

These counts and timestamps describe the committed replay only. A future
validated refresh can return a different count, membership and element-epoch
range. Each result includes its named parent object (`FENGYUN 1C`, `IRIDIUM 33`
or `COSMOS 2251`) as well as debris records. “2,661 public objects” therefore
means 2,661 unique records returned by the three chosen debris-event group
queries. In this fixture, 2,658 names end in ` DEB` and three are the named
parent objects. It does not mean 2,661 debris fragments, all tracked objects,
all debris, all UK-relevant objects, or 2,661 conjunction threats.

The canonical digest covers schema, record type, retrieval timestamp, exact
allowlisted source URLs and every retained OMM record. It detects corruption or
an unaccompanied change when checked against a separately reviewed digest, such
as the value in this document or a trusted Git commit. It does not authenticate
CelesTrak, certify source accuracy or resist an attacker able to rewrite both
the records and their in-file digest.

### Load and refresh contract

The default call is `load_catalogue(allow_network=False)`. Startup therefore
makes **zero network requests**. Load order is:

1. validated cache at `.cache/debris_catalogue.json` if its retrieval timestamp
   is within the inclusive 12-hour TTL;
2. otherwise, the newer validated source between the stale cache and committed
   bundled replay; or
3. an explicit unavailable error when neither source validates.

Only the human-operated **REFRESH IF DUE** button calls
`load_catalogue(allow_network=True)`. A due refresh performs one request with a
15-second timeout for each of the three exact allowlisted URLs, bounding the
serial request wait to 45 seconds. It rejects unexpected redirects and
non-200 responses, strictly parses OMM records, de-duplicates by NORAD catalogue
ID, enforces a maximum of 5,000 combined records and atomically writes a
validated cache.

The 12-hour value is a prototype retrieval/cache rule. It is not a statement of
CelesTrak publication frequency, orbit accuracy, conjunction freshness or
operational suitability. The separate four-object public snapshot uses a
different two-hour retrieval rule.

If a source refresh fails, the interface retains the last validated source
record when available and shows a warning. Repeated venue retries are not a
recovery strategy. A cache/replay label must remain visible.

### SGP4 command-globe display

`catalogue_globe_records` applies SGP4 to each public mean-element record for a
declared display timestamp and returns Earth-centred TEME kilometre vectors.
The UI labels that timestamp `DISPLAYED`. It is the propagation evaluation time,
not the observation time, source retrieval time or proof of present telemetry.

In the current command view, the default position track re-evaluates the loaded
elements at wall-clock time every five seconds. **PAUSE TRACK** freezes that
visual clock and **RESUME TRACK** restarts it. This can project a bundled
historical record beyond its retrieval time. `5 s DATED-ELEMENT DISPLAY
PROPAGATION` therefore describes the display calculation, not a live source.
The provenance label still determines whether the input is a current-session
fetch, cache, stale cache or bundled replay, and the underlying mixed element
epochs remain the accuracy boundary. Never turn “displayed now” into “observed
now”.

Rows whose SGP4 propagation reports an error are omitted from the display. If
the displayed-object count differs from the validated catalogue count, describe
the globe as degraded and do not infer anything from missing points.

The globe also embeds the final synthetic `GUARD-1` local offset on an
illustrative 550 km reference orbit. That visual co-location does not give the
synthetic object a real Earth-centred orbit and does not establish proximity to
any public debris point.

## Public pipeline B: four-object audit snapshot

The separate `data/public_orbit_snapshot_2026-09-03.json` fixture contains:

- UK-DMC 2 (`35683`);
- ISS (`25544`);
- PHISAT 2 (`60470`);
- AC1-002 (`66745`); and
- three parsed rows from the bounded SOCRATES query
  `NAME=oneweb,&ORDER=TCA&MAX=5`.

It is a four-object visual context, not a screening population. The SOCRATES
rows do not describe a screen of UK-DMC-2 against those four objects.

| Fixture field | Committed value |
|---|---|
| Source label | `CelesTrak public GP/OMM and SOCRATES Plus` |
| Retrieval UTC | `2026-09-03T09:21:39Z` |
| OMM epoch range | `2026-09-02T05:00:29.030112Z` to `2026-09-02T23:28:27.723360Z` |
| SOCRATES source data as of | `2026-09-02T06:33:00Z` |
| Contents | 4 OMM objects; 3 SOCRATES candidates |
| Canonical snapshot SHA-256 | `205e1928755de30a36d2f3514e56a04e604b7ae1942b759b23c68e6942038d4d` |

Startup is also offline/cache-first. A human may press **REFRESH PUBLIC DATA IF
DUE**; a validated cache inside the inclusive two-hour TTL is reused, and any
network attempt starts a two-hour UI cooldown. Successful data must pass strict
schema, size, identity, URL and value checks. An HTTP 403/404 is not retried.
The uncommitted cache path is `.cache/public_orbit_snapshot.json`.

For the committed historical fixture, globe positions are replayed with SGP4 at
the snapshot retrieval time rather than silently promoted to current wall-clock
positions. A per-record simplified fallback, when required, is explicitly
labelled and must not be described as SGP4.

The digest binds schema, context, source label and URLs, retrieval time, OMM
epoch bounds, SOCRATES data-as-of time and both record sets. The digest field
alone is excluded. Integrity proves coherence, not operational quality.

## CAA-linked public example: UK-DMC-2

The small public view joins identifiers rather than guessing from a name:

| Source | Name | International designator | Catalogue number | Public description |
|---|---|---|---:|---|
| CAA CAP 2207, March 2026 | `UK-DMC-2` | `2009-041C` | `35683` | Disaster Monitoring |
| CelesTrak public GP query | `UK-DMC 2` | `2009-041C` | `35683` | Public GP element record |

The [CAA register entry](https://www.caa.co.uk/data-and-publications/publications/documents/content/cap2207/)
supports the UK regulatory link. The
[CelesTrak query](https://celestrak.org/NORAD/elements/gp.php?CATNR=35683&FORMAT=JSON-PRETTY)
supports the public catalogue link.

This says nothing about current operational status, service availability,
national protection priority, present ownership or who would make a manoeuvre
decision. It does not imply Parliament, CAA, UKSA, MOD or RAF access, tasking,
control or endorsement.

## Public pipeline C: bounded SOCRATES display

The radial display does not run a local all-pairs detector. It parses stored
public SOCRATES Plus rows and visualises:

- radius: the source-modelled minimum range, shown with a logarithmic display
  transform while retaining physical distance labels;
- clockwise angle: reported TCA relative to the stored SOCRATES data-as-of time;
- shape: a display type inferred from the public name, not authoritative source
  classification; and
- counts: displayed, invalid and outside the declared seven-day horizon.

The zero-time tick is labelled `SOURCE AS-OF`, not “now”. A close-looking point
is a small source-modelled minimum range in a dated public model output. It is
not an orbital plane, risk score, probability, decision threshold or evidence
of collision. Absence from the bounded view is not evidence of safety.

[CelesTrak SOCRATES Plus](https://celestrak.org/SOCRATES/) publishes public
information about pending conjunction candidates using its documented public
GP model. UK Orbit Guard does not reproduce its catalogue-wide calculation,
adopt its source setting as a UK threshold, recompute its maximum-probability
field, or treat it as operational validation. It is not a conjunction data
message (CDM), operator ephemeris or covariance-aware assessment.

## Synthetic RL model

### Scenario

The command buttons build one to six allowlisted deterministic templates:

- `head_on`;
- `crossing`; and
- `fast_debris`.

The controlled synthetic satellite begins at the origin of a planar Hill/LVLH
local encounter frame around an illustrative 550 km circular reference orbit.
The injected objects follow constant-velocity local paths. The satellite follows
a semi-implicit discrete integration of the planar Clohessy-Wiltshire/Hill
equations.

Default episode constants:

| Parameter | Value |
|---|---:|
| Time step | 20 s |
| Maximum steps | 72 |
| Horizon | 1,440 s / 24 min |
| Illustrative keep-out radius | 0.35 km |
| Commanded acceleration magnitude | 0.000005 km/s² = 0.005 m/s² |
| Impulse per held thrust step | 0.10 m/s |
| Maximum injected objects | 6 |

The keep-out radius is a synthetic termination rule, not an operator, NSpOC,
CAA, RAF or CelesTrak standard.

### Observation and action spaces

The fixed 12-component observation contains:

1. satellite radial and along-track position;
2. satellite radial and along-track velocity;
3. nearest-risk object's relative position;
4. nearest-risk object's relative velocity;
5. clipped time-to-closest-approach proxy;
6. miss-distance proxy;
7. object-count fraction; and
8. episode progress.

All policies have 65 parameters: five actions × (12 observations + one bias).
The five deterministic discrete actions are `COAST`, `RADIAL OUT`, `RADIAL IN`,
`PROGRADE` and `RETROGRADE`.

### Reward and termination

Each step begins with a small survival term and subtracts declared penalties for
proximity, use of thrust and large local displacement. A keep-out breach at or
below 0.35 km adds a large penalty and terminates the episode; reaching the
horizon adds a synthetic completion bonus. The displayed “minimum simulated
clearance” is the smallest sampled step separation in this model, not continuous
TCA, hard-body clearance or collision probability.

Optimising this reward does not guarantee maximum clearance, minimum fuel,
robust control or monotonic improvement. The retained checkpoint is selected by
nominal synthetic validation reward. The training plot shows population mean
return and retained-policy replay return; neither line is a safety curve.

### Cross-entropy policy search

The fixed stage job uses:

- seed 42;
- generation 0 as the all-zero `COAST` baseline;
- 10 training generations;
- 24 candidates per generation;
- 3 perturbed episodes per candidate; and
- 720 executed search episodes, plus deterministic validation replays.

Training samples policy weights from an evolving Gaussian distribution and
updates its mean and spread from the elite candidates. Perturbations alter each
synthetic object's starting position by at most ±0.12 km and scale each velocity
component by 0.94–1.06. This is lightweight cross-entropy episodic policy search,
not the inherited PPO scaffold.

The result is rejected if no policy parameter changed from Gen 0. A changed
checkpoint proves the search produced different parameters; it does not prove
the learned policy is operationally useful.

## Daytona lifecycle and evidence

The host-only SDK is pinned in `requirements-live.txt` as
`daytona==0.207.0`. The sandbox worker itself uses the Python standard library.
`DAYTONA_API_KEY` must contain a non-blank value in the Streamlit process and
the installed SDK must match `0.207.0` for the live control to unlock. The app
checks presence only and never intentionally displays the credential value.

A requested run:

1. freezes the deterministic hazards and scenario SHA-256;
2. captures `rl_core.py` and `daytona_rl_worker.py` and computes a runtime-bundle
   SHA-256;
3. creates one private, ephemeral Daytona sandbox with outbound networking
   blocked, auto-stop disabled and a 12-minute TTL;
4. uploads the frozen worker files and JSON request, then has the sandbox worker
   independently recompute the same sorted-file runtime digest before training;
5. runs the worker with a five-minute command timeout;
6. checks the remote result metadata against a 10 MB ceiling, then downloads it;
7. validates the exact schema, sandbox ID, invocation ID, scenario and runtime
   hashes, model constants, action/observation dimensions, training counts,
   timestamps, checkpoint change, reward sums, trajectories, object identities
   and non-operational flags;
8. waits for explicit sandbox deletion; and
9. only then returns a result marked `result_validated: true`,
   `sandbox_deleted: true` and `local_training_fallback_used: false`.

The state ledger can show `QUEUED`, `CREATING`, `LIVE`, `TRAINING`,
`VALIDATING`, `RESULT_COLLECTED`, `CLEANED`, `COMPLETE` or `FAILED`.
An intermediate state is not evidence of completion. If cleanup cannot be
confirmed, collected output is rejected.

The sandbox-side bundle digest detects transfer corruption or unexpected file
replacement between capture and execution. It is an integrity cross-check, not
cryptographic attestation of Daytona's platform or host.

Per-run host files are stored under
`.cache/daytona_rl/<invocation-id>/` as a request, live-state ledger, result
envelope and controller log. The latest accepted envelope may be copied to
`.cache/daytona_rl/last_verified.json`. These are local runtime artefacts and
must not contain or substitute for the API key.

The UI contracts are:

- `VERIFIED DAYTONA RESULT` — current app session received an accepted result;
- `RECORDED DAYTONA REPLAY` — a prior accepted envelope was loaded, explicitly
  not current live compute;
- `LOCAL GEN 0 PREVIEW` — only the deterministic untrained baseline is present;
  and
- `DAYTONA FAILED — no local result was substituted` — the remote route failed.

This repository state and its unit tests do not establish that any live sandbox
was created. Only current credential-backed runtime evidence and its run passport
support that claim.

## Separate synthetic lead-time fixture

`scenarios/uk_eo_demo_1.json` is wholly fictional and is not the RL scenario.
Its protected asset, secondary object, alert, service role and manoeuvre options
exist only to make a policy counterfactual reproducible. Every generated record
includes its scenario hash, `synthetic: true`, `operational_use: false`, model
version, seed, assumptions and human-approval gate.

The ideal model uses:

```text
cross-track displacement = Δv × actionable lead time
projected miss           = 120 m baseline + cross-track displacement
```

Therefore:

```text
0.05 m/s × 21,600 s + 120 m = 1,200 m
0.05 m/s ×  2,700 s + 120 m =   255 m
0.40 m/s ×  2,700 s + 120 m = 1,200 m
0.40 m/s ÷ 0.05 m/s         =     8×
```

The 8× value is an intentionally constructed inverse-lead-time comparison. It
is not learned by Daytona, measured operational performance, fuel percentage,
cost, mission-life impact or collision-probability reduction.

## Visible label dictionary

| Label | Required interpretation |
|---|---|
| `CURRENT-SESSION CELESTRAK GP FETCH` | Validated response from the three public debris group URLs; still not telemetry or operational data |
| `CACHED CELESTRAK GP SNAPSHOT` | Validated runtime cache; “cached” must remain visible |
| `STALE CACHED CELESTRAK GP SNAPSHOT` | Validated cache beyond the 12-hour retrieval window; degraded age remains visible |
| `BUNDLED CELESTRAK GP REPLAY` | Committed historical source record; never call it current |
| `5 s DATED-ELEMENT DISPLAY PROPAGATION` | A wall-clock display calculation over loaded mean elements; never live observation or telemetry |
| `PUBLIC MEAN-ELEMENT CONTEXT · NOT SENSOR TELEMETRY` | Command-globe data boundary |
| `DAYTONA READY` | SDK and key presence only; no run evidence |
| `LIVE DAYTONA COMPUTE` | Current invocation in progress; phase-specific evidence only |
| `VERIFIED DAYTONA RESULT` | Accepted current-session result and confirmed deletion |
| `RECORDED DAYTONA REPLAY` | Accepted prior record; not current live compute |
| `LOCAL GEN 0 PREVIEW` | Local untrained baseline; no remote result |
| `PUBLIC-ELEMENT PROXIMITY SCREEN / 7-DAY WINDOW` | Bounded dated SOCRATES display, not a local detector |
| `SOURCE AS-OF` | SOCRATES reference time, not wall-clock now |
| `CANDIDATES FOR FURTHER REVIEW` | Limit of prototype authority |
| `SYNTHETIC OFFLINE FIXTURE` | Start of the separate fixed 8× counterfactual |

## Operational exclusions and hard stop

The prototype does not include:

- operational orbit determination or tracking-sensor fusion;
- precise operator ephemerides, covariance or conjunction data messages;
- continuous TCA solving, hard-body radii or collision probability;
- validated atmospheric density or space-weather uncertainty;
- thruster, attitude, communications, payload or mission constraints;
- post-manoeuvre orbit determination or secondary-conjunction assessment;
- operator-to-operator coordination, licensing decisions or manoeuvre authority;
- secure integration with NSpOC, RAF, MOD, CAA or an operator;
- hostile-object attribution, interception, targeting or autonomous command; or
- verified fuel, cost, mission-life or national-performance estimates.

The prototype's authority ends at **candidate for further review**. Before any
operational decision, the authorised operator and appropriate operational
service would need current validated data, covariance and object geometry;
compute an appropriate TCA and collision probability; assess mission and
execution constraints and secondary conjunctions; coordinate as required; and
retain human decision authority.

[Monitor Space Hazards](https://www.monitor-space-hazards.service.gov.uk/)
provides eligible UK-licensed operators and government users with operational
services. UK Orbit Guard has no access to it.

## Authoritative public sources

1. [CAA: licences granted and registers of space objects](https://www.caa.co.uk/space/about-the-space-team/licences-granted-and-registers-of-space-objects/)
2. [CAA CAP 2207: UK Registry of Outer Space Objects](https://www.caa.co.uk/data-and-publications/publications/documents/content/cap2207/)
3. [CelesTrak: GP data formats, queries and usage guidance](https://celestrak.org/NORAD/documentation/gp-data-formats.php)
4. [CelesTrak: UK-DMC 2 public GP record](https://celestrak.org/NORAD/elements/gp.php?CATNR=35683&FORMAT=JSON-PRETTY)
5. [CelesTrak: SOCRATES Plus methodology](https://celestrak.org/SOCRATES/)
6. [CelesTrak: bounded OneWeb SOCRATES query used by the fixture](https://celestrak.org/SOCRATES/table-socrates.php?NAME=oneweb,&ORDER=TCA&MAX=5)
7. [Python SGP4: reference implementation and accuracy discussion](https://github.com/brandon-rhodes/python-sgp4/blob/master/README.rst)
8. [CCSDS: Orbit Data Messages Recommended Standard](https://public.ccsds.org/Pubs/502x0b3e1.pdf)
9. [NASA CARA: conjunction-event prediction](https://www.nasa.gov/cara/step-1-conjunction-event-prediction/)
10. [NASA CARA: close-approach risk assessment](https://www.nasa.gov/cara/step-2-close-approach-risk-assessment/)
11. [NSpOC: role and mission sets](https://www.gov.uk/government/organisations/national-space-operations-centre/about)
12. [RAF: UK Space Command](https://www.raf.mod.uk/what-we-do/uk-space-command/)
13. [UK Parliament: Space Resilience inquiry](https://committees.parliament.uk/committee/111/national-security-strategy-joint-committee/news/217022/security-in-space-committee-launches-new-inquiry-on-space-resilience/)
