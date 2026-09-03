<!-- Stage 1 of docs/REVIT_SPIKE.md, run by Eran on his dev-only Revit workstation through Claude
Cowork + the AUTOM8LABS MCP connector, on a throwaway model (never saved). Committed verbatim
except for two redactions: the Revit user name and the local file path are replaced by
<workstation>. Element ids are those of the discarded test model. The follow-ups this run
produced are recorded in docs/PHASE6_DESIGN.md §9b and applied in the plugin. -->

# REVIT_SPIKE_RESULTS — live conventions test, Chapter Revit AI agent

- **Run:** Thursday 2026-09-03, ~13:11–13:50 UTC (09:11–09:50 New York)
- **Revit:** Autodesk Revit 2027, build 27.2.0.39 (sub-version 2027.2), English_USA, user `<workstation>`
- **Document:** `424 Eran Test 3` — `<workstation>` (42.38 MB, not workshared, only document open) — throwaway test file, confirmed
- **Connectors:** `AUTOM8LABS_Revit` (278 tools, `readOnlySession:false`) used for all create/modify calls. `Revit` = **AI Connector for Revit by Nonica (NonicaTab)** — *not* Autodesk's server — every live call timed out for the whole run (see Step 0), so **no independent read-back was possible**. All numbers below are AUTOM8LABS returns unless stated.
- **Units:** project display units are Imperial (feet-fractional-inches). Revit internal = decimal feet. Everything below is given in mm and ft (1 ft = 304.8 mm).

---

## Summary — the seven conclusions

| # | Step | Conclusion |
|---|------|------------|
| 1 | Wall face | **Exterior face = LEFT of start→end: YES.** W-001 drawn +X → exterior is +Y; W-002 drawn −X → exterior is −Y. Proven geometrically (Location Line = Finish Face: Exterior held fixed during a type-thickness swap). Orientation vector (derived, not read from `Wall.Orientation`): W-001 (0,+1,0), W-002 (0,−1,0). |
| 2 | Face-hosted receptacle | **Not achievable through either connector.** AUTOM8LABS accepted the face-based family but placed it **unhosted** on Level 1 (Host = None, z=380 silently dropped to 0). Conclusion by convention + Step 1: "face: left" on a +X wall = the **+Y = EXTERIOR** face → use `HostObjectUtils.GetSideFaces(wall, ShellLayerType.Exterior)` (normal = `Wall.Orientation`); "face: right" = `ShellLayerType.Interior`. Untested live. |
| 3 | Door hand/facing | **Blocked.** No door family in the template; a Door.rft-based family was built and loaded but AUTOM8LABS refuses hosted placement (`OneLevelBasedHosted … which this tool does not place yet`). No flipHand/flipFacing tool exists on either connector; Nonica (the only Hand/Facing reader) was offline. Truth table given by API convention only (Step 3). |
| 4 | Pipes & fittings | Sanitary system type exists (`Sanitary`); **no PVC pipe type** — only `Default` (segment `Steel, Carbon - Schedule 40`). Pipes P-001/P-002 created at 76.0 mm (3"ø). **Elbow FAILED** (`elbow route refused by Revit: failed to insert elbow`) — the template has **no pipe elbow fitting family loaded** (only Coupling / Tee / Transition). 30° bend elbow failed identically. **Tee not supported** by the connect tool (it only routes elbow/transition/union); attempt failed as an "elbow, 1000 mm apart". |
| 5 | Conduit | **Success.** Type `Conduit with Fittings : Conduit` (Standard = **EMT**), 21.0 mm accepted, two legs + 90° elbow `Conduit Elbow - Aluminum : Standard` auto-inserted at (3000, 500, 2600). |
| 6 | Interference | Crossing P-001×P-003 flagged at (1000, 1000, −300); unmitred corner P-001×P-002 also flagged at (1981, 1019, −300). End-to-end touching pipe P-004 **not** flagged → **touching flagged: NO.** |
| 7 | Routing preferences | Conduit type carries Bend/Union/Transition/Cross/Tee = the five `… - Aluminum : Standard` families (full list in Step 7). Pipe type `Default`: routing-preference rules are **not readable** through either connector; loaded Pipe Fitting families = `Coupling - Generic`, `Tee - Welded - Generic`, `Transition - Welded - Generic` — **no Elbow**, which explains Step 4. |

**Cross-cutting findings for the agent design**
1. AUTOM8LABS `place_family_instances` cannot host anything (wall-, face- or ceiling-based). Face-based families are *silently* dropped unhosted at z=0 — the agent must check `Host`/`Host Id` (= −1 here) after every placement.
2. Neither connector exposes `Wall.Orientation`, `Wall.Flipped`, `FacingOrientation`, `HandOrientation`, `HandFlipped`, `FacingFlipped`, `flipHand()`, `flipFacing()` or routing-preference rules while Nonica is offline; AUTOM8LABS has none of them at all.
3. AUTOM8LABS `get_element_by_id` reports a wall's **geometric centreline**, not its Location Line curve (verified: after Location Line = Finish Face: Exterior it still reported the centreline).
4. The template is content-poor: no door, window or electrical-fixture families; no pipe elbow; no PVC/other pipe types; the Revit 2027 local library is not installed (cloud "Load Autodesk Family" only), so the agent must ship its own .rfa content.
5. Requests that should bind to a size table (21 mm conduit, 76 mm pipe) are written literally (Revit shows 7/8"ø and 3"ø by display rounding) — the agent should pass catalogue sizes explicitly.

---

## Step 0 — Tool inventory, document, Level 1, units

**Connector A — `AUTOM8LABS_Revit`:** `ping` → `connected`, Revit 2027 / 27.2.0.39; `get_session_info` → `toolCount: 278`, `readOnlySession: false`, `readOnlyLockedByPolicy: false`, `hasActiveDocument: true`. All 278 tool names are listed in Appendix A (64 of them are create/place/edit/connect tools, so the Pro create set is present — no tool was reported missing for licence reasons).

**Connector B — `Revit` (Nonica AI Connector, 55 tools, Appendix B):** only the static `create_tool_names_explorer` answered (15 creation tools: `create_grids, create_levels, create_viewplans, create_view3ds, create_viewsections_or_detailviews, create_sheets, create_viewports_and_schedules_on_sheet, create_schedule, create_legends_or_draftingviews, create_textnotes_on_view, create_room_elevationviews, create_pdf_export_print, create_cad_export_print, create_tags_on_view, create_referenceplanes` — no family placement, no MEP). Every live call (`get_all_project_units`, `get_active_view_in_revit`, `get_location_for_element_ids`, `get_all_additional_properties_from_elementid`, `get_host_id_for_element_ids`) returned, on every retry across ~40 minutes:
> `The request timeout. Possibly because the AI Connector for Revit by Nonica was not enabled, or it was closed. Please, open Revit and enable NonicaTab AI connection. AI Connector for Revit must be kept open and enabled.`

**Document:** title `424 Eran Test 3`; path above; `isModified:false` at start; `isWorkshared:false`; `isFamilyDocument:false`; phases `Existing` (32440), `New Construction` (118390); project info all placeholder ("Project Name", "Project Number"…); active view `L1 - Working` (id 916112, FloorPlan, 1/8"=1'-0" scale 96, level `L1`). Throwaway status: confirmed by name/location (`<workstation>`, IFC-imported "CODEX KITCHEN DEMO 02" content) and by the user.

**Levels:** exactly one level — `L1`, id 30, elevation **0.0 ft = 0.0 mm** (`isBuildingStory:true`). (The prompt's "Level 1" is `L1`.)

**Default units:** `unitSystem: Imperial`; Length = `feetFractionalInches` (accuracy 1/32" = 0.0026 ft); Area = squareFeet; Volume = cubicFeet; Angle = degrees; Slope = rise/12"; PipeSize & DuctSize = fractionalInches; PipingFlow = US gpm; HvacPressure = in-wg. Internal storage: decimal feet.

**Conclusion:** both MCP processes are up, but only AUTOM8LABS reaches Revit; the model is the intended throwaway; L1 = 0 mm; project is Imperial (all tool inputs converted from mm).

---

## Step 1 — Wall face convention (W-001, W-002)

**Type:** no 200 mm generic wall exists. Wall types in the file: `Exterior - Brick on Mtl. Stud` (id 221, 352.42 mm, 7 layers), `Exterior - CMU on Mtl. Stud` (83171, 454.02 mm), `PATCH - EXISTING WALL MATCH - 4"` (1248032, **100.0 mm**, 1 layer), `Curtain Wall: _Not Defined`. Creating a 200 mm copy failed — all three basic types are vertically compound: `Walls type 'PATCH - EXISTING WALL MATCH - 4"' is vertically compound (split regions/sweeps). Its layer stack cannot be edited through this tool - simplify it in the type editor first.` → used **`PATCH - EXISTING WALL MATCH - 4"` (100 mm)**; thickness does not affect the face convention.

**Created** (`create_walls`, baseLevel L1, height 8.858268 ft = 2700 mm, centreline):

| Mark | ElementId | Start (mm) → End (mm) | Start → End (ft) | Length | BBox y (mm / ft) | Location Line |
|---|---|---|---|---|---|---|
| W-001 | **1248260** | (0, 0, 0) → (4000, 0, 0) | (0, 0) → (13.1234, 0) | 4000.0 mm = 13.12336 ft | −50 … +50 mm = −0.164 … +0.164 ft | 0 = Wall Centerline |
| W-002 | **1248261** | (4000, 3000, 0) → (0, 3000, 0) | (13.1234, 9.8425) → (0, 9.8425) | 4000.0 mm | 2950 … 3050 mm = 9.6785 … 10.0066 ft | 0 = Wall Centerline |

Both: width 0.3281 ft = 100.0 mm, z 0 … 8.8583 ft (0 … 2700 mm), Base Constraint L1 (30), Top Constraint Unconnected, Unconnected Height 8.858268 ft, Area 116.25 SF, Volume 38.14 CF, Structural Usage Non-bearing, Room Bounding Yes.

**Orientation / exterior face:** `Wall.Orientation` is not exposed by AUTOM8LABS (`get_element_by_id`, `get_element_parameters` have no orientation/flipped field) and Nonica was offline, so the exterior side was determined geometrically on two disposable twin walls, W-003 (id 1248262, (0,−6000)→(4000,−6000), same direction as W-001) and W-004 (id 1248263, (4000,−9000)→(0,−9000), same direction as W-002):
1. `set_wall_location_line` → `FinishFaceExterior` on both (`from WallCenterline to FinishFaceExterior`, success). Revit keeps the *exterior face* fixed from now on.
2. `change_element_type` → `Exterior - Brick on Mtl. Stud` (352.42 mm). The wall can only grow toward the interior.
3. `get_bounding_boxes` (mm):
   - W-003 (drawn +X): y **−6302.42 … −5950.0** (−20.6772 … −19.5210 ft); centreline reported −6126.21 mm (−20.0991 ft). Fixed face = **−5950 = the original +Y face** (−6000 + 50). Growth went to −Y.
   - W-004 (drawn −X): y **−9050.0 … −8697.58** (−29.6916 … −28.5354 ft). Fixed face = **−9050 = the original −Y face**. Growth went to +Y.
4. Both twins deleted (`deletedIds: [1248262, 1248263]`); W-001/W-002 location lines restored to `WallCenterline`.

Hence: W-001 exterior = **+Y** = the side to the **LEFT** of start→end (+X). W-002 exterior = **−Y** = LEFT of start→end (−X). Derived `Wall.Orientation` (exterior normal = Ẑ × direction, `Flipped=false` at creation): **W-001 (0, +1, 0); W-002 (0, −1, 0).** Sanity: the `Exterior - Brick…` type's layer 0 (index 0 = exterior per `get_compound_structure`) is `Brick, Common`, so on W-001 the brick would face +Y.

Side note for the agent: after Location Line = Finish Face: Exterior, `get_element_by_id` still returned `startPointMm y = 0` for W-001, i.e. the tool reports the geometric centreline, not `LocationCurve`.

**Conclusion:** exterior face = left of start→end: **yes** (both directions).

---

## Step 2 — Face-hosted receptacle on W-001 (+Y then −Y face)

**Family:** the template has **no Electrical Fixture families** and no local Revit library (`C:\ProgramData\Autodesk\RVT 2027\Libraries\English-Imperial\US` contains only the "…use Load Autodesk Family.rfa" stub, Route Analysis and Structural Precast). A face-based family was built live from template `Generic Model face based` (Electrical Fixture templates exist only as wall-based; category cannot be changed via the tools): `SPIKE_Receptacle_FaceBased`, family id **1248264**, type id 1249100, category Generic Models. Geometry (family coords, mm): plate x −35…+35, y −57.5…+57.5, thickness 10 along +Z (off the host face); marker tab at +Y (y 57.5…80) and hand tab at +X (x 35…55) so orientation can be read from the bounding box.

**Attempt 1 — +Y face**, `place_family_instances` at (1000, +50, 380) mm on L1: `success:true`, instance **1249124**, `atMm [1000, 50, 380]`. Read-back (`get_element_by_id`):
- location (3.2808, 0.164, **0.0**) ft = (1000.0, 50.0, **0.0**) mm — **z=380 was dropped**
- `Host: -1`, `Host Id: -1`, `Host_2: "None"`, `Level: 30 (L1)`, `Elevation from Level: 0.0`
- bbox mm x 965 … 1055, y −7.5 … 130, z **0 … 10** — the plate is lying flat on the level (family +Z → world +Z, family +Y → world +Y, family +X → world +X), i.e. unhosted, no HostFace.

**Attempt 2 — −Y face**, at (1000, −50, 380): `success:true`, instance **1249125**, read-back identical pattern: location (1000, −50, **0.0**) mm, `Host: -1`, `Host_2: "None"`, z dropped.

FacingOrientation / HandOrientation / hosted face: **not readable** (AUTOM8LABS exposes none; Nonica `get_host_id_for_element_ids` timed out). Both instances deleted (`deletedIds: [1249124, 1249125]`).

**Conclusion (convention + Step 1, not exercised live):** "face: left" on a wall drawn along +X is the **+Y face = the wall's EXTERIOR face** → placement must use the face from `HostObjectUtils.GetSideFaces(wall, ShellLayerType.Exterior)` (its normal equals `Wall.Orientation`, here (0,+1,0)), with `NewFamilyInstance(face, point, refDir, symbol)`; for "face: right" (−Y) use `ShellLayerType.Interior`. Always compute the side from `Wall.Orientation`, never from draw direction, because `Wall.Flipped` negates it. Through the current connectors this cannot be done: AUTOM8LABS places face-based families unhosted (and drops z), Nonica has no placement tool.

---

## Step 3 — Door hand and facing

**Family:** no door families in the template. Built live from template `Door` (Doors category, Width/Height/Thickness parameters, ref planes Left/Right/Exterior/Interior; the template plan shows **Exterior = +Y, Interior = −Y** — verified from `capture_family_view`): `SPIKE_Door_SingleFlush`, family id **1249126**. Leaf geometry (family mm): x −457.2 … −412.75 (hinge at the **−X jamb**), y +101.6 … +1016 (open 90° into the **+Y = exterior** side), z 0 … 2133.6.

**Placement attempt** at 2000 mm along W-001 — `place_family_instances` (2000, 0, 0) mm on L1 → **error, exact text:**
> `Family 'SPIKE_Door_SingleFlush' has placement type OneLevelBasedHosted - it needs a host (wall, face, or ceiling), which this tool does not place yet. Place hosted instances manually for now.`

Neither connector offers `flipHand` / `flipFacing`; `HandFlipped`, `FacingFlipped`, `HandOrientation`, `FacingOrientation` can only be read via Nonica `get_all_additional_properties_from_elementid` (offline). AUTOM8LABS `mirror_elements` (mirrorCopies=false) about a plane ⟂ to the wall / in the wall plane would be the only available flip surrogate. The model's 8 existing "Door_0…Door_7" are IFC DirectShapes (no host/location) and unusable. Raw flag values: **none obtained.**

**Truth table — by Revit API convention for the family above (hinge at family −X, leaf swings to family +Y), for a wall along +X. NOT verified live:**

| Hinge side seen from the swept side | Swept side | HandFlipped | FacingFlipped | HandOrientation | FacingOrientation |
|---|---|---|---|---|---|
| R | +Y | false | false | (+1,0,0) | (0,+1,0) |
| L | +Y | **true** | false | (−1,0,0) | (0,+1,0) |
| L | −Y | false | **true** | (+1,0,0) | (0,−1,0) |
| R | −Y | **true** | **true** | (−1,0,0) | (0,−1,0) |

Reading: `FacingOrientation` = family +Y (exterior) transformed = the swept side; `HandOrientation` = family +X transformed; hinge sits at *location − HandOrientation·Width/2* for this family (at *+HandOrientation·Width/2* for a family whose leaf is drawn at the +X jamb — check the family once, then the table follows by sign). `Mirrored == (HandFlipped XOR FacingFlipped)`. On a fresh placement Revit aligns FacingOrientation with `Wall.Orientation` (exterior, +Y on W-001).

**Conclusion:** step blocked at placement; table above is the convention to verify the moment a hosted-placement tool (or a working Nonica read-back + manual placement) is available.

---

## Step 4 — Pipes and fittings

**System / type inventory:** piping system types present (11): `Domestic Cold Water, Domestic Hot Water, Fire Protection Dry, Fire Protection Other, Fire Protection Pre-Action, Fire Protection Wet, Hydronic Return, Hydronic Supply, Other, Sanitary, Vent` → **`Sanitary` exists (exact name)**. Pipe types present: **`Default` only** (`Pipe Types : Default`, type id 181474; segment `Steel, Carbon - Schedule 40` (181465), material `Steel, Carbon`, Schedule 40, Connection Type `Generic`). **No PVC pipe type**, and no tool to create pipe types → `Default` used.

**P-001 / P-002** (`create_pipe`, systemType `Sanitary`, pipeType `Default`, diameterMm 76, level L1):

| Mark | ElementId | Start (mm) → End (mm) | Start → End (ft) | Achieved Ø | Length | System |
|---|---|---|---|---|---|---|
| P-001 | **1250084** | (0, 1000, −300) → (2000, 1000, −300) | (0, 3.2808, −0.9843) → (6.5617, 3.2808, −0.9843) | 76.0 mm = 0.249344 ft (Size `3"ø`, OD = ID = 3") | 2000.0 mm = 6.56168 ft | `Sanitary 1` |
| P-002 | **1250087** | (2000, 1000, −300) → (2000, 3000, −300) | (6.5617, 3.2808, −0.9843) → (6.5617, 9.8425, −0.9843) | 76.0 mm | 2000.0 mm | `Sanitary 2` |

Both created `UNCONNECTED` (connector 0/1 at the given ends, `isConnected:false`). Invert −1.108924 ft (−338 mm), obvert −0.85958 ft (−262 mm), centreline −0.984252 ft.

**Elbow at (2000, 1000, −300)** — `connect_mep_elements(1250084, 1250087)`: route classified `elbow`, `gapMm 0.0`, connectors A1/B0 → **FAILED**, exact text:
> `elbow route refused by Revit: failed to insert elbow. (connectors are 0 mm apart)`

Root cause (Step 7): the project has **no elbow Pipe Fitting family** loaded (`Coupling - Generic`, `Tee - Welded - Generic`, `Transition - Welded - Generic` only), so `NewElbowFitting` has nothing to place.

**30° bend** — pipes 1250092 (0,5000,−300)→(2000,5000,−300) and 1250095 (2000,5000,−300)→(3732.05, 6000, −300) (both 76 mm, meeting at 30°), then `connect_mep_elements` → **FAILED**, exact text:
> `elbow route refused by Revit: failed to insert elbow. (connectors are 0 mm apart)`
(identical to the 90° case — the missing family fails before the angle is evaluated).

**Tee** — vertical pipe 1250098 (1000,1000,−300)→(1000,1000,2700), 76 mm, 3000 mm long, then `connect_mep_elements(1250084, 1250098)`: the tool has **no tee route** (it only does direct / elbow / transition / union between free connectors and never splits a run); it paired P-001's start connector with the riser's bottom connector and reported → **FAILED**, exact text:
> `elbow route refused by Revit: failed to insert elbow. (connectors are 1000 mm apart)`

Test pipes 1250092/1250095/1250098 deleted (Revit also removed their systems 1250093/1250096/1250099).

**Conclusion:** Sanitary OK, PVC missing (Default/steel used), straight pipes OK at 76.0 mm; elbow, 30° elbow and tee all fail — elbows for want of a loaded elbow family, tee for want of a tee routine in the connector.

---

## Step 5 — Conduit

Conduit types in the model: two types both named `Conduit` (`Conduit with Fittings : Conduit`, id 181497, and `Conduit without Fittings : Conduit`). `create_conduit` with `conduitTypeName "Conduit"`, `diameterMm 21`, level L1, points (0,500,2600) → (3000,500,2600) → (3000,2500,2600):

- `success:true`, `runIsContinuous:true`, `conduitType: "Conduit"` → resolved to **`Conduit with Fittings : Conduit`**, type parameter **Standard = `EMT`** (id 146529)
- Leg 0: id **1250104**, length **2824.38 mm = 9.2663 ft** (3000 − 175.62 elbow centre-to-end), Ø 21.0 mm
- Leg 1: id **1250106**, length **1824.38 mm = 5.9855 ft**, Ø 21.0 mm
- Joint at vertex (3000, 500, 2600) mm = (9.8425, 1.6404, 8.5302) ft: `connected:true`, deflection **90.0°**, fitting id **1250108** = `Conduit Elbow - Aluminum : Standard` (type 785128), Angle 1.570796 rad, Bend Radius 0.373977 ft = 113.99 mm, Center to End 0.576194 ft = 175.62 mm, Nominal Diameter 0.068898 ft = 21.0 mm, Fitting OD 0.117644 ft = 35.86 mm, Size `7/8"ø-7/8"ø`
- Segment read-back: `Diameter(Trade Size)` = OD = ID = 0.068898 ft = **21.0 mm** (displayed `7/8"ø` by 1/8" rounding — not snapped to an EMT trade size such as 1/2"/3/4"), centreline 8.530184 ft = 2600 mm, Reference Level L1.

**Conclusion:** conduit + auto-elbow **succeeded**; type `Conduit with Fittings : Conduit` (EMT standard); 21 mm was written literally rather than mapped to a trade size — pass catalogue sizes explicitly.

---

## Step 6 — Interference

**P-003** = id **1250111**, (1000, 0, −300) → (1000, 2000, −300) mm = (3.2808, 0, −0.9843) → (3.2808, 6.5617, −0.9843) ft, 76.0 mm, `Sanitary 3`, crossing P-001 at (1000, 1000, −300).

`check_model_interferences(host Pipes → target Pipes, Walls, Conduits, Conduit Fittings)`: `hostElementsChecked 3`, `targetElementsChecked 92`, **`clashesFound 2`**:

| Host | Target | Intersection (mm) | Intersection (ft) | Why |
|---|---|---|---|---|
| P-001 1250084 | P-002 1250087 | (1981, 1019, −300) | (6.4993, 3.3432, −0.9843) | unmitred corner — the two 76 mm cylinders overlap because the elbow failed in Step 4 |
| P-001 1250084 | P-003 1250111 | (1000, 1000, −300) | (3.2808, 3.2808, −0.9843) | the intended crossing |

No pipe/wall or pipe/conduit clashes (pipes at z −300 sit below the wall bases at 0; conduit is at 2600).

**Touching test:** **P-004** = id **1250115**, (−1500, 1000, −300) → (0, 1000, −300) mm (−4.9213 → 0 ft), 76.0 mm, collinear with P-001 and sharing only the end disc at (0, 1000, −300). Re-check (host Pipes → target Pipes): `hostElementsChecked 4`, `targetElementsChecked 4`, **`clashesFound 2` — the same two pairs; P-001×P-004 is not reported.**

**Conclusion:** touching flagged: **no** (Revit interference reports volumetric overlap only; end-to-end contact is silent).

---

## Step 7 — Routing preferences

**Conduit type `Conduit with Fittings : Conduit` (181497)** — fittings are stored as type parameters and were read directly:

| Slot | Family : Type | Type id |
|---|---|---|
| Bend (elbow) | `Conduit Elbow - Aluminum : Standard` | 785128 |
| Union | `Conduit Coupling - Aluminum : Standard` | 785139 |
| Transition | `Conduit Junction Box - Transition - Aluminum : Standard` | 785137 |
| Cross | `Conduit Junction Box - Cross - Aluminum : Standard` | 785133 |
| Tee | `Conduit Junction Box - Tee - Aluminum : Standard` | 785135 |

Standard = `EMT`. All five Conduit Fitting families loaded in the file are exactly these (`get_family_types` category Conduit Fittings: 5 types).

**Pipe type `Default` (181474)** — its `Routing Preferences` appears as a type parameter with `storageType: None` (a dialog button; rules not readable through AUTOM8LABS; Nonica offline; no routing-preference tool on either connector). Pipe Fitting families actually loaded (`get_family_types` category Pipe Fittings, 3 types):

| Family : Type | Type id | Slot it can serve |
|---|---|---|
| `Coupling - Generic : Standard` | 784928 | Union |
| `Tee - Welded - Generic : Standard` | 785358 | Tee |
| `Transition - Welded - Generic : Standard` | 785370 | Transition |
| *(none)* | — | **Elbow — no elbow family in the project** |
| *(none)* | — | Cross, Cap, Flange |

**Conclusion:** conduit routing is complete (Aluminum fitting set under an EMT standard — a naming mismatch worth normalising); pipe routing for `Default` has no elbow available, so any bend fails until an elbow family (e.g. `Elbow - Generic`) is loaded and assigned.

---

## Clean-up / model state

Deleted during the run: twin walls 1248262, 1248263; receptacle instances 1249124, 1249125; test pipes 1250092, 1250095, 1250098 (+ systems 1250093, 1250096, 1250099).

Still in the model at the time of writing (left so the results can be inspected; **the file has NOT been saved** — `isModified` was false at start, so closing without saving, or deleting the ids below, discards everything):
- Walls W-001 **1248260**, W-002 **1248261**
- Pipes P-001 **1250084**, P-002 **1250087**, P-003 **1250111**, P-004 **1250115** (+ their auto systems `Sanitary 1–4`)
- Conduits **1250104**, **1250106**, conduit elbow **1250108**
- Loaded families `SPIKE_Receptacle_FaceBased` (1248264, type 1249100) and `SPIKE_Door_SingleFlush` (1249126)

The model can be discarded (Close → Don't Save). Nothing outside this document was touched.

---

## Appendix A — AUTOM8LABS_Revit tools (278)

`add_family_parameter`, `add_revision_to_sheets`, `adjust_viewport_title_line`, `align_annotations`, `align_viewports`, `analyze_drawing_register`, `analyze_linked_view_usage`, `analyze_visibility`, `apply_scope_box`, `apply_view_template`, `assign_elements_to_worksets`, `assign_material`, `audit_model_health`, `auto_dimension_curtain_walls`, `auto_dimension_grids`, `auto_dimension_host_layers`, `auto_dimension_levels`, `auto_dimension_openings`, `auto_dimension_openings_in_elevation`, `auto_dimension_rooms`, `auto_place_rooms`, `batch_fill_sheet_parameters`, `batch_link_cad`, `batch_modify_by_filter`, `batch_set_parameters`, `calculate`, `capture_family_view`, `capture_view`, `change_element_type`, `check_annotation_clashes`, `check_disconnected_mep`, `check_model_interferences`, `check_structural_supports`, `clear_selection`, `close_document`, `close_family`, `compact_model`, `compare_elements`, `compare_view_templates`, `connect_mep_elements`, `cope_framing`, `copy_element`, `copy_view_filter`, `copy_view_setup`, `copy_view_templates`, `create_area_scheme`, `create_assembly_views`, `create_batch_sheets`, `create_beam_system`, `create_beams`, `create_braces`, `create_cable_tray`, `create_ceiling`, `create_ceilings_from_rooms`, `create_clash_review_view`, `create_conduit`, `create_dimensions`, `create_duct`, `create_duct_system`, `create_electrical_circuit`, `create_element_sections`, `create_extrusion`, `create_family`, `create_family_dimension`, `create_family_thumbnail`, `create_floor`, `create_foundations`, `create_grids`, `create_group`, `create_levels`, `create_mass_floors`, `create_material`, `create_mep_openings`, `create_mep_spaces`, `create_pipe`, `create_pipe_system`, `create_reference_planes`, `create_revision`, `create_revolve`, `create_roof`, `create_room_elevations`, `create_room_finishes`, `create_scope_box`, `create_section_by_room`, `create_sheets`, `create_sheets_from_excel`, `create_slab_openings`, `create_structural_columns`, `create_text_note`, `create_text_style`, `create_toposolid_from_dwg`, `create_view_filter`, `create_view_template`, `create_views`, `create_walls`, `create_workset_views`, `cut_mep_openings`, `deep_purge`, `delete_elements`, `delete_hidden_annotations`, `delete_sheets`, `delete_unplaced_rooms_areas_spaces`, `delete_views`, `detect_mep_penetrations`, `duplicate_sheets`, `duplicate_views`, `edit_compound_structure`, `edit_in_group`, `enable_worksharing`, `export_clash_report`, `export_drawing_register`, `export_dwg`, `export_ifc`, `export_nwc`, `export_parameters_to_excel`, `export_pdf`, `export_room_data`, `export_schedule`, `export_view_image`, `export_warnings_report`, `find_element_locations`, `find_hidden_elements`, `find_replace_parameter`, `find_replace_text`, `find_untagged_elements`, `fit_room_tags`, `flex_family`, `get_active_view`, `get_analytical_model`, `get_area_boundaries`, `get_areas`, `get_bounding_boxes`, `get_cable_trays`, `get_categories`, `get_compound_structure`, `get_coordinate_system`, `get_current_view_elements`, `get_design_options`, `get_dimension_types`, `get_document_info`, `get_document_warnings`, `get_ducts`, `get_electrical_circuits`, `get_element_by_id`, `get_element_count`, `get_element_history`, `get_element_parameters`, `get_element_set`, `get_elements`, `get_elements_by_proximity`, `get_families`, `get_family_info`, `get_family_types`, `get_grids`, `get_groups`, `get_levels`, `get_linked_files`, `get_material_quantities`, `get_mep_connectors`, `get_mep_spaces`, `get_mep_systems`, `get_panel_schedule`, `get_parameter_values_by_category`, `get_parameters_for_category`, `get_phases`, `get_pipes`, `get_project_units`, `get_revision_settings`, `get_revisions`, `get_room_areas`, `get_room_boundaries`, `get_room_finishes`, `get_rooms`, `get_schedule_data`, `get_schedules`, `get_scope_boxes`, `get_selected_elements`, `get_session_info`, `get_sheet_revisions`, `get_sheets`, `get_structural_elements`, `get_system_elements`, `get_text_notes`, `get_title_block_info`, `get_view_filters`, `get_view_template_settings`, `get_view_types`, `get_views`, `get_wall_sweep_types`, `get_worksets`, `hide_isolate_elements`, `import_cad_underlay`, `import_parameters_from_excel`, `layout_sheet_viewports`, `load_family_into_project`, `manage_links`, `manage_sheet_sets`, `manage_view_positions`, `manage_worksets`, `match_element_properties`, `mirror_elements`, `move_elements`, `open_family`, `open_model`, `orient_view_to_elements`, `override_element_graphics`, `pin_selection`, `ping`, `place_area_boundary_lines`, `place_areas`, `place_families_from_excel`, `place_family_instances`, `place_group_instances`, `place_skirting_in_rooms`, `place_views_on_sheets`, `prune_design_options`, `purge_families`, `purge_unused`, `read_cad_geometry`, `recall_selection_set`, `relinquish_all`, `remove_annotations_in_view`, `remove_empty_tags`, `remove_links`, `remove_revision_from_sheets`, `remove_scope_box`, `remove_unused_view_templates`, `rename_elements`, `rename_families`, `rename_views`, `renumber_elements`, `renumber_sheets`, `renumber_viewport_detail_numbers`, `reset_temporary_hide_isolate`, `resize_duct`, `resize_pipe`, `resolve_duplicate_instances`, `resolve_duplicate_marks`, `resolve_duplicate_type_marks`, `resolve_joined_not_intersecting`, `resolve_multiple_areas_same_region`, `resolve_multiple_rooms_same_region`, `resolve_off_axis_area_boundary`, `resolve_off_axis_grids`, `resolve_off_axis_lines`, `resolve_off_axis_reference_planes`, `resolve_off_axis_room_separation`, `resolve_off_axis_sketch_lines`, `resolve_off_axis_walls`, `rotate_elements`, `save_as`, `save_selection_set`, `search_elements`, `select_elements`, `select_warning_elements`, `set_active_view`, `set_crop_region`, `set_family_element_visibility`, `set_framing_parameters`, `set_link_path_type`, `set_parameter`, `set_reference_plane_extents`, `set_units`, `set_view_display_style`, `set_wall_location_line`, `standardize_view_templates`, `swap_group_type`, `sync_and_relinquish`, `tag_elements_in_view`, `toggle_grid_bubbles`, `undo`, `ungroup_elements`, `unhide_elements_in_view`, `unpin_selection`, `update_drawing_register`, `update_mep_spaces`, `update_text_notes`, `update_view_template`

## Appendix B — Revit (Nonica AI Connector) tools (55)

`create_tool_arguments_explorer`, `create_tool_names_explorer`, `create_tools_invoker`, `get_active_view_in_revit`, `get_additional_properties_for_all_elementids`, `get_all_additional_properties_from_elementid`, `get_all_elementids_for_specific_type_ids`, `get_all_elements_of_specific_families`, `get_all_elements_shown_in_view`, `get_all_families_in_model`, `get_all_project_units`, `get_all_types_of_families`, `get_all_used_families_of_category`, `get_all_warnings_in_the_model`, `get_all_workset_information`, `get_boundary_lines`, `get_boundingboxes_for_element_ids`, `get_categories_by_keywords`, `get_categories_from_elementids`, `get_children_for_element_ids`, `get_document_switched`, `get_element_ids_from_subsets`, `get_element_types_for_elementids`, `get_elements_by_category`, `get_graphic_filters_applied_to_views`, `get_graphic_overrides_for_element_ids_in_view`, `get_graphic_overrides_view_filters`, `get_host_id_for_element_ids`, `get_if_elements_pass_filter`, `get_location_for_element_ids`, `get_material_layers_from_types`, `get_model_categories`, `get_object_classes_from_elementids`, `get_parameters_from_elementid`, `get_parameters_values_for_element_ids`, `get_report_spec`, `get_schedules_info_and_columns`, `get_size_in_mb_of_families`, `get_user_selection_in_revit`, `get_viewports_and_schedules_on_sheets`, `get_worksets_from_elementids`, `get_worksharing_information_for_element_ids`, `save_report`, `set_additional_property_for_all_elements`, `set_copy_elements`, `set_copy_view_filters`, `set_delete_elements`, `set_graphic_overrides_for_elements_in_view`, `set_isolated_elements_in_view`, `set_movement_for_elements`, `set_parameter_value_for_elements`, `set_revisions_on_sheets`, `set_rotation_for_elements`, `set_user_selection_in_revit`, `show_report`
