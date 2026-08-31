import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { Ajv2020 } from "ajv/dist/2020.js";
import { fullFormats } from "ajv-formats/dist/formats.js";
import canonicalize from "canonicalize";
import layoutSchema from "../../schemas/chapter-layout.v2.3.json" with { type: "json" };
import { chapterLayoutSchema } from "../src/generated/chapter-layout.js";

const here = dirname(fileURLToPath(import.meta.url));
const raw = readFileSync(join(here, "..", "..", "..", "..", "fixtures", "layouts", "minimal.json"), "utf8");
const fixture = JSON.parse(raw) as Record<string, unknown>;

const ajv = new Ajv2020({ strict: false, formats: fullFormats });
const validate = ajv.compile(layoutSchema);

describe("chapter-layout v2.3", () => {
  it("minimal.json validates against the JSON Schema (ajv)", () => {
    const ok = validate(fixture);
    expect(validate.errors ?? []).toEqual([]);
    expect(ok).toBe(true);
  });

  it("minimal.json parses through the generated zod schema", () => {
    const parsed = chapterLayoutSchema.parse(fixture);
    expect(parsed.meta.schema_version).toBe("2.3");
    expect(parsed.walls).toHaveLength(4);
  });

  it("round-trips to canonical-byte-identical JSON (no defaults materialized)", () => {
    const parsed = chapterLayoutSchema.parse(fixture);
    expect(canonicalize(parsed)).toBe(canonicalize(fixture));
  });

  it("rejects a misspelled optional flag (nested strictness)", () => {
    const bad = structuredClone(fixture) as { walls: Record<string, unknown>[] };
    bad.walls[0]!["is_load_baering"] = true;
    expect(validate(bad)).toBe(false);
    expect(() => chapterLayoutSchema.parse(bad)).toThrow();
  });

  it("rejects a zero-size footprint", () => {
    const bad = structuredClone(fixture) as {
      furniture: { items: { footprint: [number, number] }[] }[];
    };
    bad.furniture[0]!.items[0]!.footprint = [2200, 0];
    expect(validate(bad)).toBe(false);
  });

  it("requires levels for pointcloud-sourced layouts (meta if/then)", () => {
    const bad = structuredClone(fixture) as { meta: Record<string, unknown> };
    bad.meta["scan"] = { source: "polycam", capture: "pointcloud" };
    delete bad.meta["levels"];
    expect(validate(bad)).toBe(false);
  });
});
