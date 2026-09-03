# Data, provenance and limitations

UK Orbit Guard keeps public catalogue context and the fictional policy
counterfactual separate in code, labels, visuals and narration. Neither layer is an
operational collision-avoidance service.

## Data classes

| Data class | Purpose | What it can support | What it cannot support |
|---|---|---|---|
| CelesTrak public GP elements | Dated public orbit context from OMM-keyed JSON, with legacy TLE as a documented provider format | Approximate SGP4/TEME positions for the bounded 3D globe | Complete catalogue coverage, a local conjunction detector, precise ephemerides, covariance, safety status or manoeuvre advice |
| CAA public register metadata | Link one named public example to a UK regulatory record | Explain why UK-DMC-2 is a defensible UK-linked civil example | Current operational status, priority/protected status, military or RAF ownership, endorsement or control |
| CelesTrak SOCRATES Plus | Dated public conjunction-candidate input for the radial screen | Visualise source-reported object identity, TCA, minimum range and relative speed with provenance | Become a local collision probability, validate this prototype, import an operational threshold, or turn a candidate into a flight decision |
| Synthetic JSON fixture | Repeatable lead-time policy counterfactual | Demonstrate the constructed 8× manoeuvre-demand comparison | Describe any real object, alert, orbit, operator, mission or national performance |
| Dated NSpOC/UKSA/Parliament publications | Policy context and aggregate counts | Motivate scrutiny questions | Provide a live feed or evidence that this prototype has operational access |

The demo uses no restricted or classified data, no Space-Track credentials, no NSpOC
or Monitor Space Hazards account, and no spacecraft telemetry or command link.

## Visible provenance labels

These labels are boundaries, not decoration:

- global: `PUBLIC-DATA PROTOTYPE · NO RESTRICTED FEEDS · NO COMMAND · NOT FOR FLIGHT OPERATIONS`;
- public snapshot source: `CelesTrak public GP/OMM and SOCRATES Plus`;
- public snapshot context: `Public GP/OMM proximity context only; not operational collision assessment.`;
- load origin: `LATEST PUBLIC FETCH`, `CACHED PUBLIC SNAPSHOT` or
  `BUNDLED PUBLIC SNAPSHOT`;
- catalogue view: `PUBLIC ORBIT PICTURE / RECORDED SNAPSHOT` and
  `CELESTRAK GP/OMM · SGP4/TEME DISPLAY REPLAY`;
- candidate view: `PUBLIC-ELEMENT PROXIMITY SCREEN / 7-DAY WINDOW` and
  `CELESTRAK SOCRATES · PUBLIC GP MODEL`;
- public globe: `PUBLIC-ELEMENT CONTEXT · APPROXIMATE PROPAGATION · NO RESTRICTED DATA`;
- public radial screen: `CANDIDATES FOR FURTHER REVIEW · NO COVARIANCE · NOT A FLIGHT DECISION`;
- handoff boundary: `PUBLIC SCREEN ENDS HERE`;
- degraded public state: `CACHED / DEGRADED` plus the reason;
- synthetic tabs: `SYNTHETIC OFFLINE FIXTURE` and `SEPARATE FROM ALL PUBLIC OBJECTS`.

The public modes are named **Catalogue** and **Proximity screen**. “Candidate” means a
dated public record parsed from the SOCRATES Plus source and retained inside the display's
declared horizon. It must not be relabelled as an operational alert, collision, threat,
hazard, safe pass or manoeuvre target.

For every public snapshot or replay, read the summary ribbon/inspector and use the
downloadable public snapshot record for the full provenance:

| Provenance field | Required interpretation |
|---|---|
| **Data class / source** | Public GP elements from CelesTrak; never NSpOC or sensor data |
| **Exact source URLs / bounded object set** | Defines the fetched GP objects and SOCRATES query; the globe is not the entire tracked population |
| **Retrieved at (UTC)** | When the response was obtained, not the element observation time |
| **Element epoch** | Epoch carried by each GP record; mixed epochs and record age matter |
| **Cache/replay state and age** | Distinguishes a fresh cache, expired cache and committed historical replay |
| **Reference time** | The time at which positions and the declared horizon are evaluated |
| **Method** | SGP4 and TEME kilometre vectors for the globe; source-modelled SOCRATES fields for the radial screen |
| **Screen contract** | Persisted SOCRATES data-current timestamp, bounded source query and declared display horizon |
| **Counts** | Fetched, valid, propagation-error, invalid, outside-horizon and displayed counts |
| **Use flags** | Public records preserve `operational_collision_assessment: false`; the synthetic record separately preserves `operational_use: false` |

The two-hour cache rule governs **network retrieval**, not orbit accuracy. A response
inside the cache TTL is not automatically suitable for operations, and a recent retrieval
can still contain elements with older epochs.

## CAA-linked public example: UK-DMC-2

The public example is joined on identifiers rather than a name guess:

| Source | Name | International designator | Catalogue number | Public description |
|---|---|---|---:|---|
| CAA CAP 2207, March 2026 | `UK-DMC-2` | `2009-041C` | `35683` | Disaster Monitoring |
| CelesTrak public GP query | `UK-DMC 2` | `2009-041C` | `35683` | Public GP element record |

The [CAA register entry](https://www.caa.co.uk/data-and-publications/publications/documents/content/cap2207/)
records the object because it is in the UK Registry of Outer Space Objects. The
[CelesTrak query](https://celestrak.org/NORAD/elements/gp.php?CATNR=35683&FORMAT=JSON-PRETTY)
supplies public GP elements when a manual refresh is permitted. The app records the
element epoch returned at retrieval time; this document intentionally does not freeze a
moving epoch value.

This linkage says nothing about whether the object is currently operational, what
services it presently supports, whether it is nationally protected, or who would make a
current manoeuvre decision. It does not imply Parliament, CAA, UKSA, MOD or RAF
ownership, tasking, endorsement or access.

## Public-source acquisition and cache

[CelesTrak documents](https://celestrak.org/NORAD/documentation/gp-data-formats.php)
public general-perturbations queries in TLE and OMM-related formats. The prototype
prefers OMM-keyed JSON because it has explicit field names and is not constrained to
five-digit catalogue numbers. CelesTrak describes its JSON and CSV representations as
using OMM keywords; it recommends standard OMM XML for safety-critical systems. This
prototype is expressly non-operational.

The allowlisted globe snapshot is intentionally small: UK-DMC 2 (`35683`), ISS
(`25544`), PHISAT 2 (`60470`) and AC1-002 (`66745`). It is a four-object visual context,
not a screening population. The separate radial input is the bounded CelesTrak SOCRATES
query `NAME=oneweb,&ORDER=TCA&MAX=5`, whose source report declares its own seven-day
computation interval. That OneWeb-filtered report is not a screen centred on UK-DMC-2.

The retrieval contract is deliberately conservative:

1. The Friday default makes zero network requests. It loads a self-verifying local cache
   when one exists, otherwise the committed historical replay, and labels the origin.
2. A human may press **↻ REFRESH PUBLIC DATA IF DUE** during rehearsal or development.
3. A verified cache no older than two hours (the TTL boundary is inclusive) is reused
   instead of calling the source.
4. A successful GP/OMM and SOCRATES response must pass strict schema, size and value
   checks before replacing the verified cache.
5. A timeout, malformed response, HTTP 403/404 or other source
   error leaves the last verified cache/replay in place and displays a degraded reason.
6. The interface does not automatically retry. After a manual network attempt—successful
   or failed—the refresh control is disabled for two hours in that app session. CelesTrak
   says it checks for new GP data once every two hours and rate-limits excessive or
   erroneous requests.

“Latest public snapshot” means latest successfully verified snapshot available to the
prototype. It never means live sensor data. “Historical replay” means positions are
reproduced against the fixture's recorded reference time; the fixture is not projected
from its old epoch to the wall-clock present and presented as current.

The committed replay is `data/public_orbit_snapshot_2026-09-03.json`. A successful
manual refresh may update the uncommitted runtime cache at
`.cache/public_orbit_snapshot.json`; the two-hour TTL, strict validation and canonical
snapshot SHA-256 travel with the snapshot provenance. The digest binds the schema,
context, source label and URLs, retrieval UTC, earliest/latest OMM epochs, SOCRATES
data-as-of UTC and both record sets; only the digest field itself is excluded.

### Committed Friday replay provenance

| Field | Fixed fixture value |
|---|---|
| Source label | `CelesTrak public GP/OMM and SOCRATES Plus` |
| Retrieval UTC | `2026-09-03T09:21:39Z` |
| OMM epoch range | `2026-09-02T05:00:29.030112Z` to `2026-09-02T23:28:27.723360Z` |
| SOCRATES data as of | `2026-09-02T06:33:00Z` |
| Bounded contents | 4 OMM objects; 3 parsed SOCRATES candidates |
| Canonical snapshot SHA-256 | `205e1928755de30a36d2f3514e56a04e604b7ae1942b759b23c68e6942038d4d` |

These values describe the committed historical fixture only. A verified runtime cache
has its own displayed retrieval time, epoch range, data-as-of time and hash. The fixed
fixture must never be called current or live on Friday.

## Public pipeline A: GP/OMM catalogue globe

The 3D globe and radial screen have different source methods. For the globe, UK Orbit
Guard:

1. loads and strictly validates the four allowlisted public OMM-keyed records;
2. identifies UK-DMC-2 by designator `2009-041C` and catalogue number `35683`;
3. uses the recorded snapshot/replay reference time rather than silently substituting the
   wall-clock present;
4. propagates positions with the installed SGP4 implementation and checks its error code;
5. supplies Earth-centred TEME positions in kilometres to the visual; and
6. surfaces the source, retrieval time, OMM epoch range and any degraded state.

SGP4 here drives visual public-orbit context only. It does **not** pair objects, calculate
relative distance, prune a wider catalogue or generate a conjunction candidate. If SGP4
is unavailable, any simplified two-body display must be visibly degraded and evaluated
at element epoch; it must not be described as SGP4, current or operational.

The Python SGP4 documentation distinguishes the propagator's numerical precision from
the much larger prediction uncertainty of public mean elements. A correct library call
therefore does not make the source orbit precise or suitable for safety decisions.

### What the catalogue globe shows

- Earth-centred TEME kilometre positions at the recorded reference time;
- display type inferred from the public object name and encoded by shape/legend; this is
  not an authoritative source classification;
- a selected-object role distinct from a review-candidate role;
- trails only for the selected and review objects; and
- a visible empty or cached/degraded state when records are unavailable.

It is not to encounter-analysis scale, does not show sensor custody and is only the four
allowlisted objects—not a complete map of the tracked population.

## Public pipeline B: SOCRATES Plus candidate screen

The radial display does not run a local all-pairs screen. UK Orbit Guard strictly parses
the bounded public SOCRATES Plus response, validates the source report's computation
interval, persists its data-current timestamp, and transforms each valid row into a
visual candidate record.
The source fields include object identifiers, TCA, minimum range, relative speed and a
public maximum-probability field. The prototype does not recompute, promote or present
that source probability as its own operational conclusion.

The radial screen shows:

- radius: SOCRATES's source-modelled minimum range, displayed on a log transform while
  retaining physical km/m labels;
- clockwise angle: the source TCA relative to the stored SOCRATES data-as-of timestamp
  within the declared display horizon;
- shape: a transparent payload/rocket-body/debris display type inferred from the public
  name, with unknown as a separate class;
- smallest source-modelled ranges first, with the first three candidates labelled; and
- separate counts for invalid data and objects outside the declared horizon.

It is not an orbital plane, probability plot, risk score or decision boundary. Visual
closeness to the centre means only a smaller minimum range in the dated SOCRATES public
model output. It is not evidence of a collision, and absence from the bounded display is
not evidence of safety.

## SOCRATES is an input, not operational validation

[CelesTrak SOCRATES Plus](https://celestrak.org/SOCRATES/) publishes regular information
about pending conjunctions over the coming week. Its published methodology says it runs
active payloads against the public unclassified GP catalogue three times per day using
SGP4 and reports encounters within its own 5 km setting. CelesTrak also warns that
minimum distance without position covariance can exaggerate true risk and explains the
additional assumptions behind its maximum-probability field.

UK Orbit Guard uses bounded rows from that public report as input to the radial display;
it does not reproduce SOCRATES's catalogue-wide computation. The prototype does not
adopt its 5 km setting as a local or UK operational threshold, treat its probability
field as UK Orbit Guard's calculation, claim full-report coverage, or treat absence from
the bounded OneWeb query as safety. The source is public GP-model context—not a CDM,
operator ephemeris or validation of this hackathon prototype. Covariance-aware operational
assessment remains a separate step.

## Synthetic policy fixture

`scenarios/uk_eo_demo_1.json` is wholly fictional. Its protected asset, secondary object,
alert, service role and manoeuvre options exist only to make the counterfactual
reproducible. Every generated record includes:

- scenario ID and scenario-file SHA-256;
- `synthetic: true` and `operational_use: false`;
- model version, seed and assumptions; and
- the human-operator approval gate.

The model uses constant relative velocity in a two-dimensional local encounter plane. An
ideal instantaneous cross-track impulse produces:

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

The 8× result is an intentionally constructed inverse-lead-time comparison. It is not
measured operational performance. Δv is a manoeuvre-demand proxy—not fuel percentage,
cost, mission-life impact or probability reduction.

## Exclusions and hard stop

Neither layer includes:

- operational orbit determination or tracking-sensor fusion;
- precise operator ephemerides, covariance or conjunction data messages (CDMs);
- continuous TCA solving, hard-body radii or collision-probability calculation;
- atmospheric density and space-weather uncertainty beyond the source model;
- thruster, attitude, communications, execution or payload constraints;
- post-manoeuvre orbit determination or secondary-conjunction assessment;
- multi-operator coordination, licensing decisions or manoeuvre authority;
- hostile-object attribution, targeting, interception or autonomous command; or
- fuel, cost, mission-life or claimed national-performance estimates.

The prototype's authority ends at **candidate for further review**. Before any operational
decision, the authorised operator and appropriate operational service would need current
validated data, covariance and object geometry; compute an appropriate TCA and collision
probability; consider operational constraints and secondary conjunctions; coordinate as
required; and retain the human decision. [Monitor Space Hazards](https://www.monitor-space-hazards.service.gov.uk/)
provides eligible UK-licensed operators and government users with operational services;
UK Orbit Guard has no access to it.

## Authoritative sources

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
