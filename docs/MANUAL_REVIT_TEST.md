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
Runner for a Claude session on the workstation: `docs/REVIT_SPIKE.md` — stage 1 (the API
conventions through the AUTOM8LABS bridge) is DONE 2026-09-03, results in
`docs/REVIT_SPIKE_RESULTS.md`; stage 2 (the add-in itself) is OPEN. Stage-1 outcomes per row:
- [ ] One `create_pipe` envelope (two segments + one 90° elbow) executes; tee case emits REVIEW.
      Stage 1: straight pipes OK at Ø76 (`Sanitary` system exists; no PVC type, `Default` steel
      used); the elbow FAILED because the template has no pipe elbow family → the plugin now
      preflights the type's routing preferences (`routing_preference_missing`) and surfaces
      Revit's refusal as `fitting_insert_failed`. Re-test once an elbow family is loaded
      (stage 2 prerequisite 3).
- [ ] One `create_door` + `place_device` envelope: door lands at offset-centerline convention;
      receptacle is face-hosted at 380 mm AFF on the ROOM-side face named by `args.face`
      (left = +90° CCW of start→end); record any wall whose `face` the executor got wrong.
      Stage 1: exterior face = LEFT of start→end CONFIRMED live (both draw directions); hosting
      untestable through the connector (it placed face-based families unhosted at z = 0) → the
      plugin now fails `unhosted` unless `Host` is the wall and `HostFace` is set. Needs the
      add-in + a face-based fixture family (stage 2).
- [ ] `create_door` `swing` L|R + `flip_facing`: leaf sweeps LEFT of start→end when
      `flip_facing` is falsy (Phase 5 swing.py convention); hinge at the plan's jamb.
      Stage 1: BLOCKED (no door family, no hosted placement, no flip tools). The plugin no longer
      maps onto HandFlipped/FacingFlipped: it compares the placed door's HandOrientation /
      FacingOrientation with the plan's directions and flips on disagreement, assuming the
      Door.rft convention (hinge at family −X, swing to family +Y). Verify with Chapter's real
      door family — a different family convention fails `door_flip_failed`.
- [ ] Template prerequisite: routing preferences loaded (runbook); missing-fitting failure mode
      recorded. Stage 1: RECORDED — pipe type `Default` carries Coupling / Tee / Transition but
      no elbow; conduit type `Conduit with Fittings : Conduit` (EMT) carries all five fittings
      and its auto-elbow works. Content list: `docs/REVIT_SPIKE.md` stage 2 prerequisites.
- [ ] Sizes bind to the type's table: Ø76 → 76.2 (3"), Ø51 → 50.8 (2"), conduit 21 → 19.05
      (¾" EMT); a request with no table nominal within 2.5 mm fails `unknown_size`. Stage 1
      showed literal values never bind (OD = ID = 76.0; 21 mm displayed as 7/8").
- [ ] Interference law: touching-but-not-overlapping elements are NOT reported (strict overlap).
      Stage 1: CONFIRMED — an end-to-end touching pipe was not flagged; a true crossing and an
      unmitred corner were.

## Phase 6 gate (MEP + Commit #2)
Prerequisite: the enrollment catalog directory `%AppData%\ChapterHub\catalogs\` holds
`mep_types.json` and `clash_prisms.json` copied from `packages/contracts/catalogs/` (and, as of
Phase 7, `param_allowlist.json` from `packages/contracts/ops/`; the add-in fails MEP ops with
`catalog_missing` otherwise) — with the REAL template names, not
the `_PLACEHOLDER` rows — and the template content listed under `docs/REVIT_SPIKE.md` stage 2
prerequisites (door family per the Door.rft convention, one face-based fixture family per device
kind, a PVC DWV pipe type whose routing preferences carry an elbow, trade-size diameters).
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

## Phase 7 gate (export → render review → finish selection → Commit #3)
Prerequisites: the Phase 6 gate rows above; `docs/REVIT_TEMPLATE_CONTENT.md` done — in particular
§5: the five `CHPT_*` shared parameters bound per `ops/param_allowlist.json` categories (the
executor fails `unknown_param` otherwise); `param_allowlist.json` enrolled beside the MEP
catalogs; the gateway reachable over HTTPS on the same host as the WSS (the add-in PUTs blobs to
`https://<gateway>/projects/<id>/blobs/<sha256>` under its workstation token); the aidm-bridge
running with `AIDM_ENDPOINT` empty (mock renderer) unless the real AIDM is configured (gate
question G2).
- [ ] `POST /projects/:id/render-views` on the post-Commit-#2 model: the export envelope commits
      (`seq` +1, empty id-map delta), three PNGs appear in the gateway blob dir whose file name ==
      `sha256(bytes)` == the `blob_ref` in three `export_ready` frames arriving AFTER
      `commit_result committed`, in views order (plan, section, 3d_hidden); no temporary view is
      left in the Project Browser; `/state.render` shows `exported` with 3 refs. Record each PNG's
      pixel width (expect 2048 — Revit fits horizontally; the height differs from the sim's).
- [ ] Gateway unreachable over HTTPS (block the port) → the export envelope rolls back
      `blob_upload_failed`, no frames, temporary views gone, `/state.render.status = failed`.
- [ ] `compose-render` → the `render_review` card shows the three source views, the Canny + line
      maps and the (mock) renders through the blob URLs; the prompt block carries the layout's
      `style_tags` verbatim as DATA; SKU candidates per surface (PLACEHOLDER badges until the real
      catalog lands). Approve.
- [ ] `POST /projects/:id/finish-selection` with a real selection (real SKUs, or placeholders with
      `ALLOW_PLACEHOLDER_SKUS=1 CI=true` on a dev-only gateway) → `finish_commit` card lists the
      selection and the `set_parameter` ops; approve → `issue-finish` → `Commit #3 finishes`
      commits (`seq` +1, empty delta); in Revit the Properties palette of a selected wall shows
      `CHPT_Product_SKU`, `CHPT_Spec_Section`, `CHPT_Finish_Material`, `CHPT_Render_Ref`; a door shows
      SKU + Spec only; a conflict wall (two rooms, two SKUs) shows the `Comments` note and no finish
      params. `/state.finish_done = true`; a second `issue-finish` → `finish_already_done`.
- [ ] Negative: hand-craft an envelope (`POST /envelopes` with the approved review's `approval_ref`
      but an added `set_parameter Mark`) → 422 `param_not_allowlisted`, nothing sent; a
      `CHPT_Finish_Material` on a door in a directly-created review → refused by the gateway; with
      the gateway check bypassed (dev build), the add-in itself rolls back `param_not_allowlisted`
      (category) and revit-sim agrees — three enforcers, one file.
- [ ] Unbind `CHPT_Render_Ref` from Walls in a throwaway copy → the finish envelope rolls back
      `unknown_param` naming the parameter; rebind → commits. `/state.finish` shows the hard failure
      card once; a NEW selection restarts.
- [ ] Ctrl+Z after Commit #3 → `state_divergence`; project dirty; `issue-finish` refused
      (`drift_review_pending`).

## Per release
- [ ] Re-run the Phase 1 gate list plus any op handlers added in the release.
