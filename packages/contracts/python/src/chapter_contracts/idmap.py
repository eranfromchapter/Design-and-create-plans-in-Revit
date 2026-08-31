"""Cross-language id-map hash (hello.id_map_hash, drift gate):

    sha256( UTF-8( JCS( [[logical_id, element_id], ...] sorted by logical_id ) ) )

Pinned by packages/contracts/fixtures/idmap/hash_cases.json in TS, Python, and C#.
"""

from __future__ import annotations

import hashlib

import rfc8785


def id_map_hash(entries: dict[str, int]) -> str:
    pairs = [[k, entries[k]] for k in sorted(entries)]
    return hashlib.sha256(rfc8785.dumps(pairs)).hexdigest()
