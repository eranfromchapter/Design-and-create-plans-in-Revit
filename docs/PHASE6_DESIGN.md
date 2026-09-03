# Phase 6 design — MEP Agent + merge gate + clash recovery + Commit #2 (FINAL, synthesized)

Status: design for the implementer; stops at the Phase 6 gate. Branch `claude/phase-6-mep`, stacked on `claude/phase-5-interior` (HEAD `90c9501`).
Provenance: winning design = **testable** (determinism/testability lens); grafted from **spec-exact** (WSS serialization, confirmation validation, state-machine completeness, `revit_sim.clash` single law, `/envelopes` guard, gateway verbatim assertion, `reissue_of`) and **minimal** (spec-literal P-4 default, `preplaced`/`obstacles` placer seam, placer-recorded host wall, corridor/laundry NEC rules, branch tree, `interior_ops_verbatim` + `replan_deltas`, connected-pair exemptions). Every refutation from the six lens passes is resolved in §0. Every interpretive decision is a **PIN-nn** row in the Pinned decisions section; rows marked ⚠ deviate from the Part G letter or from prior handoff text and sit behind a named constant whose default is the letter.

Decisions taken with Eran before the build (2026-09-02): `place_device.args.face` (left|right) and
`kind: receptacle_240` ADDED to the op registry (so PIN-34's auto-detect fallback is retired — `face`
is always emitted); every rebuilt merged plan needs a fresh human approval (PIN-31); P-4 `L = along`
(PIN-08 default); the Phase 5 inside-room predicate now uses the room's inner-face polygon (Eran Q7,
fixed on PR #6 before this phase's goldens were generated).

Conventions: all coordinates and constants in mm; "blocking"/"info" are review-item severities; "REVIEW" means a review row a human must decide, never auto-approved.

---

## 0. Refutation ledger

Verdicts are the lens verdicts; the resolution column is binding. ACCEPT = the design below changes; REJECT = one-line reason; HOLDS = kept as claimed; N/A = the refuted mechanism is not in the final design.

### 0.1 Refutations of the winning design (testable)

| id | lens | finding (short) | verdict | resolution |
|---|---|---|---|---|
| T-G1 | partg | P-4 `L = leg + along` flips the golden (3 stacks) against Part G "from the P-2 projection foot" | refuted | ACCEPT — default `P4_L_INCLUDES_DRAIN_LEG = False` (spec-literal); leg is still emitted geometry with an honest z-profile; overshoot → info `branch_plenum_marginal` (§3.2); both variants in the gate note; Eran Q3 |
| T-G2 | partg | "panel/levels have no schema home" is false (`meta.levels`, `meta.electrical.panel` exist in v2.3) | refuted | ACCEPT — confirmations are stamped into `meta.levels`/`meta.electrical.panel` on the MEP/merge layout; the commit2 snapshot carries them (§2.1) |
| T-G3 | partg | DW appliance receptacle on the counter wall emitted as `receptacle` | refuted | ACCEPT — GFCI is area-based: every device on a kitchen counter wall or in bathroom/powder/laundry is `gfci` regardless of originating rule (§3.3, PIN-19) |
| T-G4 | partg | same-seq re-issue vs Phase 6 "fresh seq" | weak | ACCEPT — Commit #2 re-issues use `seq = max(lastCommitted, lastIssued)+1` (PIN-30); Phase 1–5 behaviour unchanged |
| T-G5 | partg | dedupe closed form invalid for small `outlet_spacing` | weak | ACCEPT — general fixpoint dedupe (midpoint merge) + `outlet_spacing < 610` → blocking `outlet_spacing_invalid`; hypothesis strategy S ∈ [1, 8000] (§3.3) |
| T-G6 | partg | stack exclusion zones breaking device runs is a non-spec extra | weak | ACCEPT — default `ZONES_BREAK_DEVICE_RUNS = False`; a device whose foot lies in a zone becomes `device_unroutable` (info, no conduit); flag documented ⚠ PIN-13 |
| T-G7 | partg | silent hinge-side switch fallback | weak | ACCEPT — fallback ladder latch → latch-corner adjacent wall → hinge side, each fallback emits an info item (`switch_corner_fallback`, `switch_hinge_side`) (§3.3) |
| T-G8 | partg | E-1 program filter / hallway rule not in Part G; laundry and bath 2 end with zero receptacles | weak | ACCEPT (partially) — E-1 runs in every room except closet/bathroom/powder/corridor/laundry; corridor and laundry get explicit NEC single-device PINs ⚠ (PIN-16/17); any non-closet room ending with zero receptacles → info `room_without_receptacle` |
| T-G9 | partg | counter-wall fallback derivation is non-spec; spec path untested | weak | ACCEPT — fallback kept as PIN-18 with info `counter_walls_derived`; spec path covered by a synthetic casework test; growing the Phase 4 golden with casework is Eran Q2 |
| T-G10 | partg | pipe vs structure → `blocked` instead of re-planning the lower priority | weak | ACCEPT — action `relocate_stack` (exclude the wall, re-run P-1..P-4 for that stack's fixtures, re-route affected conduits) within the shared budget; `blocked` only when no candidate wall remains (§4.4) |
| T-G11 | partg | catalog `fire_rating_hr` never reaches generated walls | weak | ACCEPT — `catalogs.wall_fire_rating_hr(wall)` = wall flag else catalog value else 0 (§2.2) |
| T-G12 | partg | interior ops no longer verbatim after furniture re-plans; not stated | weak | ACCEPT — `interior.ops_verbatim: bool` + `replan_deltas[]` in MergeResult and on the card; documented handoff amendment (§4.6); folded into Eran Q4 |
| T-G13 | partg | P-1 exclusions / tie-break / P-3 snapping are non-literal | weak | ACCEPT (as PINs) — SI-8 exclusion is an application of the existing hard rule (PIN-05); tie-breaks and snapping are spec-silent PINs (PIN-06/07) with alternatives stated; all in the Pinned table for Eran |
| T-G14 | partg | sim check ≠ Phase A (no wall prisms in sim, fixed family height) | weak | ACCEPT — ONE law: walls/doors/windows are not clash elements anywhere; per-kind heights and exemption pairs come from `catalogs/clash_prisms.json` read by Phase A, the sim and a plugin Core test; `test_phase_a_equals_sim_law` property (§4.2, §6.2) |
| T-G15 | partg | constants/budget/branch-retention claims | holds | kept; counters asserted |
| T-I1 | invariants | budget derived from the LATEST `commit2_merge` regardless of branch pair → permanent 409 after exhaustion | refuted | ACCEPT — iteration state is scoped to the **merge chain** = (interior_plan.review_id, mep_plan.review_id); a new approved `mep_plan` starts a fresh chain = the REVIEW exit (§5.0) |
| T-I2 | invariants | `commit_result`/`clash_delta` race; "rolled_back without pairs → re-issue" re-signs the clashing envelope outside the budget | refuted | ACCEPT — `commit_result.errors[].code == "interference"` is the authoritative clash signal; pairs parsed from `"A~B"` in the same transaction; `clash_delta` is supplementary; per-session WSS promise chain; per-review re-issue cap (§5.3) |
| T-I3 | invariants | content_hash proves inputs, not that returned ops ⊆ branch ops | weak | ACCEPT — gateway verifies MergeResult (op enum, ≤1000, ids ⊆ branch ids, un-actioned ops deep-equal, single trailing check) → `commit2_failure{merge_ops_unverified}` (§5.2) |
| T-I4 | invariants | no staleness check at issue-commit2 | weak | ACCEPT — 409 `merge_review_stale` unless the review's chain is the current chain; `furnish-layout`/`plan-mep` 409 while a Commit #2 envelope is in flight (§5.1) |
| T-I5 | invariants | `recordClashDelta` not project-scoped; unbounded pairs | weak | ACCEPT — project-scoped UPDATE, ≤256 pairs, id pattern, ids must appear in the review ops (§5.3) |
| T-I6 | invariants | conduit `drop` vs host wall not exempt; sim/plugin structure asymmetry | weak | ACCEPT — see T-G14; walls are never clash elements in any executor; `(furniture, device|conduit)` exempt (PIN-24) |
| T-I7 | invariants | unknown clash ids on live Revit kill recovery | weak | ACCEPT — plugin emits `revit:<ElementId>` for unmapped elements; merge treats an unknown id as priority 0 and re-plans the known lower-priority element; both unknown → `commit2_failure{clash_pair_unknown}` (§4.4, §7) |
| T-I8 | invariants | `expired`/`ack_rejected` fall through the ladder; `envelopeForReview` singular | weak | ACCEPT — all six envelope statuses handled; `latestEnvelopeForReview` by `issued_at` (§5.1) |
| T-I9 | invariants | time limit request-boundary only | weak | ACCEPT — `deadline_check` callback threaded into P-1 loop, Dijkstra relax loop, E-1..E-3 loops, Phase A sweep and re-plans; `mep/` and `merge/` stay clock-free by AST test (§3.0) |
| T-I10 | invariants | `outlet_spacing` unbounded below | weak | ACCEPT — as T-G5 |
| T-I11 | invariants | same-seq deviation unlisted | weak | ACCEPT — as T-G4 |
| T-I12 | invariants | registry prose (`sim_behavior`) and new catalogs are contract-adjacent changes | weak | ACCEPT — listed as Eran Q5 (registry prose amendment, no schema change) and Q2 (catalogs) |
| T-I13 | invariants | SI-8: conduits routed through demising walls at zero penalty | weak | ACCEPT (partially) — `is_demising` walls count as fire-rated for the 4000 penalty (PIN-22); devices may still host on them (surface boxes) |
| T-I14 | invariants | AUTO_APPROVE CI-only; failure kinds never auto | holds | kept + unit test that a blocking `mep_plan` auto-approved under CI still yields `mep_plan_ready=false` |
| T-I15 | invariants | approval binding, rollback consistency, inject_clash unreachable, no new op | holds | kept |
| T-B1 | buildable | golden bed F-008 sits 46 mm inside W-018 → device/drop vs furniture clashes in Phase A and sim | refuted | ACCEPT — `(furniture, device)` and `(furniture, conduit)` are exempt everywhere (in-wall electrical never clashes with room furniture; NEC wall space is furniture-agnostic) PIN-24; Phase 5 placer intrusion is Eran Q7 |
| T-B2 | buildable | `legalize_furniture` never reads `layout.furniture` → single-item re-legalization is predicate-vacuous | refuted | ACCEPT — keyword-only `preplaced=()`/`obstacles=()` seam seeds `ctx.placed`/`all_aabbs` (defaults keep Phase 5 bytes); oracle failure → `drop` in the same round (§4.4) |
| T-B3 | buildable | exemption table incomplete (drop/wall, furniture/wall) | refuted | ACCEPT — as T-G14/T-B1 |
| T-B4 | buildable | same-seq | weak | ACCEPT — as T-G4 |
| T-B5 | buildable | 3-stack golden hinges on the unapproved L PIN | weak | ACCEPT — as T-G1; goldens generated under the default; alternative table pinned in `phase6_2br_gate_note.json` |
| T-B6 | buildable | `room_without_switch` misses R-005 | refuted | ACCEPT — all review-item counts come from the generator; corner fallback (§3.3) likely places D-013's switch on W-019 |
| T-B7 | buildable | GFCI lands behind the range | weak | ACCEPT — counter runs subtract range/oven/refrigerator along-wall extents (§3.3) |
| T-B8 | buildable | "ten walls at 4.0" is nine | refuted | ACCEPT — `p1_ranking` emitted by the generator; no hand counts survive in this document except as "≈" predictions |
| T-B9 | buildable | e2e asserts `mep_review_items_open` before the plan is approved (unreachable) | weak | ACCEPT — e2e approves the blocking plan first; ladder order documented |
| T-B10 | buildable | `commit2_rolled_back_no_clash {errors}` needs an errors column | weak | ACCEPT — migration 0005 adds `envelopes.errors jsonb` (§2.3) |
| T-B11 | buildable | P-1 iteration assert can fire legitimately | weak | ACCEPT — blocking `p1_iterations_exceeded` review item; the counter is diagnostics (§3.2) |
| T-B12–15 | buildable | recovery e2e reachable; goldens 1–5 stable; seams exist; golden arithmetic | holds | kept (arithmetic re-derived below under the new defaults, marked ≈) |

### 0.2 Refutations of spec-exact and minimal that bind the final design

| id | finding (short) | resolution |
|---|---|---|
| S-G1 / S-B1 / M-B6 | `place_device` has no face; both executors host on face_left → ~12 golden devices outside the building or in the wrong room | ACCEPT — Eran Q1 is a **pre-build gate ask** tied to the mandated live spike; `ops.py` emits `face` iff the registry `args_schema` has it (auto-detected), else info `device_face_unavailable` per right-face device; the gate note lists those ids; the sim renders wherever the executor law puts the device (honest SVG) |
| S-G2 / S-I1 / M-G2 / M-I8 | plugin `RunInterferenceCheck` against the whole model with only connector exemptions → every live Commit #2 rolls back | ACCEPT — created-set scope, structure categories excluded, shared exemption pairs by category, connector-joined and same-logical-id pairs excluded, `doc.Regenerate()` before filtering (§7) |
| S-G3 / M-G11 | P-4 as whole-wall exclusion / `used_walls` (spec: second stack, residual re-run) | ACCEPT — prune loop keeps the first stack; residual re-runs P-1 over all candidates incl. the same wall; no `used_walls` |
| S-G4 / S-B14 (Q2) | "furniture never re-plans" inverts the priority table | N/A — final follows the table (furniture 5 re-plans via `legalize_furniture(preplaced, obstacles)`) |
| S-G5 / S-B3 | `resolveDatum` NaN under AUTO_APPROVE | ACCEPT — `ceiling_z` = commit0 snapshot wall height (uniform by construction), never `decision_payload` (§2.2) |
| S-G6 | E-4 exclusion interval follows no rule | N/A — final uses the ±300 square per stack on the wall's centerline edges |
| S-G8 | riser bias unexercised | ACCEPT — `test_p1_riser_bias_decides_tie` (two walls tie on ΣFU; riser distance decides) |
| S-G9 | Phase A pinned to AABB contrary to D1 | ACCEPT — Phase A uses oriented polygons (D1); the sim law is the AABB superset; property `oriented_pairs ⊆ aabb_pairs` |
| S-G10 / S-I9 / S-B6 | budget arithmetic inconsistent; mixed A/B untested | ACCEPT — PIN-29 defines `iterations_used` = re-plan rounds (A+B), a round may start iff `used < 3`; `test_shared_budget_mixed` |
| S-G11 | E-H appliance rule not isolated from Part G counts | ACCEPT — appliance receptacles are `extensions.appliance` in counts (PIN-20) |
| S-G12 | AUTO_APPROVE CI path untested | ACCEPT — gateway unit test with `config.autoApprove=true` |
| S-G13 | zero-length check vs vertical stacks | ACCEPT — 3D Euclidean segment length, reject < 1e-6 (§6.1) |
| S-I2 / S-I4 / S-B7 | no `ack_rejected`/expiry transitions; `expired_ttl` terminal | ACCEPT — `ack_rejected`, `expired`, and `rolled_back{expired_ttl}` all → re-issue allowed under the per-review cap, never counted against the clash budget (§5.1) |
| S-I3 / S-B2 | WSS frames concurrent; session write after the 202 | ACCEPT — per-session promise chain in `core.ts register()`; all Commit #2 state lives on the envelope/review rows written inside `insertIssuedEnvelope` / `recordCommitResult` transactions (no post-202 write) |
| S-I5 | `POST /envelopes` issues commit-labelled envelopes without `approval_ref` | ACCEPT — 422 `approval_ref_required` when `commit_label` matches `/^Commit #/` or ops contain commit-class ops (§5.1); Phase 1 e2e label "phase 1 golden walls" unaffected |
| S-I6 | gateway never verifies interior ops verbatim | ACCEPT — as T-I3 |
| S-I7 | issue-commit2 can commit superseded branches | ACCEPT — as T-I4 |
| S-I8 | no uniqueness on active merge sessions | ACCEPT — partial unique index `reviews_one_pending_commit2_merge`; `envelopes_one_inflight` covers issued envelopes (§2.3) |
| S-I11 / M-I15 | loops not time-limited inside the solver | ACCEPT — as T-I9 |
| S-I12 | `clash_delta` pairs unbounded | ACCEPT — as T-I5 |
| S-I13 | Part C placement deviation unlisted | ACCEPT — Eran Q9 |
| S-B10 | executor's committed model retains `envelope_created` | ACCEPT — reset to `None` after swap (§6.2) |
| S-B12 | `createReview` opens its own transaction | ACCEPT — `withTransaction(fn)` helper + `createReviewTx(client, …)` (§5.3) |
| M-G1 / M-I1 | branch drop from the fixture centre at floor_z self-clashes with the served fixture | ACCEPT — z0 = `floor_z − h_fitting` puts every branch below the floor; `(pipe leg, served fixture)` additionally exempt (§4.2) |
| M-B1 / M-G2 | wc + lav legs and trunks fully coincident; 56 coincident panel drops | ACCEPT — per-stack **branch tree** (one `create_pipe` per unique segment, Ø = max upstream) PIN-10; single-source **raceway tree** for conduits (drops per device + shared trunk chains) PIN-23; preflight asserts no positive-length same-system overlap |
| M-G3 / M-I5 / M-I6 | budget from `event_log`/envelope statuses (non-clash rollbacks counted, not shared across calls, no reset, spans superseded plans) | N/A — final persists `iterations_used` in each `commit2_merge` content and scopes to the chain; non-clash rollbacks never touch the budget |
| M-G4 / M-I2 / M-B2 | Phase-B furniture re-plan is a geometric no-op; test re-plans the higher priority | ACCEPT — progress guarantee: an action whose element hash is unchanged escalates (obstacle inflation → drop) in the same round; `replan_deltas` non-empty asserted in unit + e2e; lower priority always re-plans |
| M-G5 | non-interference rollbacks consume budget | ACCEPT — as S-I2/S-I4 |
| M-G6 / M-I3 | `plan-commit2` races the `clash_delta` frame | ACCEPT — as T-I2 (pairs come from `commit_result` in-transaction; 409 `clash_pairs_pending` never needed but kept as a guard) |
| M-G7 / M-B8 | E-3 leaves Bedroom 4 without a switch (D-013 on a 1000 mm wall) | ACCEPT — corner fallback (§3.3) |
| M-G8 / M-B4 | P-4 ignores the 2775 mm leg (F-006 7308 > 7115) | ACCEPT (partially) — spec-literal acceptance by default; the emitted z-profile is computed over the full tree path and the overshoot is surfaced (`branch_plenum_marginal`); Eran Q3 |
| M-G9 | range/oven as counter; kitchen E-1 all gfci | ACCEPT — sink/DW only define the fallback counter run; kitchen non-counter E-1 devices are `receptacle` (spec-literal) |
| M-G10 | 1 mm junction tolerance vs 0.1 mm node ids can disconnect the graph | ACCEPT — union-find canonicalization of all candidate points within 1 mm before edges (§3.5) |
| M-G12 / M-B3 | E-1 property fails in L ∈ (2a, 2a+300) | ACCEPT — property split: pre-dedupe bounds + post-dedupe coverage (§9) |
| M-G13 | windows don't break runs (spec: "openings") | ACCEPT (as PIN-12 ⚠) — windows break a run only when the device height lies within the window; constant `WINDOWS_BREAK_RUNS_ALWAYS = False` |
| M-I4 | offset-ordered ids renumber on re-plan → history pairs mis-resolve | REJECT for the final design — ids are assigned once in the approved `mep_plan`; the merge gate mutates params of existing ids and never re-numbers (§4.4) |
| M-I7 | stack chased into unflagged exterior W-004 | ACCEPT (vacuous on the flag-free golden) — PIN-05 excludes SI-8-flagged walls on real scans; the literal argmax stays on the golden |
| M-I9 | runtime `/merge` does not re-run the validator | ACCEPT — `validate_layout` after every re-plan round; oracle failure of a moved item → `drop`; final layout invalid → 422 `merge_internal` |
| M-B7 | nearest-centerline host wall mis-hosts 4/18 golden items | ACCEPT — placer-recorded `diagnostics.items[].wall_id` rides into `/plan-mep`; nearest wall is the fallback (§2.2) |
| M-B9 | T-junction into a rated wall is a penetration | ACCEPT — penalty whenever the path arrives at a node interior to rated B on a wall ≠ B (pass-through or turn-in); arrival along B itself is free (§3.5) |
| M-B14 | `tests/e2e/src/api.ts` missing from the modified list | ACCEPT — listed (§1) |
| M-B15 | Phase 5 handoff "verbatim" needs an amendment note | ACCEPT — §4.6 |

---

## Pinned decisions (for gate review)

Kind: **S** = spec-silent interpretation; **⚠** = deviates from the Part G letter or prior handoff text, sits behind a named constant, default = the letter unless stated; **E** = engineering/implementation pin. "Golden" = whether flipping it changes Phase 6 golden bytes.

| PIN | decision | kind | constant / default | alternative | golden |
|---|---|---|---|---|---|
| 01 | Wet room = `rooms[].wet_zone` OR the room holds a placed item with `"sanitary" ∈ hookups` (kitchen R-009 derived); recorded in `inputs.wet_rooms`/`derived_wet_rooms` | S | — | wet_zone only (kitchen fixtures would have no stack) | yes |
| 02 | Fixture = placed item with `"sanitary" ∈ hookups`; FU/drain Ø/slope from `catalogs/plumbing.json` by `kind`; never family-name matching (AST test) | S | — | — | — |
| 03 | Host wall of an item = placer-recorded `diagnostics.items[].wall_id`; fallback: boundary wall with |dist − (t/2 + d_eff/2)| ≤ 1, then nearest centerline, then smaller id | E | — | nearest-centerline only (4/18 golden items mis-hosted) | yes |
| 04 | Riser bias: nearest `risers[type=sanitary]`, 0 when none; no riser adoption in v1 (a stack within 300 of an existing sanitary riser → info `riser_adjacent`) | S | `LAMBDA_FU_PER_MM=0.0005` | adopt the riser as the stack | no (golden has no risers) |
| 05 | P-1 candidates exclude walls flagged `is_demising`/`is_load_bearing`/`is_exterior` (SI-8 immutability applied to stack chases) | S (SI-8) | `P1_EXCLUDE_SI8_WALLS=True` | literal argmax incl. flagged walls | no (flag-free golden) |
| 06 | P-1 tie-break: higher score → `is_wet_wall` first → smaller Σ FU·dist(wall, fixture) → smaller wall id | S | — | wall id only | yes (kitchen stack wall) |
| 07 | P-3 stack snapping: a stack inside a door clear span (± Ø/2 + 50) moves to the nearest legal offset; none → wall infeasible → residual re-runs P-1; info `p3_snapped` | S | `STACK_SNAP_MARGIN_MM=50` | wall infeasible whenever t_s lands in a span | yes (S-2 offset) |
| 08 | P-4 routed length `L = along` (P-2 foot → stack along the wet wall) | ⚠ letter | `P4_L_INCLUDES_DRAIN_LEG=False` | `L = leg + along` (physically honest; golden → 3 stacks) | yes — both tables in the gate note |
| 09 | P-4 violation: prune the fixture with the largest L (tie → smaller id), recompute t_s, repeat; residual re-runs P-1 over all candidates (same wall allowed); first stack stays | S | `MAX_STACKS=4`, `MAX_P1_ITERATIONS=16` (blocking item, not assert) | exclude the whole wall | yes |
| 10 | Branch geometry is a per-stack Manhattan **tree**: paths centre→foot→stack unioned, split at every node, one `create_pipe` per unique segment, Ø = max drain Ø upstream, slope by segment Ø; z-profile walked from the stack junction so the deepest fixture starts at `floor_z − h_fitting` (pipe top); plenum overshoot → info `branch_plenum_marginal` | E | — | one pipe per fixture (coincident pipes → live Revit rollback) | yes |
| 11 | v1 emits sanitary DWV only; stack path `[floor_z − h_plenum, ceiling_z]` (vent continuation); `vent_manual`/`supply_manual`/`gas_manual`/`wye_manual` info items; stack Ø = max(51, 76 if any wc, max drain Ø) | S | `STACK_MIN_DIAMETER_MM=51`, `STACK_WC_DIAMETER_MM=76` | — | — |
| 12 | Openings that break device runs: doors always; windows only when the device height lies within the window | ⚠ letter ("openings") | `WINDOWS_BREAK_RUNS_ALWAYS=False` | windows always break | yes |
| 13 | Stack exclusion squares (±300) do **not** break device runs; a device whose foot is inside a square has no route → info `device_unroutable`, no conduit | letter | `ZONES_BREAK_DEVICE_RUNS=False` | zones break runs (devices slide out of the square; every device routable) | yes |
| 14 | Spacing kernel: `N=max(1,⌈(L−2a)/S⌉+1)`; `N=1 → [L/2]` explicit; general dedupe = merge consecutive positions < 300 apart to their midpoint until fixpoint; `outlet_spacing < 610` → blocking `outlet_spacing_invalid` | S | `E1_MIN_OUTLET_SPACING_MM=610` | keep-first dedupe | yes (N=2 band) |
| 15 | Counter run interval is removed from E-1 runs on that wall (fixed cabinets break wall space); the rest of the wall gets E-1 | S | — | — | yes |
| 16 | Corridor: one `receptacle` at the midpoint of the longest legal 380-run if the longest boundary edge ≥ 3000, else none (NEC 210.52(H)) | ⚠ | `HALLWAY_RECEPTACLE_MIN_EDGE_MM=3000` | plain E-1 spacing on corridor walls | yes |
| 17 | Laundry: one `gfci` at 1150 at the midpoint of the longest legal run ≥ 610 (NEC 210.52(F)); closet: none; bathroom/powder: E-2 basin rule only | ⚠ | — | plain E-1 spacing | yes |
| 18 | Counter walls: `casework[].is_counter` (spec) ∪, when the layout has NO casework, host walls of `kitchen_sink`/`dishwasher` in kitchen rooms; fallback run = union of their footprint projections ± 600, minus range/oven/refrigerator projections, minus openings; info `counter_walls_derived` | S | `E2_COUNTER_FALLBACK_EXTEND_MM=600` | casework only (E-2 vacuous on the golden) | yes |
| 19 | GFCI is area-based: any device on a kitchen counter wall, or in bathroom/powder/laundry, is `kind=gfci` (E-1, E-2, appliance alike); kitchen non-counter devices are `receptacle` | S | — | 2020-NEC all-kitchen GFCI | yes |
| 20 | Appliance receptacles (no Part G rule): one `receptacle`/`gfci` per placed item with `electrical_120`/`electrical_240`, at its host-wall foot, 380 AFF, shifted ≤ 600 to a legal run point (`appliance_receptacle_shifted`), else `appliance_receptacle_unplaceable`; `electrical_240` → info; never deduped; reported under `counts.extensions.appliance` | ⚠ extension | `EXTENSION_APPLIANCE_RECEPTACLES=True` | off (Part G-only counts) | yes |
| 21 | E-3: one switch per door, swept-side room, latch side 150 from jamb, 1220 AFF; fallback ladder: latch-corner adjacent wall of the same room (150 from the corner) → hinge side → none; every fallback emits an info item; `room_without_switch` for non-closet rooms with none; back-to-back devices (same wall, |Δoffset|<100, |Δh|<100) shift +150·k, k ≤ 8 | S | `E3_CORNER_FALLBACK_MM=300` | latch side only + review | yes |
| 22 | E-4 penalty applies to `fire_rating_hr ≥ 1` (wall flag else catalog) and to `is_demising` walls; penetration = arriving at a node interior to rated B on a wall ≠ B (pass-through or turn-in) | S (SI-8) | `E4_PENETRATION_PENALTY_MM=4000` | fire rating only; turn-in free | no (flag-free golden) |
| 23 | E-4 ops are a single-source raceway **tree**: one drop conduit per device (`Q-n` pairs with `E-n`) + one conduit per maximal trunk chain; `home_runs[]` reports the per-device path/length/penetrations/cost; panel node = panel foot on its wall; conduits end at z 2600 | E | `E4_CONDUIT_Z_MM=2600`, `E4_CONDUIT_DIAMETER_MM=21`, `PANEL_MAX_WALL_DIST_MM=600` | one full conduit per device (coincident solids) | yes |
| 24 | Clash law (all three executors): walls/doors/windows are not clash elements; structure = columns + risers; exempt pairs: same-system (pipe,pipe), (conduit,conduit), (device,device), (device,conduit), (pipe leg, served fixture), (furniture, device), (furniture, conduit); everything else checked; positive-area footprint overlap AND strict z overlap; heights from `catalogs/clash_prisms.json` | S | `OVERLAP_EPS_MM2=1e-3` | wall prisms + clipping | yes (Phase A counts) |
| 25 | Phase A uses oriented shapely polygons (D1); the sim uses AABBs of the same prisms (superset); the plugin uses `ElementIntersectsElementFilter` with the same exemption pairs by category | E | — | — | — |
| 26 | Re-plan actions (lower priority moves): furniture → `legalize_furniture(preplaced, obstacles)`; device → slide ±150·k (k ≤ 4) away from the higher element; conduit → re-route with forbidden edges; stack (vs structure) → `relocate_stack`; no-change → escalate → `drop`; every action logged with before/after | E | `DEVICE_SHIFT_MM=150`, `DEVICE_SHIFT_TRIES=8` | REVIEW on any furniture pair | recovery golden |
| 27 | Merge is stateless and replayable: `prior_actions` are replayed deterministically; ids are never re-assigned by the merge | E | — | — | — |
| 28 | Merge chain identity = (interior_plan.review_id, mep_plan.review_id); iteration state is derived from the chain's `commit2_merge` reviews and their envelopes; a new approved `mep_plan` or `interior_plan` starts a fresh chain (the REVIEW exit) | E | — | merge_sessions table | — |
| 29 | Budget: `iterations_used` = re-plan rounds performed (Phase A rounds that applied actions + Phase B re-plan calls); a round may start iff `iterations_used < 3`; therefore two rollbacks → plan 3 commits, three rollbacks → plan 4 is still allowed, a fourth rollback → REVIEW | ⚠ interpretation | `MERGE_BUDGET=3` | "≤ 3 merged plans" (third rollback → REVIEW) | e2e counts |
| 30 | Commit #2 re-issues use a fresh seq (`max(lastCommitted, lastIssued)+1`, fresh envelope_id); Phase 1–5 same-seq behaviour unchanged (D3) | ⚠ Phase 6 text | `issueEnvelope({seqPolicy:"next_issued"})` | same seq (D3) | e2e asserts |
| 31 | Every rebuilt merged plan is a new `commit2_merge` review requiring human approval before signing (AUTO_APPROVE covers it in CI only) | E (SI-2/SI-5) | — | approve-once, auto re-issue within budget | — |
| 32 | Non-clash rollbacks: `expired_ttl`, `ack_rejected`, sweep `expired` → the same approved review may be re-issued (cap 3 per review, not counted against the clash budget); `duplicate_id`/`unknown_revit_type`/`op_not_implemented`/`fitting_unsupported`/`internal` → `commit2_failure`, chain `failed` (exit: new `plan-mep`) | E | `MAX_REISSUES_PER_REVIEW=3` | — | — |
| 33 | Confirmations (`panel`, `slab_to_slab_mm`) arrive on `plan-mep` (body or UI form) and are stamped into `meta.electrical.panel`/`meta.levels`; a `plan-mep` call without confirmations reuses the latest `mep_plan`'s; validation: `slab_to_slab_mm` 2100..6000 and > ceiling height else blocking `levels_inconsistent`; panel within 600 of a wall centerline else 422 `panel_not_on_wall` | E | — | separate `mep_inputs` review kind | — |
| 34 | `face` is emitted in `place_device` iff the registry `args_schema` declares it (auto-detected at import); otherwise right-face devices carry `face:"right"` in content + info `device_face_unavailable` and executors host on face_left | E | — | — | yes (once Q1 lands) |
| 35 | Multi-segment `create_pipe`/`create_conduit` id-map: logical id → first segment's ElementId; remaining segments/fittings grouped under a Revit `Group` named `HUB {id}` | E | — | one logical id per segment (op change) | — |
| 36 | MEP agent + merge gate live in `services/layout-compiler` (`mep/`, `merge/`), continuing the Phase 4/5 deviation from PLAN Part C `services/agents/*` | E | — | new services | — |
| 37 | Furniture moved by a Phase A/B re-plan: `interior.ops_verbatim=false`, per-item `replan_deltas`, the `commit2_merge` approval supersedes the `interior_plan` ops for those items; the commit2 snapshot is the re-planned furnished layout | ⚠ Phase 5 handoff text | — | re-open `interior_plan` | recovery golden |

---

## 1. Package placement & service topology

**Decision.** MEP agent and merge gate are two subpackages of `services/layout-compiler`, exposed as two endpoints on the existing FastAPI app. No new service, venv or CI job; **e2e stays at 5 children** (converter, extractor, compiler, gateway, sim). Rationale: shared seams (`geometry.py`, `swing.py`, `catalogs.py`, `interior.py`, `replay.py`, `validator.py`), shapely/hypothesis already present, Phase 4/5 precedent (PIN-36; Eran Q9). Phase 6 is deterministic — no LLM seam.

```
services/layout-compiler/src/layout_compiler/
  mep/
    constants.py    # every constant in §3.0, incl. the interpretation switches
    inputs.py       # levels/panel resolution + stamping, wet rooms, host walls, counter walls, blocking items
    runs.py         # wall runs per (room, wall, height): collinear-edge mapping, opening breaks
    plumbing.py     # P-1..P-4, branch tree, z-profile
    electrical.py   # E-1/E-2/E-3, corridor/laundry rules, appliances, dedupe, back-to-back, gfci area rule
    routing.py      # E-4: canonical wall graph, state Dijkstra from the panel, raceway tree
    fittings.py     # elbow classification (90/45/unsupported), collinear merge — twin of C# PipePath
    ops.py          # place_device / create_pipe / create_conduit emission, id assignment, registry validation
    plan.py         # plan_mep(): orchestration, deadline, MepPlan
  merge/
    prisms.py       # element -> 2.5D prism (Polygon, z0, z1, priority, cls, host, links); reads clash_prisms.json
    clash.py        # Phase A STRtree sweep, exemptions, deterministic ordering
    replan.py       # per-pair actions, action log, replay, progress guarantee
    gate.py         # merge(): budget state machine, merged ops, clash report, SVGs, validator oracle
  golden_mep.py     # golden constants (panel, slab_to_slab, injected pairs) — a table like golden_4br.py
scripts/gen_golden_mep.py, scripts/demo_phase6.py
```

Modified: `interior.py` (keyword-only `preplaced=()`, `obstacles=()` on `legalize_furniture`), `replay.py` (`render_mep_svgs`, `render_merge_svgs`), `catalogs.py` (`plumbing_table()`, `wall_fire_rating_hr()`, `mep_types()`, `clash_prisms()`), `server.py` (`/plan-mep`, `/merge`), sim `model.py`/`executor.py`/`client.py`/`render/svg.py`/new `clash.py`, gateway `routes.ts`/`repos.ts`/`core.ts`/`ui/reviews.ts`/`config.ts`/new `layout/mep-client.ts`, `layout/merge-client.ts`, `migrations/0005_commit2.sql`, plugin `Handlers.cs`/`EnvelopeHandler.cs`/new Core `PipePath.cs`, `ClashPairs.cs`, `tests/e2e/src/api.ts` + `harness.ts`, `docs/MANUAL_REVIT_TEST.md`, `Makefile`, CLAUDE.md status.

New contract-adjacent files (no schema change): `packages/contracts/catalogs/mep_types.json` (placeholders, `requires_human_input: true`), `packages/contracts/catalogs/clash_prisms.json` (engineering defaults like `plumbing.json`: kind heights, exemption pairs, default family height), `packages/contracts/fixtures/pipepath/manifest.json` (C#/Python conformance twin). Registry prose amendment for `create_pipe`/`create_conduit`/`run_interference_check` `sim_behavior` is Eran Q5.

### 1.1 Compiler endpoints

`POST /plan-mep` — `MepRequest` (`extra="forbid"`):
```json
{ "project_id": "uuid",
  "commit0_layout": {ChapterLayout}, "commit1_layout": {ChapterLayout}, "commit1_ops": [...],
  "interior_ops": [{"op":"place_family","args":{...}}],
  "furnished_layout": {ChapterLayout},
  "placer_wall_ids": {"F-001":"W-003", ...},
  "confirmations": {"panel": [8050.0, 5200.0], "slab_to_slab_mm": 3000.0} }
```
Response 200 = **MepPlan** (the `mep_plan` review content minus gateway-stamped keys):
```json
{ "layout": {furnished ChapterLayout with meta.levels + meta.electrical.panel stamped},
  "inputs": {"floor_z":0.0,"ceiling_z":2700.0,"slab_to_slab":3000.0,"h_plenum":300.0,"levels_source":"meta|confirmation|missing",
             "panel":[8050.0,5200.0],"panel_source":"meta|riser:RS-01|confirmation|missing","panel_node":[8000.0,5200.0],"panel_wall_id":"W-019",
             "outlet_spacing":3660.0,"wet_rooms":[...],"derived_wet_rooms":["R-009"],"counter_walls":{"R-009":["W-002"]},"counter_source":"casework|derived"},
  "stacks":   [{"id":"P-001","wall_id":"W-004","offset":5133.3,"xy":[5133.3,7000.0],"diameter":76.0,"fixtures":["F-006","F-007","F-012"],
               "score_fu":9.0,"riser_bias":0.0,"p1_ranking":[["W-004",9.0],["W-001",5.0],["W-003",5.0],["W-025",5.0],...],"snapped":false}],
  "branches": [{"id":"P-003","fixture_ids":["F-006"],"stack_id":"P-001","diameter":76.0,"slope":0.0104,"segment":[[600,4225,-188.0],[600,6675,-162.5]],"cls":"leg"}],
  "fixture_routes": [{"fixture_id":"F-006","leg_mm":2775.0,"along_mm":4533.3,"L_mm":4533.3,"L_max_mm":7115.4,"path_mm":7308.3,"plenum_overshoot_mm":2.0}],
  "devices":  [{"id":"E-001","kind":"receptacle","rule":"E-1","room_id":"R-001","host_wall_id":"W-001","offset":1912.5,"height_afl":380.0,
               "run":[0.0,3825.0],"face":"right","door_id":null,"source":null,"circuit":"120V"}]   # device ↔ conduit pairing lives in home_runs[] (conduit_id), not on the device,
  "home_runs":[{"device_id":"E-001","conduit_id":"Q-001","length_mm":12345.6,"penetrations":0,"cost":12345.6,"nodes":[[0.0,1912.5],[0.0,7000.0],...]}],
  "ops": [ create_pipe..., place_device..., create_conduit... ],
  "review_items": [{"code":"wye_manual","severity":"info","refs":["P-001","P-005"],"message":"..."}],
  "svgs": {"commit1":"<svg…>","mep":"<svg…>"},
  "diagnostics": {"elapsed_ms":412.0,"counters":{"p1_iterations":2,"p4_prune_steps":0,"snap_steps":1,"graph_nodes":81,"graph_edges":97,"dijkstra_states":210,"shift_tries":3}},
  "counts": {"devices":45,"receptacle":30,"gfci":5,"switch":10,"pipes":10,"stacks":2,"conduits":60,"review_items":14,"blocking":0,
             "extensions":{"appliance":3}} }
```
422 `{"error": code, "message", "raw_outputs": []}` with `commit1_layout_invalid | furnished_layout_invalid | mep_timeout | mep_internal`.

Severity: **blocking** = `panel_missing, levels_missing, levels_inconsistent, plenum_too_shallow, no_wet_wall_candidate, stacks_exceeded, p1_iterations_exceeded, outlet_spacing_invalid, fixture_kind_unknown`. **info** = `p3_snapped, p4_prune, branch_plenum_marginal, wye_manual, vent_manual, supply_manual, gas_manual, riser_adjacent, counter_walls_derived, room_without_receptacle, room_without_switch, switch_corner_fallback, switch_hinge_side, switch_unplaceable, appliance_receptacle_shifted, appliance_receptacle_unplaceable, electrical_240, bath_gfci_unplaceable, device_backtoback_shifted, device_unroutable, conduit_path_too_long, conduit_fittings_manual, device_face_unavailable`.

`POST /merge` — `MergeRequest` (`extra="forbid"`):
```json
{ "project_id":"uuid", "commit0_layout":{...}, "commit1_ops":[...],
  "interior": {"review_id":"uuid","content_hash":"sha256hex","ops":[...],"layout":{...}},
  "mep":      {"review_id":"uuid","content_hash":"sha256hex","plan":{MepPlan}},
  "iterations_used": 0, "iteration": 1,
  "prior_actions": [ {Action} ],
  "clash_pairs": [{"a_id":"E-001","b_id":"P-001","kind":"hard_interference"}] }
```
Response 200 = **MergeResult**:
```json
{ "status":"clean|budget_exhausted|blocked", "iteration":1, "iterations_used":0,
  "interior":{"review_id":"…","content_hash":"…","ops_count":18,"ops_verbatim":true},
  "mep":{"review_id":"…","content_hash":"…","ops_count":115},
  "layout":{furnished ChapterLayout after any furniture re-plans, meta stamped},
  "ops":[ place_family..., create_pipe..., place_device..., create_conduit..., {"op":"run_interference_check","args":{"scope":"last_commit"}} ],
  "actions":[ {Action} ], "replan_deltas":[{"id":"F-014","kind":"furniture","from":{...},"to":{...},"reason":"..."}], "dropped":["E-045"],
  "clash_report":{ClashReport}, "svgs":{"commit1":"<svg…>","merged":"<svg…>"},
  "counts":{"ops":115,"place_family":18,"place_device":45,"create_pipe":10,"create_conduit":60} }
```
`Action = {"iteration","trigger":"phase_a|phase_b","pair":{a_id,b_id,kind},"lower","lower_priority","higher","higher_priority","action":"shift_device|reroute_conduit|relegalize_furniture|relocate_stack|drop","params":{before,after},"changed":true}`.
`ClashReport = {"budget":{"limit":3,"used":k,"remaining":3-k},"phase_a":{"rounds":[{"iteration","clashes":[{a_id,b_id,a_cls,b_cls,a_priority,b_priority,overlap_area_mm2,z_overlap_mm}],"actions":[...]}]},"phase_b":{"replans":[{"iteration","pairs":[...],"actions":[...]}]},"prisms":{"furniture":18,"structure":0,"pipes":10,"devices":45,"conduits":60}}`.
422: `interior_layout_invalid | clash_pair_unknown | merge_timeout | merge_internal`.

### 1.2 Gateway routes
- `POST /projects/:id/plan-mep` (service) body `{confirmations?}` → `mep_plan` | `mep_failure`.
- `POST /ui/projects/:id/plan-mep` (actor form `panel_x, panel_y, slab_to_slab_mm`) → same → 302 (the README's human-suppliable card field).
- `POST /projects/:id/merge-commit2` (service) → `commit2_merge` | `commit2_failure`.
- `POST /projects/:id/issue-commit2` (service) → envelope "Commit #2".
- `GET /projects/:id/state` gains `mep_plan_ready`, `commit2_done`, `commit2 {...}` (§5.4).

---

## 2. Data model

### 2.1 Representation — no contract schema change
MEP geometry lives in (a) registry ops and (b) review content, exactly as Phase 5 did for furniture. `mep_plan.content` is the MEP branch delta: `content.ops` verbatim = the MEP half of Commit #2; the tables (`stacks/branches/devices/home_runs`) are its projection (generator asserts tables ⇔ ops). `commit2_merge.content` embeds both branch refs + merged ops. The `commit2` snapshot stores `content.layout` — the furnished ChapterLayout **with `meta.levels {floor_z, ceiling_z, slab_to_slab}` and `meta.electrical.panel` stamped** from confirmations/meta/riser (validated against `chapter-layout.v2.3.json`; PIN-33). Stacks have no schema home: they are `create_pipe system=sanitary` vertical paths + `stacks[]` (the sim renders a stack marker from vertical sanitary pipes).

Optional registry proposal (Eran Q1, pre-build): `place_device.args.face: enum[left,right]`, `place_device.kind += receptacle_240`. Fallback in force until then: PIN-34.

### 2.2 Derived semantics (all PIN-01..07, 18, 22)
- **Levels**: `meta.levels` if present (assert D1 `floor_z < ceiling_z ≤ floor_z + slab_to_slab` else blocking `levels_inconsistent`); else `floor_z = 0`, `ceiling_z` = commit0 snapshot wall height (uniform by construction — never `decision_payload`, which is null under AUTO_APPROVE), `slab_to_slab = confirmations.slab_to_slab_mm` else blocking `levels_missing`. `h_plenum = slab_to_slab − (ceiling_z − floor_z)`; `h_plenum − Ø − h_fitting ≤ 0` for any fixture → blocking `plenum_too_shallow`.
- **Panel**: `meta.electrical.panel` → nearest `risers[type=electrical]` (tie → smaller id) → `confirmations.panel` → blocking `panel_missing` (E-1..E-3 still run; E-4 emits nothing). Panel wall = nearest centerline within 600 else 422 `panel_not_on_wall` (gateway zod + compiler).
- **Fire rating**: `catalogs.wall_fire_rating_hr(wall)` = `wall.fire_rating_hr` else catalog entry for `revit_type` else 0.
- **Wet room / fixture / host wall / counter wall**: PIN-01/02/03/18.

### 2.3 DB — migration `0005_commit2.sql`
```sql
ALTER TABLE envelopes ADD COLUMN clash_pairs jsonb;   -- pairs from commit_result (parsed) ∪ clash_delta, clamped
ALTER TABLE envelopes ADD COLUMN errors jsonb;        -- commit_result.errors verbatim (rolled_back only)
CREATE UNIQUE INDEX reviews_one_pending_commit2_merge ON reviews(project_id)
  WHERE kind = 'commit2_merge' AND status = 'pending';
```
`commit2` already exists in `layout_snapshots.commit_label` CHECK and `SnapshotRow`. Review kinds (free text): `mep_plan`, `mep_failure`, `commit2_merge`, `commit2_failure`. Iteration state is derived from the **merge chain** (PIN-28), never stored separately.

---

## 3. MEP algorithms (Part G; every constant in mm)

### 3.0 Constants (`mep/constants.py`)
```
LAMBDA_FU_PER_MM = 0.0005
E1_INSET_MM = 1830; E1_DEFAULT_SPACING_MM = 3660; E1_MIN_RUN_MM = 610; E1_DEDUPE_MM = 300; E1_HEIGHT_AFL_MM = 380; E1_MIN_OUTLET_SPACING_MM = 610
E2_INSET_MM = 610; E2_SPACING_MM = 1220; E2_HEIGHT_AFL_MM = 1150; E2_BASIN_MAX_MM = 914; E2_COUNTER_FALLBACK_EXTEND_MM = 600
E3_JAMB_OFFSET_MM = 150; E3_HEIGHT_AFL_MM = 1220; E3_CORNER_FALLBACK_MM = 300
E4_PENETRATION_PENALTY_MM = 4000; E4_STACK_EXCLUSION_MM = 300; E4_CONDUIT_Z_MM = 2600; E4_CONDUIT_DIAMETER_MM = 21; E4_MAX_PATH_POINTS = 100
DEVICE_EDGE_MM = 50; DEVICE_B2B_MM = 100; DEVICE_SHIFT_MM = 150; DEVICE_SHIFT_TRIES = 8; APPLIANCE_SHIFT_MAX_MM = 600
STACK_MIN_DIAMETER_MM = 51; STACK_WC_DIAMETER_MM = 76; STACK_SNAP_MARGIN_MM = 50; RISER_ADJACENT_MM = 300
HALLWAY_RECEPTACLE_MIN_EDGE_MM = 3000; PANEL_MAX_WALL_DIST_MM = 600
MAX_STACKS = 4; MAX_P1_ITERATIONS = 16; MERGE_BUDGET = 3
MEP_TIME_LIMIT_S = 60.0; MERGE_TIME_LIMIT_S = 60.0     # wall clock only in plan.py/gate.py; deadline_check threaded into every loop
GRAPH_NODE_TOL_MM = 1.0; COORD_ROUND = 0.1
# interpretation switches — flipping any regenerates goldens (see Pinned decisions)
P4_L_INCLUDES_DRAIN_LEG = False; ZONES_BREAK_DEVICE_RUNS = False; WINDOWS_BREAK_RUNS_ALWAYS = False
P1_EXCLUDE_SI8_WALLS = True; EXTENSION_APPLIANCE_RECEPTACLES = True
```
Slopes and `default_fitting_allowance_mm` come from `catalogs/plumbing.json` via `catalogs.plumbing_table()`. `mep/` and `merge/` import no `random`/`time`/`os.environ` except the two orchestration modules (AST test); every loop receives `deadline_check` (SI-6).

### 3.1 Wall runs (`runs.py`)
```
wall_runs(layout, room, wall, height_afl, zones=()) -> [(t0, t1)]
  collinear edges of room.boundary (perp distance to the wall's infinite line ≤ t/2 + 1 at both ends) → clamp to [0, L] → merge
  breaks = door spans (offset ± width/2)
         + window spans if WINDOWS_BREAK_RUNS_ALWAYS or sill ≤ height_afl ≤ sill + height
         + zones (only when ZONES_BREAK_DEVICE_RUNS)
  runs = segs − breaks, dropping runs ≤ 1 mm; rounded 0.1
device legal on run ⇔ t0 + 50 ≤ offset ≤ t1 − 50
```

### 3.2 P-1 … P-4 (`plumbing.py`)
```
plan_plumbing(inputs, deadline_check) -> (stacks, tree_segments, fixture_routes, items, counters)
  fixtures = placed items with 'sanitary' ∈ hookups, sorted by id; residual = set(ids); it = 0
  while residual:
      deadline_check(); it += 1
      if it > MAX_P1_ITERATIONS: blocking p1_iterations_exceeded(residual); break
      if len(stacks) == MAX_STACKS: blocking stacks_exceeded(residual); break
      # P-1
      cand = {}                                    # wall -> (ΣFU over residual fixtures in adjacent wet rooms, fixture ids)
      for room in wet_rooms with ≥1 residual fixture:
          for w in room.boundary_wall_ids:
              if P1_EXCLUDE_SI8_WALLS and (w.is_demising or w.is_load_bearing or w.is_exterior): continue
              cand[w] += residual fixtures of room
      if not cand: blocking no_wet_wall_candidate(residual); break
      score(w) = ΣFU − LAMBDA·dist(w, nearest sanitary riser)   # 0 bias when none
      pick = max by (score, is_wet_wall, −ΣFU·dist(w, fixtures), −wall_id)      # PIN-06
      serve = sorted(cand[pick])
      # P-2 / P-3 / P-4 prune loop (bounded by len(serve))
      loop:
          feet = {f: project_to_wall(center_f, pick)}            # fixture never moves
          t_s = Σ FU_f·t*_f / Σ FU_f
          Ø_stack = max(51, 76 if any wc in serve, max drain Ø)
          off = snap_out_of_door_spans(t_s·L, pick, margin=Ø_stack/2 + 50)   # PIN-07; None → wall infeasible
          if off is None: exclude pick for this iteration; serve = None; break
          L_f = along_f (+ leg_f if P4_L_INCLUDES_DRAIN_LEG)      # PIN-08
          viol = [f for f in serve if L_f > L_max_f + 1e-9]
          if not viol: break
          drop = max(viol, key=(L_f, −id)); serve.remove(drop); info p4_prune
      if serve is None: continue
      stacks.append(Stack(pick, off, xy, Ø_stack, serve, score, ranking=top5, snapped))
      residual −= serve
  tree_segments = branch_tree(stacks)                              # PIN-10
```
`L_max_f = (h_plenum − drain_f − h_fitting) / slope(drain_f)`, slope `0.0208` for Ø < 76, `0.0104` for Ø ≥ 76 (`slope_rules`). A single fixture always satisfies `along = 0`, so the loop terminates: each outer iteration removes ≥ 1 fixture or excludes a wall for that iteration only.

**Branch tree (PIN-10).** For each stack: paths `c_f → p_f → s` (leg then along). Union all segments; split at every node of any path lying on a segment (tolerance 0.5); one `create_pipe` per unique segment, `diameter = max drain Ø of fixtures whose path uses it`, `slope` by that Ø. z-profile (pipe **centerline**): walk outward from the stack junction: `z(child) = z(parent) + slope(seg)·len(seg)`; choose `z(junction)` so that the governing fixture (largest cumulative drop) has `z(c_f) + Ø_f/2 = floor_z − h_fitting`. Per segment: `z − Ø/2 ≥ floor_z − h_plenum` else info `branch_plenum_marginal(fixture, overshoot_mm)`. Path points `[[x,y,z]…]` rounded 0.1; zero-length segments never emitted. Fittings: bends are 90° by construction (`fittings.py` asserts); every tree junction and stack junction → info `wye_manual` (registry: tee/wye emits REVIEW). Stack pipe: `[[sx,sy,floor_z − h_plenum],[sx,sy,ceiling_z]]`, `system=sanitary`, `pipe_type=mep_types.pipe_types.sanitary`, `level=meta.level`. Ids: stacks `P-001..`, then segments in (stack order, segment start node sorted) order. Preflight: no two same-system segments overlap with positive length (tree guarantees; asserted → 422 `mep_internal`).

Vents/supply/gas: PIN-11 info items only.

### 3.3 E-1 / E-2 / E-3 / appliances (`electrical.py`)

**Spacing kernel** (pure, hypothesis-tested):
```
spacing_positions(L, a, S) -> list[float]
  if L < 610: return []
  N = max(1, ceil((L − 2a)/S) + 1)
  xs = [L/2] if N == 1 else [a + i·(L − 2a)/(N − 1) for i in range(N)]
  while ∃ consecutive pair with gap < 300: merge the first such pair to its midpoint      # PIN-14 fixpoint
  return xs
```
`outlet_spacing = constraints.outlet_spacing or 3660`; `< 610` → blocking `outlet_spacing_invalid`.

**Per room (sorted by id), by program:**
- `closet`: nothing. `bathroom | powder`: E-2 basin rule only. `corridor`: PIN-16. `laundry`: PIN-17.
- every other program (incl. kitchen, living, bedroom, dining, office, foyer, other): **E-1** — for each wall in `boundary_wall_ids` order, runs at 380 minus counter-run intervals (PIN-15) → `spacing_positions(L, 1830, outlet_spacing)`; device `offset = t0 + x`, `height_afl 380`.
- kitchen counter walls: **E-2** — runs at 1150 within the counter interval → `spacing_positions(L, 610, 1220)`, `height_afl 1150`.
- bathroom/powder lav: **E-2 basin** — host wall `w`, foot `o`; candidates `o ± k·50`, k = 6..18 in order (k, +, −) (300 … 900 ≤ 914); first legal on a 1150-run → `gfci`; none → info `bath_gfci_unplaceable`; no lav → nothing (Phase 5 REVIEW already covers it).
- **appliances** (PIN-20, `EXTENSION_APPLIANCE_RECEPTACLES`).
- **kind** (PIN-19): `gfci` if the device is on a kitchen counter wall or in bathroom/powder/laundry, else `receptacle`.
- **E-3** per door (sorted): `hinge_t`, `latch_t` from `swing.py` conventions; swept-side room via `swing_side_normal` (exterior door → inside room); `offset = latch_t ± 150` away from the opening; legal on a 1220-run of that room → switch; else adjacent wall of the same room meeting the host wall at the latch corner, 150 from the corner → switch + info `switch_corner_fallback`; else hinge side → switch + info `switch_hinge_side`; else info `switch_unplaceable`. Pocket doors use the same convention. One switch per door.
- **back-to-back**: in emission order a device matching an earlier one on `(host_wall_id, |Δoffset| < 100, |Δheight| < 100)` shifts `+150·k`, k ≤ 8, to the first legal offset (info `device_backtoback_shifted`), else dropped with info.
- info `room_without_receptacle` / `room_without_switch` for non-closet rooms ending with none.

**Ids and order**: E-1 (room, wall, run, x) → corridor → laundry → E-2 counter → E-2 basin → appliances → E-3 → `E-001…`. `face` per PIN-34. Ids are frozen with the approved `mep_plan` (PIN-27).

### 3.4 Op emission (`ops.py`)
Every op validated against `registry.json` `args_schema` (jsonschema). MEP delta order: `create_pipe` (stacks, then tree segments) → `place_device` (E order) → `create_conduit` (drops `Q-n` for `E-n`, then trunk chains). Numbers rounded 0.1; `level = furnished_layout.meta.level`; `pipe_type`/conduit type from `mep_types.json` (placeholders until Eran's vocabulary lands).

### 3.5 E-4 home runs (`routing.py`)
```
build_graph(layout, stacks, devices, panel_foot, forbidden=())
  candidate points per wall: endpoints, pairwise segment∩segment (T-junctions and crossings), device feet, panel foot,
                             stack-square boundary crossings
  canonicalize: union-find all points within GRAPH_NODE_TOL_MM (1.0) → one node id per class (fixes the 0.1 mm id vs 1 mm tolerance gap)
  per wall: sort offsets → edge (u,v,wall,len) unless the open segment intersects any stack square interior or is forbidden
  interior_of(B) = nodes u on B with 1 < t_B(u) < L_B − 1
dijkstra(graph, source=panel_foot, deadline_check)      # single-source; state = (node, arriving_wall|None)
  relax u→v on wall C from (u, A): pen = |{B rated: u ∈ interior_of(B), B ≠ A, B ≠ C or C == B and A ≠ B}|   # PIN-22: pass-through and turn-in both penalize; arriving along B is free
  cost' = cost + len + 4000·pen; ties (cost, node, wall) lexical; states ≤ |nodes|·(|walls|+1) — counter asserted
home_run(device) = parent walk from its foot node → nodes; unreachable → info device_unroutable (no conduit)
raceway tree (PIN-23) = union of all home-run parent edges:
  drop per device: create_conduit Q-n [[fx,fy,h_afl],[fx,fy,2600]]
  trunk chains: maximal chains between nodes of tree-degree ≠ 2, collinear points collapsed, at z 2600; > 100 points → info conduit_path_too_long
  one info conduit_fittings_manual with the junction count
```
`home_runs[]` carries per-device `length_mm`, `penetrations`, `cost`, `nodes` (the E-4 acceptance tests read these). Rated = `wall_fire_rating_hr ≥ 1 or is_demising`.

---

## 4. Merge gate (`merge/`)

### 4.1 Inputs
Approved `interior_plan.content.ops` + `content.layout` (verbatim; `content.unplaced` never read), approved `mep_plan.content` (ops + tables), `iterations_used`, `iteration`, `prior_actions` (replayed — `/merge` is stateless), `clash_pairs` (Phase B).

### 4.2 Prisms (`prisms.py`) — from `catalogs/clash_prisms.json`
| element | footprint | z | priority | cls |
|---|---|---|---|---|
| column | oriented rect | `[floor_z, ceiling_z]` | 0 | structure |
| riser | `Point.buffer(150)` | `[floor_z − h_plenum, ceiling_z]` | 0 | structure |
| pipe segment | `LineString.buffer(Ø/2)`; vertical → `Point.buffer(Ø/2)` | `[min z − Ø/2, max z + Ø/2]` | 1 (sanitary/vent) · 2 (supply, none in v1) | leg / along / stack |
| conduit segment | `buffer(Ø/2)` | `[2600 ± Ø/2]`; drop `[h_afl, 2600]` | 4 | along / drop |
| device | box at the centerline foot: along ±50, across ±t_wall/2 | `[h_afl − 60, h_afl + 60]` | 4 | device |
| furniture | `geometry.furniture_rect(item)` | `[0, kind_heights[kind] or default 900]` | 5 | furniture |

Walls/doors/windows are **not** clash elements (PIN-24). Exempt pairs (PIN-24) are the same list in Phase A, `revit_sim.clash` and the plugin (by category). `kind_heights` (engineering defaults, Eran reviews): bed 600, sofa 850, table 750, chair 900, desk 750, wardrobe 2100, nightstand 600, wc 800, lav 850, shower 2100, tub 600, kitchen_sink 900, dishwasher 900, washer 1900, range 900, oven 900, refrigerator 1800, default 900.

### 4.3 Phase A sweep (`clash.py`)
Elements sorted `(priority, id)`; STRtree over footprints; for each candidate pair not exempt: `area = ∩.area > 1e-3` and `z_overlap > 0` → clash `(a = higher priority, b = lower)`. Clashes sorted `(a_id, b_id)`. Bounded by |elements|²; `deadline_check` per query.

### 4.4 Re-plan (`replan.py`) — lower priority moves (PIN-26)
| lower \ higher | action |
|---|---|
| furniture (5) vs pipe/conduit/column/riser | `relegalize_furniture`: `legalize_furniture([item], layout minus item, deadline, preplaced=other placed items, obstacles=[higher.polygon.buffer(50)])`; on success update `layout.furniture` + its `place_family` op and record `replan_deltas`; `validate_layout` oracle must be `[]` else → `drop`; unplaceable → `drop` (item and op removed) |
| device (4) vs pipe/column/riser | `shift_device`: `o ± k·150`, k = 1..4, ordered away from the higher element's projection on the device's wall (tie `+`); first legal (run, not back-to-back) wins; its drop and the raceway tree are recomputed; none → `drop` (device + drop) |
| conduit (4) vs pipe/column/riser | `reroute_conduit`: forbid graph edges intersecting `higher.polygon.buffer(50)`; re-run Dijkstra; unchanged or unreachable → `drop` (conduit only, info) |
| stack/along pipe (1) vs column/riser (0) | `relocate_stack`: exclude the stack's wall, re-run P-1..P-4 for that stack's fixtures (residual set), rebuild its tree; recompute zones and re-route affected conduits; no candidate wall → `status = "blocked"` |
| unknown id (Phase B) vs known | unknown treated as priority 0 (`revit:<ElementId>` from the plugin); the known element re-plans per its row; both unknown → 422 `clash_pair_unknown` |
| same priority | exempt by PIN-24, or (furniture, furniture — cannot occur after Phase 5) → `blocked` |

**Progress guarantee:** after an action, the lower element's canonical hash must differ; if not, escalate once (obstacle = higher AABB + 300; device k → 5..8) and then `drop` in the same round. Ids are never re-assigned. All actions logged with `before/after` and `changed`.

### 4.5 Budget state machine (PIN-29; SI-6)
```
merge(iterations_used=u0, iteration=k, prior_actions, clash_pairs):
  plan = interior ⊕ mep; replay prior_actions
  u = u0
  if clash_pairs:                          # Phase B trigger
      if u ≥ 3: return budget_exhausted
      apply actions for each pair (sorted); u += 1
  loop (bounded by MERGE_BUDGET):
      clashes = phase_a(plan); if blocked pair: return blocked
      if not clashes: validate_layout(plan.layout) == [] else 422 merge_internal
                      return clean(ops = plan.ops + [run_interference_check], iterations_used = u)
      if u ≥ 3: return budget_exhausted(clash_report)
      apply actions for all clashes; u += 1
```
Gateway: after `rolled_back` with `interference`, the next `merge-commit2` on the same chain sends `iterations_used = prior.content.iterations_used`, `iteration = prior.content.iteration + 1`, `prior_actions = [...prior.content.prior_actions, ...prior.content.actions] (cumulative: each commit2_merge review stores the prior_actions it was built from)`, `clash_pairs`; if `iterations_used ≥ 3` → `commit2_failure{merge_budget_exhausted}` + 409 without calling the compiler. Consequence: two rollbacks → plan 3 commits (`used = 2`); four rollbacks → REVIEW. Deterministic ordering everywhere; wall clock only at the request boundary with `deadline_check` inside.

### 4.6 Phase 5 handoff amendment (PIN-37)
The interior half of Commit #2 is `interior_plan.content.ops` verbatim **unless** a Phase A/B re-plan moves or drops furniture; then `interior.ops_verbatim=false`, `replan_deltas[]` lists each item (from/to/reason), the card shows them, and the human's `commit2_merge` approval is the anchor for the moved items. The commit2 snapshot is the re-planned furnished layout (validator-clean).

### 4.7 SVGs
`replay.render_mep_svgs(commit0_layout, commit1_ops, interior_ops, mep_ops)` and `render_merge_svgs(..., merged_ops)` through the sim's canonical renderer; the replay is also the preflight (any `OpError` → 422 before a card exists). Generator asserts `svgs.commit1` pane == `phase5_2br_furnished.svg` bytes when no furniture moved.

---

## 5. Gateway flow & state machine

### 5.0 Merge chain (PIN-28)
`chain = (I, M)` = latest `interior_plan` (approved, `content.brief_version == latestConfirmedBrief`) and latest `mep_plan` (approved, `content.interior_review_id == I`, `counts.blocking == 0`). `repos.mergeChain(projectId)` returns `{interior, mep, merges: commit2_merge reviews with content.interior.review_id==I && content.mep.review_id==M ordered by created_at, latest, envelope: latestEnvelopeForReview(latest.id) by issued_at, failed: any commit2_failure for this chain with a hard code, exhausted: latest.content.iterations_used ≥ 3 && envelope.rolled_back-interference}`.

### 5.1 Ladders (each code is a test)
`POST /projects/:id/plan-mep`: 404 `unknown_project` → 503 `layout_compiler_unavailable` → commit0 snapshot else 409 `commit0_not_done` → commit1 else 409 `commit1_not_done` → `hasSnapshot(commit2)` → 409 `commit2_already_done` → a Commit #2 envelope `issued|ack_accepted` → 409 `commit2_envelope_in_flight` → `interiorPlanReady` else 409 `{interior_plan_not_ready, reason: none|pending|rejected|stale_brief}` → body zod `{confirmations?: {panel?: [n,n], slab_to_slab_mm?: 2100..6000}}` (absent → latest `mep_plan.content.confirmations`) → panel within 600 of a wall else 422 `panel_not_on_wall` → `planMep(...)` with `placer_wall_ids` from `interior.content.diagnostics.items` → 422 → `createReview(mep_failure, {...}, false)` + event + 422 → `createReview(mep_plan, {...MepPlan, brief_version, interior_review_id, interior_content_hash, confirmations}, config.autoApprove)` → 201 `{review_id, content_hash, status, counts, blocking: [codes]}`. Re-runs allowed (latest wins). UI form variant → same → 302.

`POST /projects/:id/merge-commit2`: 404 → 503 → commit0/commit1 → `commit2_already_done` → in-flight → `interiorPlanReady` → `mep = latestReviewOfKind(mep_plan)`: null → 409 `no_mep_plan`; not approved → 409 `mep_plan_not_approved`; `interior_review_id ≠ I` → 409 `mep_plan_stale`; `counts.blocking > 0` → 409 `mep_review_items_open {codes}` → any pending `commit2_merge` (any chain) → 409 `merge_review_pending {review_id}` → `chain.failed` → 409 `merge_chain_failed` → `chain.latest`:
- none, or latest rejected → `iterations_used 0, iteration 1, prior_actions [], clash_pairs []`
- latest approved, envelope none | `issued` | `ack_accepted` → 409 `merge_review_awaiting_issue`
- envelope `ack_rejected` | `expired` | `rolled_back` non-interference-transient (`expired_ttl`) → 409 `merge_review_reissuable` (use `issue-commit2`)
- envelope `rolled_back` with interference → `iterations_used = latest.content.iterations_used`; `≥ 3` → `createReview(commit2_failure, {reason: merge_budget_exhausted, ...}, false)` + 409 `merge_budget_exhausted`; else call with `iteration + 1`, `prior_actions`, `clash_pairs` (from the envelope row)
→ `merge(...)` → 422 → `commit2_failure` + 422; `budget_exhausted|blocked` → `commit2_failure{status, clash_report}` + 409 `merge_review_required {status}`; `clean` → **verify** (§5.2) → `createReviewTx(commit2_merge, {...MergeResult, brief_version}, config.autoApprove)` → 201 `{review_id, content_hash, status, iteration, iterations_used, counts, clash_summary}`.

`POST /projects/:id/issue-commit2`: 404 → commit0/commit1 → `commit2_already_done` → `review = chain.latest` approved else 409 `no_merge_review | merge_review_not_approved` → review chain ≠ current (I, M) → 409 `merge_review_stale` → envelope `issued|ack_accepted` → 409 (existing one-in-flight) → envelope `rolled_back` with interference → 409 `merge_review_consumed` → re-issues of this review ≥ 3 → 409 `merge_review_reissue_exhausted` + `commit2_failure` → `issueEnvelope(reply, id, {ops: review.content.ops, commitLabel: "Commit #2", approvalRef: {review_id, content_hash}, seqPolicy: "next_issued"})` (PIN-30); event payload carries `reissue_of` when a prior envelope exists for the review.

Other guards: `POST /projects/:id/furnish-layout` → 409 `commit2_already_done` / `commit2_envelope_in_flight`. `POST /projects/:id/envelopes` → 422 `approval_ref_required` when `commit_label` matches `/^Commit #/` or ops contain `run_interference_check|place_family|place_device|create_pipe|create_conduit` without `approval_ref`.

### 5.2 Verification of a MergeResult before it becomes a review
`mergeResultSchema`: `ops[].op ∈ {place_family, place_device, create_pipe, create_conduit, run_interference_check}`, `ops.length ≤ 1000`, exactly one trailing `run_interference_check`; every other op id ∈ ids(interior.ops) ∪ ids(mep.ops); ops whose id is not named by an `actions[]` row deep-equal (JCS) the approved branch op; `dropped ⊆` branch ids; embedded `interior/mep.content_hash` equal the live rows. Violation → `createReview(commit2_failure, {code: merge_ops_unverified, detail}, false)` + 422; never a card.

### 5.3 WSS consumers and transactions
- `core.ts register()`: `session.queue = session.queue.then(() => this.onMessage(...))` — frames per executor processed in arrival order; handlers stay idempotent and order-independent (tested both orders).
- `repos.recordCommitResult` (one transaction, project-scoped UPDATE): resolve `rv = reviews[approval_ref.review_id]`; if `rv.kind == 'commit2_merge'`: committed → `insertSnapshot(commit2, layout = rv.content.layout, reviewId)` + event `commit2_done {merge_review_id, iterations_used}`; rolled_back → `errors = r.errors`; if `errors.some(code == 'interference')` → `clash_pairs = parse "A~B" from those errors` (authoritative); other codes → if hard code → `createReviewTx(commit2_failure, {envelope_id, errors}, false)`. Branches (`interior_plan`, `mep_plan`) are never touched; the snapshot stays at commit1.
- `clash_delta` → `repos.recordClashDelta(projectId, envelope_id, pairs)`: `UPDATE envelopes SET clash_pairs = merge(existing, pairs) WHERE envelope_id=$1 AND project_id=$2`; ≤ 256 pairs, ids matching `^([A-Z]{1,2}-[0-9]{2,4}|revit:[0-9]+)$` and (for HUB ids) present in the review's ops; unknown envelope → event only.
- `recordAck(accepted=false)` and `expireStaleEnvelopes()` need no Commit #2 logic: the ladders read envelope status.
- `withTransaction(fn)` + `createReviewTx(client, …)` so review + event writes are atomic where required.

### 5.4 `GET /state` additions
```ts
mep_plan_ready: boolean   // latest mep_plan approved && interior_review_id === I && interior_plan_ready && counts.blocking === 0
commit2_done: boolean
commit2: { chain: {interior_review_id, mep_review_id} | null, iteration: number|null, iterations_used: number, budget_limit: 3, budget_remaining: number,
           merge_review_id: string|null, merge_status: "none"|"pending"|"approved"|"rejected",
           envelope_status: null|"issued"|"ack_accepted"|"ack_rejected"|"committed"|"rolled_back"|"expired",
           clash_pairs: {a_id,b_id}[]|null, last_errors: unknown[]|null, exhausted: boolean, failed: boolean, merge_current: boolean }
```

### 5.5 UI cards
`mep_plan`: `svgs.commit1` vs `svgs.mep`; counts; stacks table (id, wall, offset, Ø, FU, fixtures, snapped); review items (blocking rows highlighted); confirmations form (panel x/y, slab_to_slab_mm) posting to `/ui/projects/:id/plan-mep` when blocking items exist. `commit2_merge`: `svgs.commit1` vs `svgs.merged`; iteration/budget; clash report; actions/`replan_deltas`/dropped; `interior.ops_verbatim` badge. `mep_failure`/`commit2_failure`: raw JSON + reason banner. `config.autoApprove` applies only to `mep_plan` and `commit2_merge`; failure kinds are hard-coded `false`.

---

## 6. Sim changes (`tools/revit-sim`) — goldens 1–5 byte-stable

1. `Catalogs` gains `wall_thickness`, `pipe_types` (from `mep_types.json`), `kind_by_family_type`, `clash_prisms` (from `clash_prisms.json`); `_op_place_device` uses the host's catalog thickness (replaces `100.0`; face_left kept unless the op carries `face`); `_op_create_pipe` rejects `pipe_type ∉ pipe_types` (`unknown_revit_type`) and any segment with 3D length < 1e-6 (`invalid_path`); `level` deliberately unchecked (Commit #0 replay parity); `_op_delete_element` learns pipes/conduits.
2. `revit_sim/clash.py` (pure): `element_boxes(model, catalogs)` (families with kind heights, devices, pipes, conduits, columns, risers; **no walls/doors/windows**), `exempt(a, b)` from the shared table, `find_clashes(boxes, created: set|None)` strict `<` on all axes, created × all. `SimModel.envelope_created` set by the executor on the working copy before the op loop, reset to `None` after commit; direct `model.apply` callers (Phase 5 golden test) see the all-pairs superset — `test_interior_golden` and `test_atomicity` keep passing. First pair in `(created order, sorted other id)` → `OpError("interference", "A~B")` → existing `commit_result rolled_back` + `clash_delta` path.
3. Renderer append-only (walls→doors→windows→families→devices→pipes→conduits→stacks; `_f` formatting; groups `sorted()`); viewBox grows only when MEP elements exist. Device: `receptacle` circle r 60 white/stroke black 15 + horizontal tick; `gfci` circle + filled 50×50 square; `switch` 100×100 white rect + diagonal. Pipe: `polyline class="pipe {system}" data-d` stroke `#1f4e9c` sanitary / `#2e8b57` vent / `#c0392b` supply_h / `#1f9cc0` supply_c, width `max(Ø,20)`. Conduit: `#e08a00` width 20 dashed `120 60`. Stack marker: vertical sanitary pipe → circle r Ø/2+40 + cross. A test re-renders all four goldens and asserts equality.
4. Test hook: `Executor(test_hooks: TestHooks | None = None)`; `SimClient` constructs `TestHooks()` **only** when `--control-port` is given; control verb `inject_clash <n> <a_id> <b_id>` (`inject_clash 0` clears) → for `run_interference_check`, if `n > 0` and both ids ∈ `working.all_ids()` → `n −= 1`, raise `OpError("interference", "a~b")` before the real check. Unit tests: `Executor().test_hooks is None`; `inject_clash` refused without hooks; unknown ids ignored; `test_no_env_reads` (AST) over `revit_sim`.

---

## 7. Plugin (compile-only Addin; Core tested)

**Core** (`ChapterHub.Core`): `PipePath.cs` — `Classify(IReadOnlyList<Pt3>) → (segments, bends)`: zero-length → `PipePathError("zero_length")`; bend within 0.5° of 90/45 → supported; else `"fitting_unsupported"`; `MergeCollinear`. Pinned by `packages/contracts/fixtures/pipepath/manifest.json` read by `PipePathTests.cs` and `mep/fittings.py`. `ClashPairs.cs` — reverse lookup `ElementId → logical id` over `Delta ∪ IdMap`; misses → `revit:<ElementId>`. `ClashExemptions.cs` — category-pair table loaded from `clash_prisms.json` (Core test asserts equality with the Python table).

**Addin handlers** (`Ops/Handlers.cs`): `PlaceFamilyHandler` (required — interior ops hit `NotImplementedOpHandler` today): symbol over `OST_Furniture ∪ OST_PlumbingFixtures ∪ OST_Casework ∪ OST_SpecialityEquipment ∪ OST_ElectricalEquipment`, `NewFamilyInstance(XYZ(center, level.Elevation), symbol, level, NonStructural)` + `RotateElement` about Z. `CreatePipeHandler`: `PipingSystemType` by `mep_types.system_type_names[system]`, `PipeType` by `pipe_type`, `Pipe.Create` per segment (mm→ft), `RBS_PIPE_DIAMETER_PARAM`, `NewElbowFitting` for 90/45 per `PipePath.Classify`, else `OpFailure("fitting_unsupported")`; id-map PIN-35. `CreateConduitHandler`: `mep_types.conduit_type`, `Conduit.Create` per segment, same policy. `PlaceDeviceHandler`: honours `face` when present (GetSideFaces Interior/Exterior chosen by matching `Placement.Place` within 1 mm), else face_left; family names from `mep_types.device_families`. `CreateDoorHandler`: apply `swing`/`flip_facing` via `flipHand()`/`flipFacing()` against the start→end convention (Phase 5 committed ops carry `flip_facing`; validated in the spike). `RunInterferenceCheckHandler`: `doc.Regenerate()`; candidates = `context.Delta` (created set) vs created ∪ id-mapped elements, `ElementIntersectsElementFilter`, excluding walls/doors/windows/levels categories, exempt category pairs, connector-joined pairs and elements sharing a logical id; first hit → `OpFailure("interference", "A~B")` with logical ids. `EnvelopeHandler`: errors carry `op_index`; after `commit_result rolled_back` for `interference`, send `clash_delta {envelope_id, pairs:[{a_id,b_id,kind:"hard_interference"}]}` (sim order).

**`docs/MANUAL_REVIT_TEST.md`** — keep the open `## Pre-Phase-6 spike` (now also: "receptacle lands on the ROOM-side face — decides Q1") and add:
```
## Phase 6 gate (MEP + Commit #2)
- [ ] Pre-Phase-6 spike rows ticked (create_pipe two segments + elbow; create_door + place_device face-hosted 380 AFF; routing preferences loaded); record which walls need `face`.
- [ ] Golden Commit #2 envelope (fixtures/goldens/phase6_2br_mep.json ops) on the post-Commit-#1 model: 18 families at mm centres/rotations, stacks + branch tree with slopes, devices at 380/1150/1220 AFF, raceway tree at 2600 with drops; `commit_result committed`; id-map grows by the op count.
- [ ] Wye/tee fittings completed manually per `wye_manual`/`conduit_fittings_manual` items; time recorded; template routing-preference gaps noted.
- [ ] Interference: place a test family overlapping a committed conduit drop, re-issue → `rolled_back {interference}` + `clash_delta` with logical ids; TransactionGroup rolled back; merge-gate iteration k+1 card appears; the re-planned envelope commits.
- [ ] Fire-rated wall in the template → conduit route detours (compare `home_runs[].penetrations`).
- [ ] Ctrl+Z after Commit #2 → state_divergence.
```

---

## 8. Fixtures & goldens

Inputs (`golden_mep.py`): `PANEL = [8050.0, 5200.0]` (foyer, inside face of W-019 → panel foot `(8000, 5200)`), `SLAB_TO_SLAB_MM = 3000.0` (`h_plenum = 300`), `INJECTED_PAIRS = [("E-001","P-001")]×2` (recovery) and `×4` (exhaustion). Chain is flag-free, riser-free, casework-free; no `meta.levels`/`meta.electrical` → both come from confirmations and are stamped.

**Predicted under the defaults (≈; `gen_golden_mep.py` is the sole source of truth — copy nothing by hand):**
- Wet rooms R-003, R-007, R-011 (+ derived R-009). Fixtures F-006 wc 4 FU Ø76, F-007 lav 1 FU Ø32, F-012 wc 4 FU Ø76, F-017 sink 2 FU Ø38, F-018 DW 2 FU Ø38. L_max 7115.4 / 5673.1 / 5384.6.
- P-1 iteration 1: W-004 9.0 (W-001/W-003/W-025 5.0; nine walls 4.0) → serve {F-006, F-007, F-012}; t_s 0.4503 → **S-1 = P-001 on W-004 at (5133.3, 7000), Ø76**; along 4533.3 / 4533.3 / 5666.7 all ≤ L_max → no prune. Full paths 7308.3 / 4858.3 / 7670.7 → `branch_plenum_marginal` ×2 (F-006 ≈ 2.0 mm, F-012 ≈ 5.8 mm). Iteration 2: kitchen walls tie at 4.0 → wet walls W-026/W-027 → Σ FU·dist 6740 < 7403.6 → W-026; t_s → 450 inside D-011's span [244.5, 955.5] → snapped to **169.0** → **S-2 = P-002 at (4800, 169), Ø51**, `p3_snapped`. Branch tree: W-004 — (600,4225)→(600,6675) [F-006], (600,6675)→(600,7000) [F-006+F-007], (600,7000)→(5133.3,7000), (10800,4996)→(10800,7000) [F-012], (10800,7000)→(5133.3,7000); W-026 — (6860,450)→(6110,450) [F-018], (6110,450)→(4800,450) [both], (4800,450)→(4800,169). **10 `create_pipe`**; `wye_manual` ×5.
- Devices ≈ 45 (E-1 ≈ 28, corridor 1–2, laundry 1, E-2 counter 2, E-2 basin 1, appliances 3, switches 10–11 with D-013 via corner fallback); right-face devices listed in the gate note (`device_face_unavailable`). E-4: ≈ 81 nodes, two exclusion squares, 0 penetrations, ≈ 45 drops + ≈ 15 trunk chains.
- Commit #2 ops ≈ 18 + 10 + 45 + 60 + 1; Phase A **0 clashes** (asserted, not "by construction": the generator runs the sweep and the real sim check).
- Recovery: injected (E-001, P-001)×2 → `shift_device` 1912.5 → 1762.5 → 1612.5 (away from P-001's projection at W-001 offset 7000), Q-001 recomputed; commits at plan 3 with `iterations_used = 2`, seqs 3 → 4 → 5.
- Gate note (`P4_L_INCLUDES_DRAIN_LEG = True`): F-012 pruned (7670.7 > 7115.4) → t_s over {F-006, F-007} → S-1 at (600, 7000); residual F-012 → W-023 → S-2 (10200, 4996); kitchen S-3 (4800, 169) → **3 stacks**.

**Golden files** (all written by `scripts/gen_golden_mep.py`, eyeballed once, byte-pinned by `tests/test_mep_golden.py`): `fixtures/goldens/phase6_2br_mep.svg` (merged plan: device symbols, pipe/conduit polylines, stack markers), `phase6_2br_mep.json` (MepPlan minus svgs/diagnostics), `phase6_2br_clash_report.json` (plan-1 merge `clash_report` + counts — the demo's clash report), `phase6_2br_recovery.json` (plans 2–3 actions/ops diff/clash reports), `phase6_2br_recovery.svg` (post-Commit-#2 sim plan after recovery), `phase6_2br_gate_note.json` (alternative stack tables for PIN-08/13, right-face device ids, extension counts). Generator asserts: compile → furnish → plan_mep → merge(plan 1) `clean`; tables ⇔ ops; every op registry-valid; `validate_layout(merge.layout) == []`; `svgs.commit1 == phase5_2br_furnished.svg`; real `SimModel` replay incl. `run_interference_check` commits; two-run byte determinism; recovery replay reproduces the pinned shifts; then writes the six files. `scripts/demo_phase6.py` → `out/phase6/{mep_plan.svg, merged_plan.svg, ops.json, clash_report.json, review_items.json, gate_note.json}`.

---

## 9. Tests

`services/layout-compiler/tests/`:
- `test_mep_receptacles.py`: `test_e1_property_spacing_epsilon` (hypothesis L ∈ [610, 40000], S ∈ [1, 8000], a = 1830: pre-dedupe gap ≤ S+1 and ends ≤ a+1; post-dedupe no pair < 300−1e-6, ends ≤ a+150+1, coverage: every run point within max(a, S/2)+300 of a kept device; N=1 ⇒ [L/2]); `test_e1_exact_limits` (L = 2a, 2a+S land exactly on limits, ≤ with 1 mm epsilon); `test_e1_n1_branch`; `test_e1_dedupe_general`; `test_e1_runs_ge_610_get_one`; `test_e1_windows_break_only_at_height`; `test_e1_counter_interval_removed`; `test_outlet_spacing_below_610_blocking`; `test_corridor_single_receptacle`; `test_laundry_single_gfci`; `test_room_without_receptacle_item`.
- `test_mep_counters.py`: `test_e2_counter_circuit` (casework `is_counter` run 3000 → spacing ≤ 1220+1, inset ≤ 610+1, all gfci at 1150, sill-900 window breaks); `test_e2_counter_fallback_sink_dw_only` (range extent subtracted); `test_e2_bathroom_gfci_within_914`; `test_gfci_area_rule` (no `receptacle` on counter walls or in bath/powder/laundry).
- `test_mep_plumbing.py`: `test_p4_lmax_forces_second_stack`; `test_p4_size_dependent_slope`; `test_p4_leg_switch_changes_selection` (both constants); `test_p1_wet_wall_consolidation` (shared 152 wall scores 9 vs 5 vs 4); `test_p1_riser_bias_unit_sanity` (hypothesis d ∈ [0, 20000]: 0 ≤ λd ≤ 10 FU, λ·1000 == 0.5, same order as 1–20 FU; mutation λ = 0.5 fails); `test_p1_riser_bias_decides_tie`; `test_p1_excludes_si8_walls`; `test_p1_tiebreak_order_independent`; `test_p3_fu_weighted`; `test_p3_snap_out_of_door_span`; `test_p1_iterations_exceeded_is_blocking`; `test_branch_tree_no_overlapping_segments`; `test_branch_zprofile_and_marginal_item`; `test_fixture_never_moves`; `test_plenum_too_shallow_blocking`.
- `test_mep_switches.py`: `test_e3_latch_side` (swing L/R × flip on wall (0,0)→(3000,0), door 1500/900 → 2100 / 900, swept-side room, 1220 AFF); `test_e3_corner_fallback` (D-013 geometry); `test_e3_hinge_fallback_flagged`; `test_e3_unplaceable`; `test_backtoback_shift`.
- `test_mep_routing.py`: `test_e4_route_avoids_wet_stack_prism` (no path node inside the ±300 square; detour or `device_unroutable`); `test_e4_fire_rated_penalty_4000` (3000 mm detour chosen; 5000 mm → straight with `penetrations == 1`, `cost == length + 4000`); `test_e4_tjunction_turn_in_penalized`; `test_e4_demising_counts_as_rated`; `test_e4_panel_fallbacks` (meta → riser → confirmation → `panel_missing`); `test_e4_node_canonicalization_1mm`; `test_e4_raceway_tree_unique_segments`; `test_e4_states_bounded`; `test_e4_deterministic_ties`.
- `test_mep_inputs.py`: levels/panel stamping into `meta`, D1 assertion, wet-room derivation, placer host wall + fallback, counter-wall derivation, `fixture_semantics_from_catalog_not_names` (AST: no `revit_family`/`revit_type` string comparison in `mep/`), `face_emitted_iff_registry_declares_it`.
- `test_merge_clash.py`: `test_injected_clash_resolves_within_3`; `test_budget_exhausted_reviews`; `test_shared_budget_mixed` (Phase A 1 + two rollbacks commit; a third rollback exhausts); `test_progress_guarantee_noop_escalates_to_drop`; `test_relegalize_uses_preplaced` (item cannot land on other furniture); `test_relocate_stack_on_structure`; `test_same_priority_blocked`; `test_replay_prior_actions_deterministic`; `test_ids_never_renumber`; `test_phase_a_equals_sim_law` (property on random models: oriented pairs ⊆ sim AABB pairs; exemptions identical); `test_exemption_table_shared_fixture`; `test_validator_rerun_after_replan`.
- `test_mep_golden.py` (six files; real-sim replay commits; recovery pinned); `test_fittings_conformance.py`; `test_server.py` (`/plan-mep`, `/merge` shapes, `extra=forbid`, 422 codes); `test_mep_determinism.py` (AST: no `random`/`time`/`os.environ` outside `plan.py`/`gate.py`; `test_deadline_interrupts_solver` via a counting callback); `test_legalize_furniture_defaults_keep_phase5_bytes`.

`tools/revit-sim/tests/`: `test_clash_law.py` (boxes, exemptions, created-set scope, legacy family behaviour identical on the Phase 5 golden, committed-model reset), `test_inject_clash.py` (hook absent by default; refused without control port; pops per check; order `[ack, commit_result, clash_delta]`), `test_svg_mep.py` (symbols, stack marker, **all four goldens re-rendered unchanged**), `test_mep_ops.py` (pipe_type / zero-length rejection), `test_no_env_reads.py`.

`services/gateway/tests/`: `commit2-routes.test.ts` (one suite for plan-mep, merge-commit2, issue-commit2 and the WSS frames: full ladder codes; confirmations carry-forward; `panel_not_on_wall`; blocking → `mep_plan_ready=false` even when auto-approved under CI; UI form; `mep_failure` never auto; ladder incl. every envelope status; stub `/merge`; `simulateRollback(envelopeId, errors, pairs?)`; iteration/`iterations_used` progression; `merge_budget_exhausted` after the fourth rollback; `merge_review_consumed`; `merge_review_stale` after a newer `interior_plan`/`mep_plan`; fresh chain resets the budget; `merge_ops_unverified`; `reissuable` for `expired_ttl`/`ack_rejected`/`expired` with cap; `commit2_failure` for hard codes; commit2 snapshot layout == content.layout; `commit2_already_done` for furnish/plan-mep/merge/issue; `approval_ref_required` on `/envelopes`; envelope ops == review content ops by JCS; fresh seq and `reissue_of`), `core.test.ts` (`commit_result`/`clash_delta` in both orders; per-session serialization; `clash_delta` clamp and project scoping).

`plugin/ChapterHub.Core.Tests/`: `PipePathTests.cs`, `ClashPairsTests.cs`, `ClashExemptionsTests.cs`; `RegistryCoverageTests` unchanged; CI `dotnet build` covers the handlers.

`tests/e2e/phase6.e2e.test.ts` (5 children, sim `controlPort: true`): chain to approved `interior_plan` (as phase5) → `plan-mep {}` → 201 `blocking: ["levels_missing","panel_missing"]` → approve → `merge-commit2` → 409 `mep_review_items_open` → `plan-mep {confirmations}` → 201; `content.ops` deep-equals `phase6_2br_mep.json.ops`; `svgs.mep` == `phase6_2br_mep.svg`; approve → `merge-commit2` → 201 plan 1, `clash_report` == `phase6_2br_clash_report.json` → approve → `inject_clash 2 E-001 P-001` → `issue-commit2` 202 seq 3 → `waitForState(commit2.envelope_status === "rolled_back" && commit2.clash_pairs)` → `merge-commit2` → plan 2 (`actions[0].action === "shift_device"`, `replan_deltas` non-empty / ops differ for E-001) → approve → issue seq 4 → rolled back → plan 3 → approve → issue seq 5 → `waitForState(commit2_done)`; `last_committed_seq === 5`; `recent_envelopes` = [committed, committed, rolled_back, rolled_back, committed]; branches still approved; `layout_snapshots` = commit1 unchanged + commit2; sim `current_plan.svg` == `phase6_2br_recovery.svg`. Second `it` (fresh project): `inject_clash 4 …` → after the fourth rollback `merge-commit2` → 409 `merge_budget_exhausted`, pending `commit2_failure`, `commit2.exhausted`; `plan-mep` again → new `mep_plan` → approve → `merge-commit2` → 201 plan 1 (fresh chain). `api.ts` gains `planMep`, `mergeCommit2`, `issueCommit2`, `approveReview` confirmations, `stateSchema` fields. `make demo-phase6` = `vitest run phase6` + `demo_phase6.py`.

---

## 9a. Post-review amendments (adversarial review of the built branch)

The 46-agent review of the implemented branch confirmed 17 findings; the fixes change three
pinned details of this document, recorded here so §4/§5 are read with them:

- **Conduit and pipe ids (amends §4.4 / PIN-27).** Drop conduits are `Q-n` for device `E-n`
  and never renumber; trunks renumber from a fixed base (1 + highest device number) on every
  raceway re-run and never reuse an id the merge dropped; a dropped trunk's GEOMETRY stays
  forbidden, so a device whose only home run used it is dropped and reported (`dropped`,
  `replan_deltas`, a `drop` action) rather than left conduit-less. Pipes are derived state
  whenever P-1..P-4 re-run — after `relocate_stack` or after a plumbing fixture moved/dropped
  (recorded as a `replan_plumbing` action) — and their ids may renumber.
- **Verifier (amends §5.2).** "Every un-actioned op deep-equals the approved branch op" holds
  for furniture and devices; conduits are always derived, pipes are derived after a
  `relocate_stack`/`replan_plumbing` action; in addition every approved op must survive, be
  in `dropped`, or be derived (completeness), and the echoed branch `review_id`s must match
  the live rows. `POST /envelopes` with commit-class ops requires an `approval_ref` that names
  THIS project's approved review with the same content hash and ops (SI-2), not merely a
  well-formed ref.
- **Device shifts (amends §4.4 / PIN-26).** A shifted device must also clear every stack's
  ±300 E-4 square on its wall; `k = 1..4` failing escalates to `k = 5..8` before the drop.
  Phase A acts on LIVE pairs (the sweep is repeated before each action of a round);
  structure/structure pairs are existing conditions, never clashes.
- **Executors.** The plugin sweeps created × the whole document (clash categories), reports
  `revit:<ElementId>` for elements the HUB never created, and puts the bare `"A~B"` on the
  wire; `commit_result`/`ack` are project-scoped in the gateway; the sim's device boxes use
  the as-built thickness like Phase A.

## 9b. Live-spike amendments (stage 1, 2026-09-03)

Stage 1 of `docs/REVIT_SPIKE.md` ran on Eran's dev-only workstation (Revit 2027.2, AUTOM8LABS
connector, throwaway model); results in `docs/REVIT_SPIKE_RESULTS.md`. No contract, catalog,
sim, gateway or golden changed; the plugin changed as follows (amends §7):

- **Face law confirmed.** Exterior/finish face = LEFT of start→end, proven geometrically for
  both draw directions — `Placement.Place("face_left")` and the D1 wall convention stand.
  `PlaceDeviceHandler` chooses the face geometrically (outward normal on the named side AND
  within 1 mm of the law's point), never by shell layer, so `Wall.Flipped` cannot move a
  device; a placement that comes back unhosted (the connector did exactly that, silently, at
  z = 0) fails `unhosted`, as does a door not hosted by its wall.
- **Door flips from orientation vectors, not flags.** `CreateDoorHandler` no longer sets
  HandFlipped/FacingFlipped from `swing`/`flip_facing`: those flags are relative to the family's
  authoring and to `Wall.Orientation` (a fresh door faces the wall's exterior, negated on a
  flipped wall). It computes the desired world directions from the swing.py law
  (`ChapterHub.Core.DoorOrientation`: hinge toward start for L, leaf sweeps the left normal
  unless `flip_facing`), flips on a negative dot product, re-reads, and fails `door_flip_failed`
  if either direction still disagrees. Declared assumption, verified in stage 2 against
  Chapter's real door family: Door.rft authoring — hinge at family −X, swing to family +Y
  (HandOrientation = hinge → latch).
- **Fittings are a template prerequisite.** The stage-1 pipe type carried no elbow family and
  `NewElbowFitting` failed ("failed to insert elbow"). The handlers preflight
  (`RoutingPreferenceManager` elbow rules for pipes, `ConduitType.Elbow` for conduits →
  `routing_preference_missing`) and wrap the insert (`fitting_insert_failed` carrying Revit's
  text). Both are hard codes in the gateway (anything but `interference`/`expired_ttl`) →
  `commit2_failure`, correct because re-issuing cannot fix a template. Tees stay `wye_manual`
  (the connector could not route them either).
- **Sizes bind to the type's table.** A literal 76 mm produced OD = ID = 76 (no 3" binding) and
  21 mm displayed as 7/8". `ChapterHub.Core.MepSizes` snaps to the nearest segment /
  conduit-standard nominal within 2.5 mm (76→76.2, 51→50.8, 38→38.1, 32→31.75, 21→19.05 = ¾" EMT),
  else `unknown_size`; a type without any table keeps the literal value. The sim has no tables
  and keeps the literal Ø — Revit's real OD (3" steel = 88.9) exceeds the Phase A prism, a gap
  Phase B recovery covers by design. Gate note: `E4_CONDUIT_DIAMETER_MM = 21` and
  `mep_types.conduit_diameter_mm: 21` should become the real trade size when the vocabulary
  lands (golden re-run then).
- **Interference law confirmed.** Revit does not flag end-to-end touching (strict overlap only),
  matching Phase A, the sim and `ElementIntersectsElementFilter`; it does flag unmitred pipe
  corners, which cannot arise once elbows insert (same-run pairs are skipped anyway).
- **Template gaps → standing asks.** No door, window or electrical-fixture families, no PVC
  pipe type, no pipe elbow, local family library not installed; the observed real names
  `Sanitary` (piping system type) and `Conduit with Fittings : Conduit` (EMT) are candidates
  for Eran's `mep_types.json`, never written by us.

---

## 10. Build order, risks

### 10.1 Commits (one PR, `claude/phase-6-mep`; `make verify` + `make e2e` green at each)
1. `feat(contracts): catalogs/mep_types.json placeholders, catalogs/clash_prisms.json defaults, fixtures/pipepath manifest, README rows` (no schema change).
2. `feat(sim): MEP rendering + catalog wall thickness for place_device + pipe_type/3D-length checks + delete pipes/conduits` — asserts goldens 1–5 unchanged.
3. `feat(sim): revit_sim.clash law (created×all 2.5D, shared exemptions), TestHooks inject_clash, no-env AST test`.
4. `feat(layout-compiler): mep inputs (levels/panel stamping, wet rooms, host walls) + wall runs + plumbing P-1..P-4 + branch tree`.
5. `feat(layout-compiler): electrical E-1/E-2/E-3 + corridor/laundry + appliances + gfci area rule + dedupe`.
6. `feat(layout-compiler): E-4 routing (canonical graph, state Dijkstra, raceway tree) + fittings twin + ops emission`.
7. `feat(layout-compiler): plan_mep orchestration, /plan-mep, card SVGs`.
8. `feat(layout-compiler): merge gate — prisms, Phase A, re-plan actions, budget state machine, /merge; legalize_furniture(preplaced, obstacles)`.
9. `feat(layout-compiler): gen_golden_mep.py + six goldens + drift tests + demo_phase6.py`.
10. `feat(gateway): migration 0005, WSS serialization, plan-mep/merge-commit2/issue-commit2, chain state, verification, commit2 snapshot, state, cards, /envelopes guard, tests`.
11. `feat(plugin): Core PipePath/ClashPairs/ClashExemptions + tests; Addin place_family/create_pipe/create_conduit/run_interference_check/place_device face/door flips + clash_delta; MANUAL_REVIT_TEST Phase 6`.
12. `test(e2e): phase6 chain incl. recovery (2 rejects → commit) and exhaustion (4 rejects → REVIEW → fresh chain); make demo-phase6; CLAUDE.md status + gate items`.
Stop at the gate after 12.

### 10.2 Risk register
| risk | mitigation / observability |
|---|---|
| Literal P-1 puts the bath stack in unflagged exterior W-004 on the golden | PIN-05 bites on flagged scans; `p1_ranking` on the card; Eran Q3/Q8 |
| Spec-literal P-4 accepts branches whose full run exceeds the slope budget (F-006 2 mm, F-012 6 mm) | honest z-profile + `branch_plenum_marginal`; alternative table in the gate note; Q3 |
| `place_device` has no face → devices outside the building on W-001/W-004 | Q1 pre-build; `face` auto-emitted once the registry has it; gate note lists ids; spike row |
| Devices in stack squares are unroutable under the default | info item + count; `ZONES_BREAK_DEVICE_RUNS` alternative in the gate note |
| Real-Revit Phase B stricter than the sim (fittings, template) | plugin exemptions mirror the shared table; `doc.Regenerate()`; spike; `inject_clash` proves recovery end-to-end |
| Re-plan requires a fresh approval → recovery is two calls per iteration | PIN-31; AUTO_APPROVE keeps CI automatic; Q4 |
| Phase 5 placer lets furniture intrude into wall half-thickness | exempt pairs (PIN-24) keep Phase 6 unaffected; Q7 decides the Phase 5 fix |
| Placeholder families/pipe types will not resolve on the live template | standing catalog ask; Q2 |
| Determinism of shapely across platforms | all emitted numbers rounded 0.1; goldens generated on CI's pins; STRtree order never affects output |
| `legalize_furniture` seam touches Phase 5 | keyword-only defaults; Phase 5 goldens + 200-seed corpus unchanged (test) |

---

## Open questions for Eran (only what he can decide)

1. **Registry — `place_device.face: left|right` (pre-build, validated in the spike).** Without it every device is hosted on face_left and ~12 golden devices land outside the apartment or in the neighbouring room. Also: `kind: receptacle_240` or keep the 240 V designation report-only?
2. **Catalog vocabulary:** real Chapter names for `catalogs/mep_types.json` (DWV/vent/supply pipe types, conduit type, receptacle/GFCI/switch families, `PipingSystemType` names); review the engineering defaults in `catalogs/clash_prisms.json` (kind heights); a `_PLACEHOLDER` counter casework family so E-2 runs on `is_counter` (implies growing the Phase 4 golden emission with one casework run — a Phase 4/5 fixture change).
3. **P-4 routed length:** spec-literal `L = along` (default; golden 2 stacks, two `branch_plenum_marginal` items) vs `L = leg + along` (golden 3 stacks). Both stack tables are in `phase6_2br_gate_note.json`.
4. **Approval policy:** every rebuilt merged plan needs a new human approval (PIN-31, default) vs approve-once-and-auto-reissue-within-budget; and when the merge gate moves furniture, is the `commit2_merge` approval a sufficient anchor (PIN-37) or should the `interior_plan` review re-open?
5. **Contract text:** approve the registry prose amendment for `create_pipe` / `create_conduit` / `run_interference_check` `sim_behavior` ("2.5D created×all with shared exemptions", 3D zero-length rejection, `pipe_type` catalog check) — no schema change.
6. **Revit-machine steps:** run the (still open) Pre-Phase-6 spike before commit 11 is relied on; then the Phase 6 gate rows.
7. **Phase 5 spill-over:** the placer tests `covers` against centerline polygons, so F-008/F-011/F-019 intrude 46/75/51 mm into W-018/W-004/W-002, and F-019 partially blocks pocket door D-008's clear opening. Fix in Phase 5 now (re-pins Phase 5 goldens) or accept and carry?
8. **v1 MEP scope:** sanitary DWV only; supply/vent/gas are review items. Add `risers[].type ∈ {supply_h, supply_c}` and `create_pipe.system: gas` in a later phase?
9. **Bless or flip the ⚠ rows in Pinned decisions** (PIN-08, 12, 13, 16, 17, 20, 29, 30, 37) and the Part C placement (PIN-36). Each flip is one generator re-run.

---

## Acceptance → test name

| acceptance / rule | test |
|---|---|
| E-1 receptacle property, 1 mm epsilon on boundary comparisons | `test_mep_receptacles.py::test_e1_property_spacing_epsilon`, `::test_e1_exact_limits` |
| E-1 `N = 1` explicit branch at L/2 | `test_mep_receptacles.py::test_e1_n1_branch` |
| E-1 devices < 300 mm deduped to one; runs ≥ 610 get one | `::test_e1_dedupe_general`, `::test_e1_runs_ge_610_get_one` |
| E-2 counter circuit (a = 610, S = 1220, 1150 AFF, all gfci) | `test_mep_counters.py::test_e2_counter_circuit` |
| E-2 bathroom receptacle ≤ 914 from basin, gfci | `test_mep_counters.py::test_e2_bathroom_gfci_within_914` |
| GFCI per area (counter walls, bath/powder/laundry) | `test_mep_counters.py::test_gfci_area_rule` |
| E-3 latch-side switch (150 from jamb, 1220 AFF) | `test_mep_switches.py::test_e3_latch_side` |
| E-4 route avoids the wet-stack prism (±300) | `test_mep_routing.py::test_e4_route_avoids_wet_stack_prism` |
| E-4 fire-rated penetration penalty = 4000 mm equivalent | `test_mep_routing.py::test_e4_fire_rated_penalty_4000` |
| E-4 panel: meta → electrical riser → confirmation → REVIEW | `test_mep_routing.py::test_e4_panel_fallbacks`, `mep-routes.test.ts` (blocking `panel_missing`, UI form) |
| P-1 wet-wall consolidation; λ unit-sanity (bias same order as FU) | `test_mep_plumbing.py::test_p1_wet_wall_consolidation`, `::test_p1_riser_bias_unit_sanity` |
| P-3 FU-weighted stack position | `test_mep_plumbing.py::test_p3_fu_weighted` |
| P-4 L_max size-dependent slope; violation → second stack, residual re-run | `::test_p4_size_dependent_slope`, `::test_p4_lmax_forces_second_stack` |
| Fixture semantics from `kind`/`fixture_units`/`hookups` + plumbing.json, never family names | `test_mep_inputs.py::test_fixture_semantics_from_catalog_not_names` |
| Injected clash resolved in ≤ 3 iterations; shared A+B budget; REVIEW after | `test_merge_clash.py::test_injected_clash_resolves_within_3`, `::test_shared_budget_mixed`, `::test_budget_exhausted_reviews` |
| Lower priority re-plans; progress guaranteed | `::test_progress_guarantee_noop_escalates_to_drop`, `::test_relegalize_uses_preplaced`, `::test_relocate_stack_on_structure` |
| Phase A law == sim law (shared exemptions, oriented ⊆ AABB) | `::test_phase_a_equals_sim_law`, `revit-sim/tests/test_clash_law.py`, `ClashExemptionsTests.cs` |
| Phase-B recovery: sim rejects twice, third merged envelope commits | `tests/e2e/phase6.e2e.test.ts` "recovers after two rolled-back Commit #2 envelopes" |
| REVIEW fires on budget exhaustion; new mep_plan starts a fresh chain | `phase6.e2e.test.ts` "budget exhaustion → REVIEW → fresh chain"; `merge-routes.test.ts` |
| On rollback: branches retained, snapshot stays at Commit #1, re-issue under a fresh seq | e2e assertions on reviews/`layout_snapshots`/`recent_envelopes`; `merge-routes.test.ts` fresh-seq + `reissue_of` |
| Clash signal authoritative from `commit_result`; frames order-independent | `core.test.ts` both orders; `merge-routes.test.ts` `simulateRollback` |
| Envelope ops == approved review content ops (SI-2); `/envelopes` guard | `merge-routes.test.ts` JCS equality; `approval_ref_required` |
| Merge result provenance verified before review | `merge-routes.test.ts` `merge_ops_unverified` |
| No coincident same-system pipes; raceway tree unique | `test_branch_tree_no_overlapping_segments`, `test_e4_raceway_tree_unique_segments` |
| Every loop bounded and time-limited (SI-6) | `test_mep_determinism.py::test_deadline_interrupts_solver`, counters asserted in plumbing/routing tests |
| No LLM, no clock, no env in `mep/`, `merge/`, `revit_sim` | `test_mep_determinism.py` (AST), `revit-sim/tests/test_no_env_reads.py` |
| Op registry validity of every emitted op | `test_mep_inputs.py::test_ops_registry_valid`, generator assertion |
| Goldens 1–5 byte-stable | `layout-compiler/tests/test_interior_golden.py` + `test_mep_plan.py` (goldens 1–5 re-rendered through the sim's renderer, byte-pinned) and the phase1–5 e2e suites, `test_legalize_furniture_defaults_keep_phase5_bytes` |
| Demo: plan SVG with device symbols, pipe/conduit polylines, stack marker; clash report JSON | `make demo-phase6`; `test_mep_golden.py` |
| C#/Python pipe-path conformance | `PipePathTests.cs`, `test_fittings_conformance.py` |
| Pre-phase gate checklist (live `create_pipe`, `create_door`, `place_device`) | human — `docs/MANUAL_REVIT_TEST.md` Pre-Phase-6 spike + Phase 6 gate rows |
