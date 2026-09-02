# Catalogs

Controlled vocabularies joined against contract documents. **Three of these files carry
placeholder entries that MUST be replaced with human-supplied values before the phases that
consume them** (Part J: never invent catalog vocabulary; placeholders are marked and never shipped).

| file | consumed by | status |
|---|---|---|
| `asbuilt_types.json` | Phase 2 Lane A wall-type resolution (thickness → type) | **PLACEHOLDER — ask Eran** for the as-built wall type names + thicknesses from Chapter's Revit template |
| `new_construction_types.json` | Phase 4 layout-compiler closed vocabulary; validator + sim enforce membership for `source="generated"` elements | **PLACEHOLDER — ask Eran** for the wall/door/window type vocabulary from Chapter's template |
| `products.json` | Phase 7 finish selection, Phase 8 spec compiler | **PLACEHOLDER — ask Eran** for the 30 real Chapter SKUs (critical path for Phase 8) |
| `plumbing.json` | Phase 6 MEP rules P-1/P-3/P-4 (fixture units, drain sizes, fitting allowances) | Engineering defaults (IPC-derived); reviewable, not placeholders |
| `mep_types.json` | Phase 6 MEP op emission (`create_pipe.pipe_type` + `system`), sim catalog membership (pipe types), plugin symbol lookup (PipingSystemType names, the conduit type, the device family per `place_device.kind` — the registry ops carry no conduit type or device family) | **PLACEHOLDER — ask Eran** for pipe/conduit types, PipingSystemType names and device families from Chapter's template |
| `clash_prisms.json` | Phase 6 clash law shared by the merge gate (Phase A), revit-sim `run_interference_check` and the plugin: element classes/priorities, kind heights, exemption pairs | Engineering defaults; reviewable, not placeholders |

Catalog governance (Phase 8): human-owned, semver'd via `catalog_version`; a catalog version is
pinned per project at commit time so re-generated specs are reproducible.
