"""Dated public evidence used by the demo; there are no live feeds."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceCard:
    title: str
    value: str
    detail: str
    source_label: str
    source_url: str
    source_date: str


PUBLIC_EVIDENCE: tuple[EvidenceCard, ...] = (
    EvidenceCard(
        title="Latest public monthly count",
        value="1,209",
        detail="Collision risks to UK-licensed satellites reported for July 2026.",
        source_label="National Space Operations Centre",
        source_url="https://www.gov.uk/government/news/how-we-protected-the-uk-and-space-in-july-2026",
        source_date="20 August 2026",
    ),
    EvidenceCard(
        title="Published monthly average",
        value="1,913",
        detail="Average collision warnings issued each month to UK operators in 2025–26.",
        source_label="UK Space Agency Annual Report 2025–26",
        source_url="https://www.gov.uk/government/publications/uk-space-agency-annual-report-and-accounts-2025-2026/uk-space-agency-annual-report-2025-2026",
        source_date="14 July 2026",
    ),
    EvidenceCard(
        title="Objects in the public catalogue",
        value="34,751",
        detail="Resident space objects reported for July 2026; the figure can be revised.",
        source_label="National Space Operations Centre",
        source_url="https://www.gov.uk/government/news/how-we-protected-the-uk-and-space-in-july-2026",
        source_date="20 August 2026",
    ),
    EvidenceCard(
        title="Current parliamentary scrutiny",
        value="2026 inquiry",
        detail="The Joint Committee on the National Security Strategy opened a space-resilience inquiry.",
        source_label="UK Parliament",
        source_url="https://committees.parliament.uk/committee/111/national-security-strategy-joint-committee/news/217022/security-in-space-committee-launches-new-inquiry-on-space-resilience/",
        source_date="16 July 2026",
    ),
    EvidenceCard(
        title="Civil–defence operating model",
        value="Joint NSpOC",
        detail="NSpOC combines civil and military space-domain awareness under UK Space Command and UKSA leadership.",
        source_label="Royal Air Force — UK Space Command",
        source_url="https://www.raf.mod.uk/what-we-do/uk-space-command/",
        source_date="accessed 2 September 2026",
    ),
)


MONTHLY_COLLISION_RISKS: tuple[tuple[str, int], ...] = (
    ("Aug 2025", 971),
    ("Sep 2025", 1_537),
    ("Oct 2025", 2_402),
    ("Nov 2025", 2_472),
    ("Dec 2025", 2_643),
    ("Jan 2026", 2_608),
    ("Feb 2026", 2_117),
    ("Mar 2026", 1_847),
    ("Apr 2026", 1_194),
    ("May 2026", 1_285),
    ("Jun 2026", 1_436),
    ("Jul 2026", 1_209),
)

MONTHLY_COLLISION_RISKS_URL = (
    "https://www.gov.uk/government/news/how-we-protected-the-uk-and-space-in-july-2026"
)
