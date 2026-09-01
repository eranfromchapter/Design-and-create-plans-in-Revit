"""Transcript normalization: PII scrub first (SI-11), then strip timestamps and
filler, then a CONSERVATIVE utterance filter — a line is dropped only when it is
recognizably pure chitchat AND carries no digits and no renovation vocabulary.
When unsure, keep: recall of requirements beats prompt brevity."""

from __future__ import annotations

import re
from dataclasses import dataclass

from brief_extractor.pii import ScrubResult, scrub_pii

# "[00:12:34]", "(10:32 AM)", "10:32:15 -", "00:12 |"
TIMESTAMP_RE = re.compile(
    r"^\s*(?:\[\d{1,2}:\d{2}(?::\d{2})?\]|\(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?\)|"
    r"\d{1,2}:\d{2}(?::\d{2})?\s*[-|])\s*",
    re.IGNORECASE,
)
FILLER_RE = re.compile(r"\b(?:um+|uh+|erm?|hmm+)\b[,.]?\s*", re.IGNORECASE)

CHITCHAT_RE = re.compile(
    r"^(?:(?:[A-Z][A-Z ]{1,20}:)?\s*)"
    r"(?:hi|hello|hey|good (?:morning|afternoon|evening)|how are you|i'?m (?:good|great|fine)"
    r"|thanks?(?: you| so much)?|sounds good|bye|goodbye|see you|take care|no problem"
    r"|you'?re welcome|nice to meet you|great to see you)"
    r"[\s!,.?]*$",
    re.IGNORECASE,
)
DOMAIN_HINT_RE = re.compile(
    r"\d|kitchen|bath|bedroom|bed\b|living|dining|laundry|closet|office|wall|floor|ceiling"
    r"|door|window|budget|style|finish|tile|counter|island|open|adjacent|keep|remove|move"
    r"|renovat|apartment|room|storage|light|modern|traditional|prewar|accessib",
    re.IGNORECASE,
)


@dataclass
class NormalizedTranscript:
    text: str
    dropped_lines: int
    scrub: ScrubResult


def normalize_transcript(raw: str, client_names: list[str] | None = None) -> NormalizedTranscript:
    scrub = scrub_pii(raw, client_names)
    kept: list[str] = []
    dropped = 0
    for line in scrub.text.splitlines():
        line = TIMESTAMP_RE.sub("", line)
        line = FILLER_RE.sub("", line)
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line:
            continue
        if CHITCHAT_RE.match(line) and not DOMAIN_HINT_RE.search(line):
            dropped += 1
            continue
        kept.append(line)
    return NormalizedTranscript(text="\n".join(kept), dropped_lines=dropped, scrub=scrub)
