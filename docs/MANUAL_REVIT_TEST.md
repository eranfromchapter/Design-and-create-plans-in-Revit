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
- [ ] Real Polycam DXF of a real unit → review card → approve → Commit #0 on a throwaway model.
- [ ] Deliberately mis-scaled DXF (unitless header) → review card demands unit confirmation.

## Pre-Phase-6 spike (before the MEP agent is built)
- [ ] One `create_pipe` envelope (two segments + one 90° elbow) executes; tee case emits REVIEW.
- [ ] One `create_door` + `place_device` envelope: door lands at offset-centerline convention;
      receptacle is face-hosted at 380 mm AFF.
- [ ] Template prerequisite: routing preferences loaded (runbook); missing-fitting failure mode
      recorded.

## Per release
- [ ] Re-run the Phase 1 gate list plus any op handlers added in the release.
