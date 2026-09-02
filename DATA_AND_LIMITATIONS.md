# Data, provenance and limitations

## Scenario data

`scenarios/uk_eo_demo_1.json` is wholly synthetic. Its asset, debris object, alert,
service role and manoeuvres are fictional and exist solely to make a deterministic policy
counterfactual reproducible.

Every generated record includes:

- scenario ID;
- `synthetic: true`;
- `operational_use: false`;
- model version and seed;
- assumptions;
- human-operator approval gate;
- SHA-256 of the scenario file.

## Public evidence snapshot

The interface embeds only dated public aggregate facts:

1. [NSpOC, *How we protected the UK and space in July 2026*, published 20 August 2026](https://www.gov.uk/government/news/how-we-protected-the-uk-and-space-in-july-2026)
2. [UK Space Agency Annual Report 2025–26, published 14 July 2026](https://www.gov.uk/government/publications/uk-space-agency-annual-report-and-accounts-2025-2026/uk-space-agency-annual-report-2025-2026)
3. [UK Parliament, Space Resilience inquiry launch, 16 July 2026](https://committees.parliament.uk/committee/111/national-security-strategy-joint-committee/news/217022/security-in-space-committee-launches-new-inquiry-on-space-resilience/)
4. [Royal Air Force, UK Space Command](https://www.raf.mod.uk/what-we-do/uk-space-command/)

NSpOC states that public catalogue figures may be adjusted as tracking is refined. The
application therefore presents publication dates and does not label the snapshot “live.”

## Restricted services

[Monitor Space Hazards](https://www.monitor-space-hazards.service.gov.uk/) operational
conjunction services are available to eligible UK-licensed operators and UK government
departments. UK Orbit Guard has no connection to, credentials for, or data from that service.

## Why public TLEs are not used for the conjunction claim

Space-Track documentation warns against using public TLE data for conjunction-assessment
prediction. A credible operational assessment requires precise ephemerides, covariance,
object geometry, validated propagation and operator procedures. A fictional, transparent
fixture is more honest for this hackathon than manufacturing a “live collision” from public
catalogue elements.

- [Space-Track documentation](https://www.space-track.org/documentation)
- [NASA CARA: conjunction-event prediction](https://www.nasa.gov/cara/step-1-conjunction-event-prediction/)
- [NASA CARA: close-approach risk assessment](https://www.nasa.gov/cara/step-2-close-approach-risk-assessment/)
- [ESA: re-entry and collision avoidance](https://www.esa.int/content/view/full/413425)

## Model exclusions

- covariance and collision-probability calculation;
- full orbit determination or propagation;
- SGP4/TLE conjunction screening;
- atmospheric drag, oblateness and space weather;
- thruster, attitude, communications and execution constraints;
- second-order effects and secondary conjunctions;
- operator coordination and multi-asset scheduling;
- fuel, financial and mission-life conversion.

The result is an educational policy simulator, not a flight-safety product.
