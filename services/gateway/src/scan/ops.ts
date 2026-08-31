// Commit #0 ops construction: approved scan layout -> deterministic op list.
// Pure function; the envelope builder re-validates every op against the registry
// before signing, and this module's output must always pass that gate.
import type { ChapterLayout } from "@chapter/contracts";
import type { OpInput } from "../envelope/builder.js";

export interface Commit0Options {
  /** Human-confirmed ceiling height (mm); replaces the converter's assumption. */
  ceilingMm: number;
  /** Pre-indexed point-cloud blob ref -> link_pointcloud op (last). */
  cloudRef?: string;
}

const WALL_FLAG_KEYS = [
  "is_exterior",
  "is_load_bearing",
  "is_demising",
  "is_wet_wall",
  "fire_rating_hr",
] as const;

export function opsFromScanLayout(layout: ChapterLayout, opts: Commit0Options): OpInput[] {
  const ops: OpInput[] = [
    {
      op: "create_level",
      args: { name: layout.meta.level, elevation: layout.meta.levels?.floor_z ?? 0 },
    },
  ];

  for (const wall of [...layout.walls].sort((a, b) => a.id.localeCompare(b.id))) {
    const flags: Record<string, unknown> = {};
    for (const key of WALL_FLAG_KEYS) {
      if (wall[key] !== undefined) flags[key] = wall[key];
    }
    const args: Record<string, unknown> = {
      id: wall.id,
      start: wall.start,
      end: wall.end,
      revit_type: wall.revit_type,
      height: opts.ceilingMm,
      phase: "existing",
    };
    if (Object.keys(flags).length) args["flags"] = flags;
    ops.push({ op: "create_wall", args });
  }

  for (const door of [...layout.doors].sort((a, b) => a.id.localeCompare(b.id))) {
    ops.push({
      op: "create_door",
      args: {
        id: door.id,
        host_wall_id: door.host_wall_id,
        offset: door.offset,
        revit_type: door.revit_type,
        width: door.width,
        height: door.height,
        swing: door.swing ?? "L",
      },
    });
  }

  for (const win of [...layout.windows].sort((a, b) => a.id.localeCompare(b.id))) {
    ops.push({
      op: "create_window",
      args: {
        id: win.id,
        host_wall_id: win.host_wall_id,
        offset: win.offset,
        sill_height: win.sill_height,
        revit_type: win.revit_type,
        width: win.width,
        height: win.height,
      },
    });
  }

  if (opts.cloudRef) ops.push({ op: "link_pointcloud", args: { blob_ref: opts.cloudRef } });
  return ops;
}
