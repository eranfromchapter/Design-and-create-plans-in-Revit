// SI-4 at the signer (Phase 7, P7-10): every set_parameter op must name a parameter in
// ops/param_allowlist.json that allows the target's category. The category is derived from
// the logical-id prefix (the layout id patterns: W walls, D doors, N windows, K casework,
// F furniture, E electrical); anything else has no category and may only take "*" params.
// F -> furniture is sound because every allowlisted param that lists `plumbing` also lists
// `furniture` (param-allowlist.test.ts pins that invariant, so an allowlist edit that breaks
// it forces a hookups-aware rule deliberately). The sim re-checks by record category and
// the plugin by BuiltInCategory + storage type — three independent enforcers.
import { paramAllowlist } from "@chapter/contracts";
import type { OpInput } from "./builder.js";

export type ParamCategory =
  | "walls"
  | "doors"
  | "windows"
  | "furniture"
  | "casework"
  | "plumbing"
  | "electrical";

const PREFIX_CATEGORY: Record<string, ParamCategory> = {
  W: "walls",
  D: "doors",
  N: "windows",
  K: "casework",
  F: "furniture",
  E: "electrical",
};

const BY_NAME = new Map(paramAllowlist.params.map((p) => [p.name, p]));

export function categoryForTarget(targetId: string): ParamCategory | null {
  const m = /^([A-Z]{1,2})-\d{2,4}$/.exec(targetId);
  return m ? (PREFIX_CATEGORY[m[1]!] ?? null) : null;
}

export interface AllowlistProblem {
  index: number;
  op: string;
  reason: "param_not_allowlisted";
  detail: string;
}

export function isParamAllowed(param: string, category: ParamCategory | null): boolean {
  const entry = BY_NAME.get(param);
  if (!entry) return false;
  if (entry.categories.includes("*")) return true;
  return category !== null && entry.categories.includes(category);
}

/** null when every set_parameter op is allowlisted for its target's category. */
export function checkParamAllowlist(ops: OpInput[]): AllowlistProblem | null {
  for (let index = 0; index < ops.length; index++) {
    const op = ops[index]!;
    if (op.op !== "set_parameter") continue;
    const param = String(op.args["param"] ?? "");
    const target = String(op.args["target_id"] ?? "");
    const entry = BY_NAME.get(param);
    if (!entry) {
      return { index, op: op.op, reason: "param_not_allowlisted", detail: `param ${param} is not in ops/param_allowlist.json` };
    }
    if (entry.categories.includes("*")) continue;
    const category = categoryForTarget(target);
    if (category === null) {
      return {
        index, op: op.op, reason: "param_not_allowlisted",
        detail: `target ${target} has no allowlisted category; ${param} allows ${entry.categories.join(", ")}`,
      };
    }
    if (!entry.categories.includes(category)) {
      return {
        index, op: op.op, reason: "param_not_allowlisted",
        detail: `${param} is not allowed on ${category} (${target}); allowed: ${entry.categories.join(", ")}`,
      };
    }
  }
  return null;
}
