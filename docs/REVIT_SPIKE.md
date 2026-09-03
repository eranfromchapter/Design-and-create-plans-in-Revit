# Live-Revit spike runner (Pre-Phase-6 spike + Phase 6 checklist)

This file is the prompt for a **Claude Code session running ON the Revit workstation** with
the AUTOM8LABS MCP Connector for Revit attached. Nothing in CI ever touches live Revit
(CLAUDE.md hard rule); this is the one sanctioned manual path (PLAN.md Part B de-risk note:
manually invoked, bridge bound to localhost, throwaway models only, never client files).

## Setup (once, ~15 min, done by Eran)

1. Start Revit 2025 with a **throwaway** project based on Chapter's template (or the stock
   architectural template with the MEP disciplines enabled). Never a client model.
2. Install Claude Code on the workstation (`npm install -g @anthropic-ai/claude-code`) and
   sign in with the Chapter account.
3. Clone this repo and check out `claude/phase-6-mep`.
4. In the AUTOM8LABS dialog (Add-Ins → AUTOM8LABS → MCP Connector) copy the stdio server
   command, then in the repo directory register it for this project only:
   `claude mcp add revit -- <the server command>` (stdio, localhost — no tunnel, no port).
   The 38 free tools are read-only; creating walls/doors/devices/pipes needs the Pro licence
   key entered in the same dialog.
5. Run `claude` in the repo and paste: **"Follow docs/REVIT_SPIKE.md stage 1."**

## Stage 1 — API conventions through the MCP bridge (no plugin needed, ~30 min)

Work in a fresh throwaway model. Use mm everywhere (Revit internal units are feet; the
bridge converts or report both). Record every observation in `docs/REVIT_SPIKE_RESULTS.md`
(create it; one heading per item below; paste the raw numbers Revit returns).

1. **Wall face convention.** Create a wall `W-001` from (0,0) to (4000,0) on Level 1 with a
   generic 200 mm type. Ask Revit for the wall's exterior face (`HostObjectUtils.GetSideFaces`
   / the bridge's face or orientation query). Report whether the EXTERIOR face lies at
   +y (left of start→end, the D1 convention `Placement.Place("face_left")` assumes) or at
   −y. Repeat with the wall drawn (4000,0)→(0,0) and with `Flip`ped once.
2. **Face-hosted receptacle.** Place any face-based electrical fixture family on `W-001` at
   offset 1000 along the wall, 380 mm above the level, on the +y face, then on the −y face.
   Report the instance's location point (x, y, z) and its `FacingOrientation` for each.
   Conclude: does the plugin's `face: "left"` (= +y for this wall) land the device where the
   plan says? If not, the mapping in `PlaceDeviceHandler` (`face_left`/`face_right`) inverts.
3. **Door hand / facing.** Insert a single-flush door at offset 2000 on `W-001`. Read
   `HandFlipped`, `FacingFlipped`, `HandOrientation`, `FacingOrientation`. Flip hand, read
   again; flip facing, read again. Conclude the mapping the plan needs: Phase 5 swing.py says
   the leaf sweeps to the LEFT (+y here) of start→end when `flip_facing` is falsy, and
   `swing: "L"|"R"` is the hinge side seen from the swept side. Write the truth table
   (swing, flip_facing) → (HandFlipped, FacingFlipped) that `CreateDoorHandler` must apply.
4. **Pipes and fittings.** With a Sanitary piping system type and a PVC pipe type present:
   create two pipes (0,1000,−300)→(2000,1000,−300) and (2000,1000,−300)→(2000,3000,−300)
   at Ø76, then connect them with an elbow (`NewElbowFitting`). Report success or the exact
   exception. Then try a 30° bend and a tee into a vertical stack; report the failure text —
   those are the `fitting_unsupported`/`wye_manual` cases the plan hands to a human.
5. **Conduit.** Same with two EMT conduit segments at z 2600 and an elbow.
6. **Interference.** Create a second pipe crossing the first one and run an interference
   check (`ElementIntersectsElementFilter` or the bridge's clash tool). Report the pair and
   whether touching-but-not-overlapping elements are reported (the plan's law is strict:
   touching is legal).
7. **Routing preferences.** Report which pipe/conduit fitting families the template's
   routing preferences carry (the missing-fitting failure mode from MANUAL_REVIT_TEST.md).

Commit `docs/REVIT_SPIKE_RESULTS.md` on a branch `spike/revit-conventions` and push it; the
remote session reads it and adjusts `PlaceDeviceHandler` / `CreateDoorHandler` /
`fittings.py` if any convention differs.

## Stage 2 — the real add-in (Phase 6 checklist, later, ~1 h)

Needs the gateway + Postgres running on the workstation (`make dev-up`, `services/gateway`
with `pnpm dev`) or reachable over the network, the add-in built with the .NET 8 SDK
(`dotnet build plugin/ChapterHub.sln -c Release`) and installed per the Phase 1 gate rows,
and the two catalogs copied to `%AppData%\ChapterHub\catalogs\`. Then follow
`docs/MANUAL_REVIT_TEST.md` sections "Pre-Phase-6 spike" and "Phase 6 gate" verbatim,
ticking boxes in a commit on the same spike branch.
