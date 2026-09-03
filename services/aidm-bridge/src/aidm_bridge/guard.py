"""Injection guard (SI-7): a style tag that carries op-registry vocabulary or an
envelope-shaped fragment is DATA that looks like instructions — it is dropped before
it can reach the prompt. Deliberate twin of brief_extractor/guard.py (services are
independent venvs; sharing it would be a contracts-package change)."""

from __future__ import annotations

import re
from functools import cache

from aidm_bridge.catalogs import op_registry_names

_ENVELOPE_SHAPE_RE = re.compile(r'"(?:op|ops|args|envelope_id|payload|sig)"\s*:')


@cache
def _op_name_re() -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(map(re.escape, op_registry_names())) + r")\b")


def is_suspicious(text: str) -> bool:
    return bool(_op_name_re().search(text) or _ENVELOPE_SHAPE_RE.search(text))
