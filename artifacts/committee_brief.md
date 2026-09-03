# UK Orbit Guard — synthetic committee brief

> **SYNTHETIC · OFFLINE · POLICY SIMULATOR · NOT FOR FLIGHT OPERATIONS**

Scenario `SYN-UK-0001` uses model `local-linear-v0.1` and seed
`42`. The protected asset and debris object are fictional.

## Headline finding

In this synthetic event, acting with six hours of warning reaches approximately
**1.20 km** projected separation using a
**0.05 m/s** cross-track manoeuvre. Waiting until
45 minutes before closest approach requires **0.40 m/s**
to recover the same margin: **8.0× the manoeuvre-budget demand**.

In this ideal linear illustration, required delta-v scales inversely with lead time:
six hours divided by 45 minutes equals eight. The ratio is a constructed model
comparison, not measured operational performance.

This is a transparent policy counterfactual, not a flight command or safety guarantee.

## Why Parliament should care

- **Operational consequence:** delayed warning reduces the usefulness of small corrective manoeuvres.
- **Public-service dependency:** Earth-observation services can support environmental monitoring and emergency response.
- **Policy implication:** tracking coverage, warning latency, data exchange and auditable operator response are resilience investments.

Parliament should scrutinise capability and outcomes. NSpOC provides warning and
operational support; any operational assessment and spacecraft manoeuvre remains subject
to the authorised operator's validated process and decision authority.

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

- All asset, debris, alert and service identifiers are fictional.
- Constant relative velocity in a two-dimensional local encounter plane.
- Instantaneous ideal cross-track impulse with no execution uncertainty.
- The 1 km separation buffer is illustrative, not an NSpOC or operator threshold.
- No covariance or collision-probability calculation is performed.
- No post-manoeuvre secondary-conjunction screening is performed.
- Delta-v is a manoeuvre-resource proxy, not a fuel, cost or mission-life estimate.

Reproducibility fingerprint: `9b42ef6dcb542e78b025ee0bcbca36f1bbb5ee8eb3e58afb44f46b8e9a33a34b`
