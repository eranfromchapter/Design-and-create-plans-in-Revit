# Catalogs

Controlled vocabularies joined against contract documents. **Three of these files carry
placeholder entries that MUST be replaced with human-supplied values before the phases that
consume them** (Part J: never invent catalog vocabulary; placeholders are marked and never shipped).

| file | consumed by | status |
|---|---|---|
| `asbuilt_types.json` | Phase 2 Lane A wall-type resolution (thickness → type) | **PLACEHOLDER — ask Eran** for the as-built wall type names + thicknesses from Chapter's Revit template |
| `new_construction_types.json` | Phase 4 layout-compiler closed vocabulary; validator + sim enforce membership for `source="generated"` elements | **PLACEHOLDER — ask Eran** for the wall/door/window type vocabulary from Chapter's template |
| `products.json` | Phase 7 finish selection (per-room / per-element SKUs filtered by the brief's `finish_tier`; the render is illustrative, the selection is the data), Phase 8 spec compiler (Division 09) | **PLACEHOLDER — ask Eran** for the 30 real Chapter SKUs (critical path for Phase 8). 14 `_PLACEHOLDER` rows exist only for Phase 7 fixtures/e2e and are refused by the validator outside CI. Fields `sku, manufacturer, model, description, finish_tier, csi_section, unit`; the surface class (wall / casework / door / plumbing_fixture) is DERIVED from `csi_section` by the bridge's CSI table (`09 91/93/30/72/29` → wall, `06 41` / `12 35` → casework, `08 14/11/16` → door, `22 41/42` → plumbing fixture) — nothing is invented per SKU |
| `plumbing.json` | Phase 6 MEP rules P-1/P-3/P-4 (fixture units, drain sizes, fitting allowances) | Engineering defaults (IPC-derived); reviewable, not placeholders |
| `mep_types.json` | Phase 6 MEP op emission (`create_pipe.pipe_type` + `system`), sim catalog membership (pipe types), plugin symbol lookup (PipingSystemType names, the conduit type, the device family per `place_device.kind` — the registry ops carry no conduit type or device family) | **PLACEHOLDER — ask Eran** for pipe/conduit types, PipingSystemType names and device families from Chapter's template |
| `clash_prisms.json` | Phase 6 clash law shared by the merge gate (Phase A), revit-sim `run_interference_check` and the plugin: element classes/priorities, kind heights, exemption pairs | Engineering defaults; reviewable, not placeholders |

Catalog governance (Phase 8): human-owned, semver'd via `catalog_version`; a catalog version is
pinned per project at commit time so re-generated specs are reproducible.

## Notes from the live-Revit spike (stage 1, 2026-09-03 — `docs/REVIT_SPIKE_RESULTS.md`)

Observations to help fill the placeholders; none of these values is written into a catalog by us.

- `mep_types.json`: the template's piping system type is literally `Sanitary`; its conduit type is
  `Conduit with Fittings : Conduit` (standard EMT, all five `… - Aluminum : Standard` fittings).
  No PVC pipe type and no pipe elbow family exist yet — `pipe_types.sanitary` must name a type
  whose routing preferences carry an elbow (e.g. `Elbow - Generic`) or every bend fails
  `routing_preference_missing`. `device_families` must be FACE-based families (the plugin
  hosts on the wall face named by `place_device.face`); the template has none.
- `conduit_diameter_mm` (and the pipe diameters in `plumbing.json`) are **trade-size nominals in
  mm**: the plugin snaps to the nearest size in the type's table within 2.5 mm (76 → 76.2 = 3",
  51 → 50.8 = 2", 21 → 19.05 = ¾" EMT) and fails `unknown_size` otherwise. 21 is not itself a
  trade size; prefer the real one (19.05) when the vocabulary lands (golden re-run).
- `new_construction_types.json` door types: the plugin assumes the Door.rft authoring convention
  (leaf hinged at the family's −X jamb, swinging to family +Y = Exterior). A family authored the
  other way fails `door_flip_failed`; tell us which families hinge at +X and a per-type flag
  becomes a catalog item.

## Phase 7 notes

- `products.json` rows are consumed by `services/aidm-bridge` (candidates per surface class, filtered
  by `finish_tier`; deterministic finish-selection validation). `catalog_version` is pinned into every
  `finish_commit` review and `finish_selections` row so Phase 8 re-generates specs reproducibly.
- `ops/param_allowlist.json` (not a catalog, but enrolled beside them on the Revit machine as of
  Phase 7) names the ONLY parameters `set_parameter` may write and the categories each may touch;
  the five `CHPT_*` parameters must exist as shared parameters in Chapter's template
  (`docs/REVIT_TEMPLATE_CONTENT.md`).
