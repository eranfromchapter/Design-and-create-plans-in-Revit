"""PII scrub (SI-11): redact names/emails/addresses/phone numbers BEFORE any LLM
boundary and before any fixture recording. Deterministic: the same input yields
the same tokens, first-occurrence numbering, same-value -> same-token.

Names: matched from the caller-supplied client_names list (the project knows who
its clients are) plus honorific patterns — no NER in v1; the scrub is judged by
the seeded-PII acceptance test, not by open-world recall."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# US phone shapes: separators or parens required (so plain quantities like
# "2700" or "3 bedroom" never match), plus bare 10-digit runs.
PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}\b|\b\d{10}\b")

# "245 West 98th Street, Apt 12B" / "12 Main St" / "1 Riverside Blvd Unit 4".
STREET_SUFFIX = (
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Place|Pl|"
    r"Court|Ct|Terrace|Ter|Parkway|Pkwy|Broadway|Way)"
)
ADDRESS_RE = re.compile(
    r"\b\d{1,5}\s+(?:(?:[A-Z][A-Za-z0-9]*|\d+(?:st|nd|rd|th))\.?\s+){0,3}"
    + STREET_SUFFIX
    + r"\.?(?:,?\s*(?:Apt|Apartment|Unit|Suite|#)\.?\s*[A-Za-z0-9-]+)?",
)

HONORIFIC_NAME_RE = re.compile(r"\b(?:Mr|Mrs|Ms|Mx|Dr)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?")


@dataclass
class ScrubResult:
    text: str
    # category -> number of DISTINCT values redacted (never the values themselves)
    counts: dict[str, int] = field(default_factory=dict)


def scrub_pii(text: str, client_names: list[str] | None = None) -> ScrubResult:
    counts: dict[str, int] = {}
    tokens: dict[str, str] = {}  # matched value -> token

    def redact(category: str, pattern: re.Pattern[str], text: str, flags_ci: bool) -> str:
        def replace(m: re.Match[str]) -> str:
            key = m.group(0).lower() if flags_ci else m.group(0)
            if key not in tokens:
                counts[category] = counts.get(category, 0) + 1
                tokens[key] = f"[{category.upper()}_{counts[category]}]"
            return tokens[key]

        return pattern.sub(replace, text)

    # order matters: emails first (an email contains no phone/address), then
    # phones, then addresses (their digits must still be present), then names
    text = redact("email", EMAIL_RE, text, flags_ci=True)
    text = redact("phone", PHONE_RE, text, flags_ci=False)
    text = redact("address", ADDRESS_RE, text, flags_ci=False)
    for name in sorted(client_names or [], key=len, reverse=True):
        if not name.strip():
            continue
        pattern = re.compile(r"\b" + re.escape(name.strip()) + r"\b", re.IGNORECASE)
        text = redact("name", pattern, text, flags_ci=True)
    text = redact("name", HONORIFIC_NAME_RE, text, flags_ci=False)
    return ScrubResult(text=text, counts=counts)
