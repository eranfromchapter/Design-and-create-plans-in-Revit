# DXF input profile v1 (Lane A)

**Status: documented assumption.** Polycam states that its floor-plan DXF export
keeps walls, doors, windows and room labels "as separate layers", but publishes
nothing about entity types, width encoding, or units. This profile pins what the
converter accepts; the Phase 2 gate includes a calibration item
(docs/MANUAL_REVIT_TEST.md) to diff the first real export against it and open a
profile-v2 item if it differs. Constants live in `src/scan_converter/profile.py`.

## Accepted encoding

| Element | Layer (case-insensitive synonyms) | Entity | Semantics |
| --- | --- | --- | --- |
| Wall | `WALLS`, `WALL`, `A-WALL` | LWPOLYLINE / POLYLINE with `const_width > 0` | Vertices trace the wall **centerline**; `const_width` = thickness; bulges allowed (tessellated at max sagitta 10 mm) |
| Door | `DOORS`, `DOOR`, `A-DOOR` | LINE or 2-vertex LWPOLYLINE | Segment lies **along** the host wall centerline spanning the opening width |
| Window | `WINDOWS`, `WINDOW`, `A-GLAZ` | LINE or 2-vertex LWPOLYLINE | Same as doors |
| Room label | `ROOMS`, `ROOM`, `A-AREA` | TEXT / MTEXT | Informational only (review payload; `rooms: []` at Commit #0) |

## Units

`$INSUNITS` ∈ {1 inch, 2 ft, 4 mm, 5 cm, 6 m} is trusted. `0`/absent falls back
to the bounding-box span heuristic over WALLS entities (span bands: 3 000–30 000
→ mm, 118–1 181 → inch, 3–30 → m) and **requires unit confirmation on the review
card**. Out of every band → `unit_undetectable`. A wrong detected unit is fixed
by re-uploading with `unit_override` — geometry is never rescaled outside the
converter.

## Rejections (converter 422s)

- `multi_level_unsupported` — >1 elevation cluster (>100 mm apart) on wall
  entities, or any populated layer matching `(LEVEL|FLOOR|STOREY|STORY)[ _-]?N`
  with N ≥ 2. Never silently flattened (PLAN.md D1).
- `profile_violation` — walls without a positive `const_width` (e.g. LINEs on the
  wall layer), diagnostic lists the layers/entity types actually found.
- `no_walls_found`, `unit_undetectable`, `dxf_parse_error`.

## Assumed values (2D input carries none of these)

Door height 2040 mm, swing `L`; window sill 900 mm, height 1400 mm; wall height =
project ceiling default (2700 mm unless overridden), **confirmed by the human on
the review card**. All assumptions are listed verbatim in the review payload.

## Known deferral

Wall extraction by parallel-line pairing (exports that draw both wall faces
instead of a widthed centerline) is deferred to profile v2 — the
`profile_violation` diagnostics are designed to make that case obvious.
