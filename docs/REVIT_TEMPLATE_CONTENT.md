# Revit template content — the runbook for what the pipeline needs and Eran's template lacks

Eran (2026-09-03): "I don't have and we will need to create it" — for every item below. This file
is the build list. Every name here is a **proposal** (prefix `CHPT_`); the catalog JSON in
`packages/contracts/catalogs/` and `ops/param_allowlist.json` keep their `_PLACEHOLDER` rows until
Eran confirms the names **as created** (the table at the end), because catalog vocabulary is
human-supplied and never invented by the pipeline (CLAUDE.md hard rule).

Work in the **Chapter project template** (the `.rte` new projects start from), never in a client
model. Revit 2027 on the dev workstation; the local family library is not installed there
(`docs/REVIT_SPIKE_RESULTS.md` step 2), so families come from the cloud "Load Autodesk Family"
dialog or are authored from the family templates.

## 0. Inventory — what the live spike found vs what each phase needs

| need | phase | spike finding (stage 1) | action below |
|---|---|---|---|
| door family per the Door.rft convention (hinge −X, swing +Y) | 1, 4 | no door families; a `Door` template exists (Exterior = +Y) | §1 |
| face-based electrical-fixture family, one type per `place_device.kind` | 6 | no electrical fixtures; Electrical Fixture templates are wall-based only | §2 |
| PVC DWV pipe type with an elbow in its routing preferences + size table | 6 | only `Default` (steel, Sch 40): Coupling / Tee / Transition, **no elbow**; `Sanitary` system exists | §3 |
| EMT conduit type with a bend fitting, a real trade size | 6 | `Conduit with Fittings : Conduit` works incl. auto elbow | §4 (confirm) |
| the five `CHPT_*` shared parameters, bound to the allowlist categories | 7, 8 | none | §5 |
| window family for `create_window` | 1 | none | §6 |
| pipe fittings (elbow, tee, coupling, transition) for the PVC type | 6 | none for pipes | §6 |

## 1. Door family — `CHPT_Door_SingleFlush` (proposal)

The plugin decides hand/facing flips from the placed door's `HandOrientation` /
`FacingOrientation` vectors and assumes the Door.rft authoring convention: the leaf is hinged at
the family's **−X (Left) jamb** and swings to family **+Y (Exterior)**. A family authored the other
way fails every door op with `door_flip_failed`.

Manual (Revit UI), ~30 min:
1. File → New → Family → template `Door.rft` (Doors category; ref planes Left / Right /
   Exterior / Interior; parameters Width / Height / Thickness).
2. Model the frame + a single flush leaf: leaf extrusion from the Left ref plane, thickness 45 mm,
   swung open 90° toward Exterior (+Y); a plan swing arc symbolic line on the Exterior side.
3. Types: `813x2032` (2'8" × 6'8") and `915x2032` (3'0" × 6'8") — the two the golden layouts use.
   Width/Height are the type parameters; Thickness 45.
4. Save as `CHPT_Door_SingleFlush.rfa`; Load into the template.
5. Pocket door: duplicate as `CHPT_Door_Pocket` with the leaf visibility off in plan (a leafless
   symbol); type `813x2032`. The swing exemption in the compiler is name-based ("pocket") until
   a catalog flag exists (Phase 5 gate item 8) — keep "Pocket" in the family name.
6. Verify (Cowork can do this part): place one instance on a test wall drawn (0,0)→(4000,0); read
   `HandOrientation` and `FacingOrientation`; expected before any flip: hand along +X, facing +Y
   (the wall's exterior = LEFT of start→end). Record both vectors in the table.

Vocabulary landing spot: `new_construction_types.json` door rows (`revit_family`, `revit_type`).

## 2. Electrical-fixture family, face-based — `CHPT_ElectricalFixture_FaceBased` (proposal)

`place_device` hosts on the wall FACE named by `args.face`; wall-based families cannot be placed
that way and land unhosted (`unhosted` rollback). Revit's Electrical Fixture templates are
wall-based, so:

Manual, ~40 min:
1. New Family → `Generic Model face based.rft`.
2. Family Category and Parameters → change **Category** to **Electrical Fixtures** (this is the
   step no connector automates — it is a dialog). Keep "Always vertical" off.
3. Geometry in family mm: cover plate 70 × 115 × 10 off the host face (+Z of the face-based
   template); a small marker tab at +Y so orientation reads from the bounding box.
4. Four types (one per `place_device.kind`), all the same geometry in v1:
   `Receptacle_Duplex_120V`, `Receptacle_GFCI_120V`, `Receptacle_240V_NEMA_14-50`,
   `Switch_SinglePole`.
5. Save as `CHPT_ElectricalFixture_FaceBased.rfa`; Load into the template.
6. Verify (Cowork): `get_family_types` shows the four types under category Electrical Fixtures.

Vocabulary landing spot: `mep_types.json` → `device_families.{receptacle,gfci,receptacle_240,
switch}` = `{revit_family: "CHPT_ElectricalFixture_FaceBased", revit_type: <type>}`.

## 3. PVC DWV pipe type — `CHPT_Pipe_PVC_DWV` (proposal)

Manual, ~30 min (all click paths in the Manage / Systems ribbons):
1. Load the generic pipe fittings from the cloud library (§6): `Elbow - Generic`, `Tee - Generic`,
   `Coupling - Generic`, `Transition - Generic` (Pipe Fitting category).
2. Manage → MEP Settings → Mechanical Settings → Pipe Settings → **Segments and Sizes**: New
   Segment → material **PVC**, schedule **Schedule 40**; size table (nominal / ID / OD in mm):
   1¼" (31.75), 1½" (38.1), 2" (50.8), 2½" (63.5), 3" (76.2), 4" (101.6). These are the values
   the plugin snaps to (`MepSizes`, tolerance 2.5 mm): Part G stacks Ø51 → 50.8 and Ø76 → 76.2,
   `plumbing.json` drains 32 / 38 / 51 / 76.
3. Systems → Pipe → Edit Type → Duplicate `Default` → name `CHPT_Pipe_PVC_DWV` → **Routing
   Preferences**: Pipe Segment = the PVC Sch 40 segment (all sizes); Elbow = `Elbow - Generic`;
   Junction = `Tee - Generic`; Transition = `Transition - Generic`; Union = `Coupling - Generic`.
4. The piping system type `Sanitary` already exists — leave the name; the plugin reads it from
   `mep_types.json` `system_type_names.sanitary`.
5. Verify (Cowork): draw two Ø76 pipes meeting at a right angle with type `CHPT_Pipe_PVC_DWV` and
   connect them — the elbow must insert (this exact step failed in the spike for want of an elbow
   family); read the pipe's Diameter (expect 76.2 mm).

Vocabulary landing spot: `mep_types.json` → `pipe_types.sanitary: "CHPT_Pipe_PVC_DWV"`,
`system_type_names.sanitary: "Sanitary"`. v1 scope is sanitary DWV only (Phase 6 gate decision 5);
`vent` / `supply_*` rows stay placeholders.

## 4. Conduit type — confirm, do not create

`Conduit with Fittings : Conduit` (standard EMT) exists with all five `… - Aluminum : Standard`
fittings and the auto elbow works (spike step 5). Confirm and record:
- `mep_types.json` → `conduit_type: "Conduit with Fittings : Conduit"` (the literal type name —
  the plugin looks the type up by `Name`, so record exactly what the Type Selector shows).
- `conduit_diameter_mm: 19.05` (¾" EMT). The current placeholder 21 is not a trade size; the plugin
  snaps within 2.5 mm so 21 → 19.05 works, but the catalog should carry the real one (golden re-run
  when it lands).

## 5. Shared parameters — the five `CHPT_*` text parameters (Phase 7 / 8)

`set_parameter` writes only the params in `packages/contracts/ops/param_allowlist.json`, each on the
categories it lists. The executor fails `unknown_param` when a parameter is not bound to the
element's category in the model — so the binding IS the switch that turns Phase 7 on.

Manual, ~20 min:
1. Manage → **Shared Parameters** → Create a new file `CHPT_SharedParameters.txt` (proposal: keep
   it next to the template; whether it also lives in this repo is gate question G4) → group
   `Chapter Finishes`.
2. Add five parameters, all **Text**, discipline Common:
   `CHPT_Finish_Material`, `CHPT_Finish_Color`, `CHPT_Product_SKU`, `CHPT_Spec_Section`,
   `CHPT_Render_Ref`.
3. Manage → **Project Parameters** → Add → Shared parameter → each of the five, **Instance**,
   group under Identity Data, bound to categories exactly per the allowlist:

   | parameter | categories (allowlist word → Revit category) |
   |---|---|
   | `CHPT_Finish_Material`, `CHPT_Finish_Color`, `CHPT_Render_Ref` | walls → Walls; casework → Casework |
   | `CHPT_Product_SKU`, `CHPT_Spec_Section` | Walls, Doors, Windows, Furniture (+ Furniture Systems, Specialty Equipment), Casework, Plumbing Fixtures, Electrical Fixtures (+ Lighting Devices, Electrical Equipment) |

   `Comments` needs nothing: it is the built-in `ALL_MODEL_INSTANCE_COMMENTS` on every element.
4. Save the template. Verify (Cowork): `get_parameters_for_category` for Walls, Doors, Plumbing
   Fixtures shows the expected subset; a wall must NOT show `CHPT_Product_SKU` missing, a door must
   NOT show `CHPT_Finish_Material`.

The enrollment directory `%AppData%\ChapterHub\catalogs\` gets `param_allowlist.json` copied from
the repo beside `mep_types.json` and `clash_prisms.json` (the add-in fails `catalog_missing`
otherwise).

## 6. Cloud-library loads

From the "Load Autodesk Family" dialog (the local library is absent on the workstation):
- Pipe fittings: `Elbow - Generic`, `Tee - Generic`, `Coupling - Generic`, `Transition - Generic`.
- A window family for `create_window`: `Fixed` (or Chapter's standard) — record family + type
  names for `new_construction_types.json` window rows.
- Nothing else in v1 (furniture / casework / plumbing-fixture families are the Phase 5 catalog
  vocabulary Eran connects through knowledge later; the sim uses `_PLACEHOLDER` names there).

## 7. Cowork prompt — the automatable parts (paste into Claude Cowork on the workstation)

The AUTOM8LABS connector can build and load families (`create_family`, `load_family_into_project`,
`capture_family_view`, `get_family_types`), read parameters (`get_parameters_for_category`,
`get_element_parameters`) and place test instances; it cannot change a family's category, edit
routing preferences, or create/bind shared parameters — those are the **STOP** points where Eran
does the dialog and says "done".

> Open the Chapter project template (never a client model) in Revit 2027 with the AUTOM8LABS
> connector attached. Follow docs/REVIT_TEMPLATE_CONTENT.md in
> github.com/eranfromchapter/Design-and-create-plans-in-Revit (branch claude/phase-7-aidm):
> §1 build and load CHPT_Door_SingleFlush (types 813x2032, 915x2032) from Door.rft — hinge at −X,
> leaf swinging to +Y; then STOP and ask me to check the swing in the family editor before loading.
> §2 build the face-based fixture family from "Generic Model face based" with the four types; STOP
> before the category change — I will set the category to Electrical Fixtures in the dialog and say
> "done"; then load it. §3 load the four generic pipe fittings; STOP — I will create the PVC Sch 40
> segment, the size table and the CHPT_Pipe_PVC_DWV routing preferences by hand and say "done";
> then draw two Ø76 pipes at a right angle with that type, connect them, and report the elbow
> family used and the Diameter value. §4 report the exact conduit type name and its fittings. §5
> STOP — I will create and bind the five CHPT_ shared parameters; when I say "done", read the
> parameters of one wall, one door and one plumbing fixture and report which CHPT_ params each
> shows. §6 load a window family and report its name. Write every raw name and number Revit
> returns, never invent one, and finish with the "as created" table from §8 filled in so I can
> upload it.

## 8. "As created" table — Eran fills this in and uploads it

| slot | proposed name | as created (exact Revit name) | verified how |
|---|---|---|---|
| door family / types | `CHPT_Door_SingleFlush` / `813x2032`, `915x2032` | | HandOrientation +X, FacingOrientation +Y on a (0,0)→(4000,0) wall |
| pocket door | `CHPT_Door_Pocket` / `813x2032` | | leafless in plan |
| device family / 4 types | `CHPT_ElectricalFixture_FaceBased` / `Receptacle_Duplex_120V`, `Receptacle_GFCI_120V`, `Receptacle_240V_NEMA_14-50`, `Switch_SinglePole` | | category Electrical Fixtures; hosted placement on a wall face |
| pipe type | `CHPT_Pipe_PVC_DWV` | | elbow inserts; Diameter 76.2 |
| pipe fittings | `Elbow - Generic`, `Tee - Generic`, `Coupling - Generic`, `Transition - Generic` | | routing preferences show them |
| system type | `Sanitary` (exists) | | |
| conduit type / size | `Conduit with Fittings : Conduit` / 19.05 | | |
| shared parameters | the five `CHPT_*` (Text, instance) | | bound categories per §5 table |
| window family / type | `Fixed` / … | | |

## 9. Definition of done

- Every row of §8 has an "as created" name; the catalogs (`mep_types.json`,
  `new_construction_types.json`, `param_allowlist.json` — names only) are updated **by Eran or from
  his table**, `_PLACEHOLDER` suffixes removed row by row, goldens re-run where a value changed
  (`conduit_diameter_mm`).
- `docs/MANUAL_REVIT_TEST.md` Pre-Phase-6 stage-2 rows, the Phase 6 gate and the Phase 7 gate can
  run against the template.
- Nothing in this file becomes a catalog value without that table: the pipeline never invents
  vocabulary.
