"""Read-only access to packages/contracts (the single source of truth): the products
catalog, the set_parameter allowlist, the op registry and the plumbing table. Every
accessor is cached; nothing here reads the environment or the clock."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "packages" / "contracts"


@cache
def _load(relative: str) -> dict[str, Any]:
    return json.loads((CONTRACTS_DIR / relative).read_text())


@cache
def products() -> dict[str, Any]:
    return _load("catalogs/products.json")


@cache
def catalog_version() -> str:
    return str(products()["catalog_version"])


@cache
def sku_index() -> dict[str, dict[str, Any]]:
    return {row["sku"]: row for row in products()["skus"]}


@cache
def param_allowlist() -> dict[str, dict[str, Any]]:
    """{param name: {name, kind, categories}} from ops/param_allowlist.json (SI-4)."""
    return {p["name"]: p for p in _load("ops/param_allowlist.json")["params"]}


@cache
def set_parameter_schema() -> dict[str, Any]:
    return _load("ops/registry.json")["ops"]["set_parameter"]["args_schema"]


@cache
def op_registry_names() -> tuple[str, ...]:
    return tuple(sorted(_load("ops/registry.json")["ops"]))


@cache
def plumbing_fixtures() -> dict[str, dict[str, Any]]:
    """kind -> {fixture_units, drain_diameter_mm, hookups} (catalogs/plumbing.json)."""
    return _load("catalogs/plumbing.json")["fixtures"]
