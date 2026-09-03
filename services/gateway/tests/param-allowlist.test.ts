// SI-4 at the signer (Phase 7): set_parameter ops must name an allowlisted param that
// allows the target's category (by logical-id prefix). The allowlist JSON is the source
// of truth; these tests pin the rule AND the invariant the F -> furniture mapping relies on.
import { describe, expect, it } from "vitest";
import { paramAllowlist, productsCatalog } from "@chapter/contracts";
import { categoryForTarget, checkParamAllowlist, isParamAllowed } from "../src/envelope/param-allowlist.js";
import { buildEnvelope } from "../src/envelope/builder.js";
import { newProjectKeypair } from "../src/crypto/keystore.js";

const MASTER = Buffer.from("07".repeat(32), "hex");

describe("param allowlist (SI-4)", () => {
  it("derives the category from the logical-id prefix", () => {
    expect(categoryForTarget("W-001")).toBe("walls");
    expect(categoryForTarget("D-012")).toBe("doors");
    expect(categoryForTarget("N-003")).toBe("windows");
    expect(categoryForTarget("K-001")).toBe("casework");
    expect(categoryForTarget("F-0017")).toBe("furniture");
    expect(categoryForTarget("E-045")).toBe("electrical");
    expect(categoryForTarget("R-001")).toBeNull(); // rooms are not elements
    expect(categoryForTarget("P-001")).toBeNull(); // pipes: only "*" params
    expect(categoryForTarget("Q-001")).toBeNull();
    expect(categoryForTarget("revit:123")).toBeNull();
    expect(categoryForTarget("")).toBeNull();
  });

  it("the allowlist entries decide: name, then category, '*' everywhere", () => {
    expect(isParamAllowed("CHPT_Product_SKU", "walls")).toBe(true);
    expect(isParamAllowed("CHPT_Product_SKU", "furniture")).toBe(true);
    expect(isParamAllowed("CHPT_Finish_Material", "walls")).toBe(true);
    expect(isParamAllowed("CHPT_Finish_Material", "doors")).toBe(false);
    expect(isParamAllowed("CHPT_Finish_Material", "furniture")).toBe(false);
    expect(isParamAllowed("CHPT_Render_Ref", "casework")).toBe(true);
    expect(isParamAllowed("CHPT_Render_Ref", "electrical")).toBe(false);
    expect(isParamAllowed("Comments", null)).toBe(true); // "*"
    expect(isParamAllowed("Comments", "walls")).toBe(true);
    expect(isParamAllowed("Mark", "walls")).toBe(false); // geometry/identity params never
    expect(isParamAllowed("Phase Demolished", "walls")).toBe(false);
    expect(isParamAllowed("CHPT_Product_SKU", null)).toBe(false); // no category, not "*"
  });

  it("checkParamAllowlist reports the first offending op with a stable reason", () => {
    const ok = [
      { op: "set_parameter", args: { target_id: "W-001", param: "CHPT_Finish_Material", value: "Placeholder Mfg PH-02" } },
      { op: "set_parameter", args: { target_id: "D-001", param: "CHPT_Product_SKU", value: "x" } },
      { op: "set_parameter", args: { target_id: "W-004", param: "Comments", value: "finish conflict" } },
      { op: "set_parameter", args: { target_id: "P-001", param: "Comments", value: "stack" } },
      { op: "create_wall", args: { id: "W-099" } }, // other ops are not this check's business
    ];
    expect(checkParamAllowlist(ok)).toBeNull();
    expect(checkParamAllowlist([
      ok[0]!,
      { op: "set_parameter", args: { target_id: "D-001", param: "CHPT_Finish_Material", value: "x" } },
    ])).toMatchObject({ index: 1, op: "set_parameter", reason: "param_not_allowlisted" });
    expect(checkParamAllowlist([
      { op: "set_parameter", args: { target_id: "W-001", param: "Mark", value: "A1" } },
    ])?.detail).toMatch(/not in ops\/param_allowlist\.json/);
    expect(checkParamAllowlist([
      { op: "set_parameter", args: { target_id: "P-001", param: "CHPT_Product_SKU", value: "x" } },
    ])?.detail).toMatch(/no allowlisted category/);
    expect(checkParamAllowlist([
      { op: "set_parameter", args: { param: "CHPT_Product_SKU", value: "x" } }, // missing target
    ])).not.toBeNull();
  });

  it("invariant: every param that lists `plumbing` also lists `furniture` (F -> furniture is sound)", () => {
    for (const p of paramAllowlist.params) {
      if (p.categories.includes("plumbing")) {
        expect(p.categories, `${p.name} lists plumbing without furniture`).toContain("furniture");
      }
    }
  });

  it("the allowlist vocabulary is closed and the catalog exports are readable", () => {
    const vocabulary = new Set(["walls", "doors", "windows", "furniture", "casework", "plumbing", "electrical", "*"]);
    for (const p of paramAllowlist.params) {
      for (const c of p.categories) expect(vocabulary.has(c), `${p.name}: ${c}`).toBe(true);
      expect(["finish", "product", "spec", "comment"]).toContain(p.kind);
    }
    expect(productsCatalog.catalog_version).toMatch(/^\d+\.\d+\.\d+(-[a-z0-9.-]+)?$/);
    expect(productsCatalog.skus.length).toBeGreaterThan(0);
    for (const sku of productsCatalog.skus) expect(sku.sku.endsWith("_PLACEHOLDER"), sku.sku).toBe(true);
  });

  it("buildEnvelope refuses an off-allowlist set_parameter BEFORE signing (the signer half of SI-4)", () => {
    const keypair = newProjectKeypair(MASTER);
    const base = {
      projectId: "1f6b3c58-7a2d-4e90-9c41-2b8f5d6a7e01",
      workstationId: "ws-01",
      seq: 1,
      ttlS: 600,
      issuedAt: new Date("2026-09-03T12:00:00Z"),
    };
    const good = buildEnvelope(
      { ...base, ops: [{ op: "set_parameter", args: { target_id: "W-001", param: "CHPT_Product_SKU", value: "x" } }] },
      keypair.seedEnc, MASTER,
    );
    expect(good.ok).toBe(true);
    const bad = buildEnvelope(
      { ...base, ops: [{ op: "set_parameter", args: { target_id: "W-001", param: "Mark", value: "x" } }] },
      keypair.seedEnc, MASTER,
    );
    expect(bad.ok).toBe(false);
    if (!bad.ok) expect(bad.error).toMatchObject({ index: 0, reason: "param_not_allowlisted" });
    const wrongCategory = buildEnvelope(
      { ...base, ops: [{ op: "set_parameter", args: { target_id: "E-001", param: "CHPT_Finish_Material", value: "x" } }] },
      keypair.seedEnc, MASTER,
    );
    expect(wrongCategory.ok).toBe(false);
    // registry validation still runs first: a malformed op is invalid_args, not the allowlist
    const malformed = buildEnvelope(
      { ...base, ops: [{ op: "set_parameter", args: { target_id: "W-001" } }] },
      keypair.seedEnc, MASTER,
    );
    expect(malformed.ok).toBe(false);
    if (!malformed.ok) expect(malformed.error.reason).not.toBe("param_not_allowlisted");
  });
});
