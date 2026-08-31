"""Deterministic cross-session reconciliation (never the LLM's job): later
sessions win on conflicts, every conflict is recorded in contradictions[], and
list fields merge as first-seen-ordered unions capped at the schema's maxItems
(overflow is surfaced, never silently useful-then-gone)."""

from __future__ import annotations

from typing import Any

MAX = {
    "rooms_required": 30,
    "adjacency_rules": 40,
    "style_tags": 12,
    "keep_items": 20,
    "special_constraints": 20,
    "open_questions": 15,
    "contradictions": 20,
}


def _cap(brief: dict[str, Any], fieldname: str, diagnostics: list[str]) -> None:
    items = brief.get(fieldname)
    if items is not None and len(items) > MAX[fieldname]:
        diagnostics.append(f"{fieldname}: {len(items) - MAX[fieldname]} entries over cap dropped")
        brief[fieldname] = items[: MAX[fieldname]]


def reconcile(
    earlier: dict[str, Any],
    later: dict[str, Any],
    contradictions: list[dict[str, str]],
    diagnostics: list[str],
) -> dict[str, Any]:
    """Merge one later extraction onto the earlier accumulated brief fields.
    Both inputs are extraction-shaped dicts (no meta/contradictions)."""
    merged: dict[str, Any] = {}

    # rooms_required: keyed by program; a differing count is THE contradiction case
    rooms: dict[str, dict[str, Any]] = {
        r["program"]: dict(r) for r in earlier.get("rooms_required", [])
    }
    for room in later.get("rooms_required", []):
        program = room["program"]
        if program in rooms and rooms[program]["count"] != room["count"]:
            contradictions.append(
                {
                    "field": f"rooms_required.{program}",
                    "earlier": f"count={rooms[program]['count']}",
                    "later": f"count={room['count']}",
                    "resolution": "latest_wins",
                }
            )
        rooms[program] = dict(room)
    merged["rooms_required"] = list(rooms.values())

    # adjacency_rules: keyed by the unordered room pair; a changed relation conflicts
    def pair(rule: dict[str, Any]) -> tuple[str, str]:
        return tuple(sorted((rule["a"].lower(), rule["b"].lower())))  # type: ignore[return-value]

    rules: dict[tuple[str, str], dict[str, Any]] = {
        pair(r): dict(r) for r in earlier.get("adjacency_rules", [])
    }
    for rule in later.get("adjacency_rules", []):
        key = pair(rule)
        if key in rules and rules[key]["relation"] != rule["relation"]:
            contradictions.append(
                {
                    "field": f"adjacency_rules.{key[0]}~{key[1]}",
                    "earlier": rules[key]["relation"],
                    "later": rule["relation"],
                    "resolution": "latest_wins",
                }
            )
        rules[key] = dict(rule)
    merged["adjacency_rules"] = list(rules.values())

    # scalar: finish_tier — later wins, difference recorded
    early_tier = earlier.get("finish_tier")
    late_tier = later.get("finish_tier")
    if early_tier and late_tier and early_tier != late_tier:
        contradictions.append(
            {
                "field": "finish_tier",
                "earlier": early_tier,
                "later": late_tier,
                "resolution": "latest_wins",
            }
        )
    tier = late_tier or early_tier
    if tier is not None:
        merged["finish_tier"] = tier

    # ordered unions
    for fieldname in ("style_tags", "keep_items", "open_questions"):
        seen: list[Any] = []
        for value in [*earlier.get(fieldname, []), *later.get(fieldname, [])]:
            if value not in seen:
                seen.append(value)
        if seen or fieldname == "style_tags":
            merged[fieldname] = seen

    constraints: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    for constraint in [
        *earlier.get("special_constraints", []),
        *later.get("special_constraints", []),
    ]:
        if constraint["text"] not in seen_texts:
            seen_texts.add(constraint["text"])
            constraints.append(dict(constraint))
    if constraints:
        merged["special_constraints"] = constraints

    for fieldname in MAX:
        if fieldname in merged:
            _cap(merged, fieldname, diagnostics)
    return merged
