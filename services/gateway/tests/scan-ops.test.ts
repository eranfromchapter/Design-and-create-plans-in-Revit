// Commit #0 ops construction against the committed converter golden: order,
// counts, ceiling application, flag nesting, and registry validity (validateOps
// is the same gate the envelope builder applies before signing).
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { validateOps, type ChapterLayout } from "@chapter/contracts";
import { opsFromScanLayout } from "../src/scan/ops.js";

const GOLDEN = join(
  dirname(fileURLToPath(import.meta.url)),
  "..", "..", "..", "fixtures", "layouts", "2br_golden.json",
);
const layout = JSON.parse(readFileSync(GOLDEN, "utf8")) as ChapterLayout;

describe("opsFromScanLayout", () => {
  it("emits level -> walls -> doors -> windows in id order, registry-valid", () => {
    const ops = opsFromScanLayout(layout, { ceilingMm: 2700 });
    expect(ops).toHaveLength(1 + 17 + 5 + 3);
    expect(ops[0]).toEqual({
      op: "create_level",
      args: { name: "Level 1", elevation: 0 },
    });
    expect(ops.slice(1, 18).map((o) => o.op)).toEqual(Array(17).fill("create_wall"));
    expect(ops.slice(1, 18).map((o) => o.args["id"])).toEqual(
      [...layout.walls.map((w) => w.id)].sort(),
    );
    expect(ops.slice(18, 23).every((o) => o.op === "create_door")).toBe(true);
    expect(ops.slice(23).every((o) => o.op === "create_window")).toBe(true);
    expect(validateOps(ops)).toBeNull();
  });

  it("applies the confirmed ceiling to every wall and stamps phase=existing", () => {
    const ops = opsFromScanLayout(layout, { ceilingMm: 2600 });
    for (const op of ops.filter((o) => o.op === "create_wall")) {
      expect(op.args["height"]).toBe(2600);
      expect(op.args["phase"]).toBe("existing");
    }
  });

  it("appends link_pointcloud last when a cloud ref exists", () => {
    const ops = opsFromScanLayout(layout, { ceilingMm: 2700, cloudRef: "poly-cloud-01" });
    expect(ops.at(-1)).toEqual({ op: "link_pointcloud", args: { blob_ref: "poly-cloud-01" } });
    expect(validateOps(ops)).toBeNull();
  });

  it("nests wall flags only when the layout carries them", () => {
    const ops = opsFromScanLayout(layout, { ceilingMm: 2700 });
    // converter never invents structural flags (catalog rule: human-supplied)
    for (const op of ops.filter((o) => o.op === "create_wall")) {
      expect(op.args["flags"]).toBeUndefined();
    }
    const flagged: ChapterLayout = {
      ...layout,
      walls: [{ ...layout.walls[0]!, is_demising: true, fire_rating_hr: 1 }],
      doors: [],
      windows: [],
    };
    const [, wall] = opsFromScanLayout(flagged, { ceilingMm: 2700 });
    expect(wall!.args["flags"]).toEqual({ is_demising: true, fire_rating_hr: 1 });
  });

  it("carries door swing/type and window sill through to op args", () => {
    const ops = opsFromScanLayout(layout, { ceilingMm: 2700 });
    const door = ops.find((o) => o.op === "create_door")!;
    expect(door.args["swing"]).toBe("L");
    expect(door.args["revit_type"]).toBe("CHPT_AsBuilt_Door_PLACEHOLDER");
    const win = ops.find((o) => o.op === "create_window")!;
    expect(win.args["sill_height"]).toBe(900);
  });
});
