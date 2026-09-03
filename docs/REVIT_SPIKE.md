# Live-Revit spike runner (Pre-Phase-6 spike + Phase 6 checklist)

This file is the prompt for a Claude session running ON the Revit workstation with the
**AUTOM8LABS MCP Connector for Revit** attached. Nothing in CI ever touches live Revit
(CLAUDE.md hard rule); this is the one sanctioned manual path (PLAN.md Part B de-risk note:
manually invoked, bridge bound to localhost, throwaway models only, never client files).

## Status

- **Stage 1 — DONE 2026-09-03** (Revit 2027.2, throwaway model, Claude Cowork + AUTOM8LABS).
  Results: `docs/REVIT_SPIKE_RESULTS.md`; what changed because of them: `docs/PHASE6_DESIGN.md`
  §9b. Items 1, 4, 5, 6 and 7 are answered. Items 2 (face-hosted receptacle) and 3 (door
  hand/facing) are BLOCKED through the connectors — AUTOM8LABS cannot host anything (face-based
  families land unhosted at z = 0) and has no flip tools — and move to stage 2, where the add-in
  does the hosting.
- **Stage 2 — OPEN.** Needs the template content and the installed add-in listed below.

## Connectors (what is actually installed on the workstation)

- **AUTOM8LABS_Revit** — the only connector that reaches Revit for creating/modifying elements
  (278 tools incl. the Pro create set). It cannot host families, silently drops z on face-based
  placements, reports a wall's geometric centreline rather than its Location Line, and exposes
  none of `Wall.Orientation`/`Flipped`, door hand/facing flags, `flipHand`/`flipFacing` or
  routing-preference rules.
- **"Revit" in Claude Desktop = the AI Connector for Revit by Nonica (NonicaTab)** — NOT
  Autodesk's Revit 2027 Public MCP Server (a separate install). It timed out for the whole
  stage-1 run ("open Revit and enable NonicaTab AI connection"). Stage 1 needed only AUTOM8LABS;
  stage 2 reads everything back through the add-in.

## Runner options

**A. Claude Cowork on the workstation (recommended — the path that worked).** Start Revit 2027
with a **throwaway** project (never a client model), open Claude Cowork, confirm the AUTOM8LABS
connector is on, and paste:

> Follow docs/REVIT_SPIKE.md stage 2 in github.com/eranfromchapter/Design-and-create-plans-in-Revit
> (branch claude/phase-6-mep). Tick the checklist rows in docs/MANUAL_REVIT_TEST.md, write every
> raw number Revit returns, and upload the resulting markdown here when done.

**B. Claude Code in Windows PowerShell (alternative).** Revit running first, then one line at a
time:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force   # lets npm's .ps1 shim run
npm install -g @anthropic-ai/claude-code                     # (or: npm.cmd install -g ...)
cd $HOME; mkdir chapter -Force; cd chapter
git clone https://github.com/eranfromchapter/Design-and-create-plans-in-Revit.git
cd Design-and-create-plans-in-Revit
git checkout claude/phase-6-mep                              # a branch name, not a command
claude mcp add-from-claude-desktop                           # tick AUTOM8LABS_Revit
claude
```

If `git` is not recognised: `winget install --id Git.Git -e`, then reopen PowerShell. Inside
`claude`, `/mcp` must show the AUTOM8LABS server **connected**; then paste
"Follow docs/REVIT_SPIKE.md stage 2."

## Stage 1 — API conventions through the MCP bridge (DONE; kept for re-runs)

Work in a fresh throwaway model, mm everywhere (Revit internal units are feet; report both).
Record every observation in `docs/REVIT_SPIKE_RESULTS.md` with the raw numbers Revit returns.

1. **Wall face convention.** Wall `W-001` (0,0)→(4000,0) on Level 1; where is the EXTERIOR
   face — +y (left of start→end, the D1 convention `Placement.Place("face_left")` assumes) or
   −y? Repeat drawn (4000,0)→(0,0).
   → **Result: exterior = LEFT of start→end, both directions** (proven by holding Location Line
   = Finish Face: Exterior through a type-thickness swap). Law confirmed; no code change.
2. **Face-hosted receptacle** on `W-001` at offset 1000, 380 mm AFF, +y face then −y face;
   report location and `FacingOrientation`.
   → **Blocked:** the connector places face-based families unhosted (Host = −1, z dropped).
   Follow-up in the plugin: `unhosted` post-check. Answered in stage 2.
3. **Door hand / facing** at offset 2000; read `HandFlipped`, `FacingFlipped`,
   `HandOrientation`, `FacingOrientation`; flip hand, flip facing, read again; write the truth
   table (swing, flip_facing) → flags for `CreateDoorHandler`.
   → **Blocked** (no door family, no hosted placement, no flip tools); table by API convention
   only. Follow-up: the plugin now decides flips from the orientation VECTORS (see §9b).
4. **Pipes and fittings.** Sanitary system + PVC type: two Ø76 pipes (0,1000,−300)→(2000,1000,−300)
   and (2000,1000,−300)→(2000,3000,−300), elbow, then a 30° bend and a tee into a stack.
   → `Sanitary` exists, no PVC type (`Default` steel used), straight pipes OK; **elbow failed:
   no pipe elbow family in the template** ("failed to insert elbow"); tee not routable.
   Follow-up: `routing_preference_missing` preflight + `fitting_insert_failed`.
5. **Conduit.** Two EMT segments at z 2600 and an elbow.
   → **Works**: `Conduit with Fittings : Conduit` (standard EMT), auto `Conduit Elbow -
   Aluminum : Standard`; 21 mm written literally (shown 7/8"). Follow-up: size-table snapping.
6. **Interference.** A crossing pipe; is touching-but-not-overlapping reported?
   → Crossing flagged, unmitred corner flagged, **touching NOT flagged** — matches the strict law.
7. **Routing preferences.** Which fitting families the template carries.
   → Conduit: all five `… - Aluminum : Standard`; pipe `Default`: Coupling / Tee / Transition,
   **no Elbow**.

## Stage 2 — the real add-in (Phase 6 checklist, ~1 h at the workstation)

### Prerequisites — template content (the stage-1 template had none of it)
1. A **door family** authored per the Door.rft convention the plugin assumes: leaf hinged at the
   family's −X (Left) jamb, swinging to family +Y (Exterior); its type name goes into
   `new_construction_types.json` (Eran's vocabulary). A family hinged the other way fails the
   door op with `door_flip_failed` — then re-author it or tell us which families hinge at +X.
2. One **face-based electrical-fixture family** per `place_device.kind` (receptacle, gfci,
   receptacle_240, switch) → `mep_types.json` `device_families`. Wall-based families do not work
   with the face-hosted placement the plugin uses.
3. A **PVC DWV pipe type** whose routing preferences carry an elbow (e.g. `Elbow - Generic`) and
   a segment with a size table (1¼"…4") → `mep_types.json` `pipe_types.sanitary`. The `Sanitary`
   piping system type already exists.
4. The **conduit type** (`Conduit with Fittings : Conduit`, standard EMT — exists) with its Bend
   fitting → `mep_types.json` `conduit_type`; `conduit_diameter_mm` must be a real trade size
   (19.05 = ¾" EMT; the plugin snaps within 2.5 mm and fails `unknown_size` otherwise).
5. The Revit 2027 local family library is not installed on the workstation ("Load Autodesk
   Family" only) — load from the cloud library or ship the .rfa files with the enrollment.

### Steps
- Gateway + Postgres running on the workstation (`make dev-up`, `pnpm dev` in
  `services/gateway`) or reachable over the network.
- Add-in built with the .NET 8 SDK (`dotnet build plugin/ChapterHub.sln -c Release`) and
  installed per the Phase 1 gate rows; the two catalogs copied to
  `%AppData%\ChapterHub\catalogs\` with the REAL names (the add-in fails `catalog_missing`
  otherwise and never guesses a family).
- Follow `docs/MANUAL_REVIT_TEST.md` sections "Pre-Phase-6 spike" and "Phase 6 gate" verbatim,
  ticking boxes in a commit on a spike branch. Stage-1 items 2 and 3 are answered here: the
  receptacle must show Host = the wall on the plan's face, and the door must sweep to the plan's
  side with the hinge at the plan's jamb.
