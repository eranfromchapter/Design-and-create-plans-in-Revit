# Live-Revit verification checklist

Human-executed on the design workstation. Required at the Phase 1, Phase 2, and pre-Phase-6
gates (PLAN.md Part E — amendment delivery-2), then per release. Record date, Revit version,
plugin version, and outcome for each run.

## Phase 1 gate (after the spine is green in CI)
- [ ] Install the plugin per the enrollment procedure; `hello` reaches the gateway with
      `last_committed_seq=0` and an id-map hash.
- [ ] Run the 4-wall golden envelope live: 4 walls appear; `commit_result: committed` with 4
      id-map entries; walls land at the exact mm coordinates (spot-check two with the tape tool).
- [ ] Tampered-signature envelope → `ack rejected {bad_signature}`, nothing in the model.
- [ ] Envelope for a different `workstation_id` → rejected.
- [ ] With a family document active (wrong document), envelope → rejected `{wrong_document}`.
- [ ] Ctrl+Z after the commit → plugin sends `state_divergence`; gateway marks project dirty.

## Phase 2 gate
- [ ] **DXF profile calibration**: open the first real Polycam export and record its layer
      names, entity types, and wall-width encoding against
      `services/scan-converter/PROFILE.md` (that profile is a documented assumption —
      `uv run python -m scan_converter <file.dxf> --review` surfaces `profile_violation`
      diagnostics). If it differs, open a profile-v2 item before going further.
- [ ] Real Polycam DXF of a real unit → review card → approve (confirm ceiling height,
      confirm unit if demanded) → `issue-commit0` → Commit #0 on a throwaway model with the
      REAL as-built catalog names (placeholders will not resolve on the live template).
- [ ] Deliberately mis-scaled DXF (unitless header) → review card demands unit confirmation;
      confirming a wrong unit is refused (`unit_mismatch`) — reject + re-upload with
      `unit_override`.
- [ ] After Commit #0: manual wall edit in Revit → `state_divergence` → project dirty; scan
      re-upload refused (`commit0_already_done`).

## Pre-Phase-6 spike (before the MEP agent is built)
Runner for a Claude Code session on the workstation: `docs/REVIT_SPIKE.md` (stage 1 answers the
convention rows below through the AUTOM8LABS MCP bridge; stage 2 is the add-in itself).
- [ ] One `create_pipe` envelope (two segments + one 90° elbow) executes; tee case emits REVIEW.
- [ ] One `create_door` + `place_device` envelope: door lands at offset-centerline convention;
      receptacle is face-hosted at 380 mm AFF on the ROOM-side face named by `args.face`
      (left = +90° CCW of start→end); record any wall whose `face` the executor got wrong.
- [ ] `create_door` `swing` L|R + `flip_facing`: leaf sweeps LEFT of start→end when
      `flip_facing` is falsy (Phase 5 swing.py convention); confirm or invert the
      `flipHand()`/`flipFacing()` mapping in `CreateDoorHandler`.
- [ ] Template prerequisite: routing preferences loaded (runbook); missing-fitting failure mode
      recorded.

## Phase 6 gate (MEP + Commit #2)
Prerequisite: the enrollment catalog directory `%AppData%\ChapterHub\catalogs\` holds
`mep_types.json` and `clash_prisms.json` copied from `packages/contracts/catalogs/` (the
add-in fails MEP ops with `catalog_missing` otherwise) — with the REAL template names, not
the `_PLACEHOLDER` rows.
- [ ] Pre-Phase-6 spike rows ticked (create_pipe two segments + elbow; create_door +
      place_device face-hosted 380 AFF; routing preferences loaded); walls needing `face`
      corrections recorded.
- [ ] Golden Commit #2 envelope (`fixtures/goldens/phase6_2br_mep.json` ops after the
      Phase 5 interior ops) on the post-Commit-#1 model: 18 families at mm centres/rotations,
      2 stacks + branch tree with slopes (`HUB P-00x` groups), 45 devices at 380/1150/1220
      AFF on the named faces, raceway tree at 2600 with drops; `commit_result committed`;
      id-map grows by the op count (one logical id per op; extra segments/fittings grouped).
- [ ] Wye/tee fittings completed manually per `wye_manual` / `conduit_fittings_manual`
      review items; time recorded; template routing-preference gaps noted.
- [ ] Interference: model a short PIPE by hand (any system) crossing where a conduit drop
      of the golden envelope will run (furniture and devices are EXEMPT from conduits by the
      shared table, so use a pipe or a structural column), re-issue → `commit_result
      rolled_back {interference "A~B", op_index}` followed by `clash_delta` with logical ids
      (`revit:<ElementId>` for the hand-modelled element); TransactionGroup rolled back (no
      partial MEP); the gateway's `commit2` state shows the pair; `merge-commit2` produces
      the iteration k+1 card; the re-planned envelope commits under a fresh seq.
- [ ] Fire-rated wall in the template → conduit route detours (compare
      `home_runs[].penetrations` against the card).
- [ ] Ctrl+Z after Commit #2 → `state_divergence`.

## Per release
- [ ] Re-run the Phase 1 gate list plus any op handlers added in the release.
