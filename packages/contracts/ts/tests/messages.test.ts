import { describe, expect, it } from "vitest";
import { Ajv2020 } from "ajv/dist/2020.js";
import { fullFormats } from "ajv-formats/dist/formats.js";
import wssSchema from "../../schemas/wss-messages.v1.json" with { type: "json" };
import briefSchema from "../../schemas/brief.v1.json" with { type: "json" };
import { wssMessageSchema } from "../src/generated/wss-messages.js";
import { clientBriefSchema } from "../src/generated/brief.js";

const ajv = new Ajv2020({ strict: false, formats: fullFormats });
const validateWss = ajv.compile(wssSchema);
const validateBrief = ajv.compile(briefSchema);

const hello = {
  type: "hello",
  workstation_id: "ws-design-01",
  plugin_version: "0.1.0",
  last_committed_seq: 0,
  id_map_hash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
};

const commitResult = {
  type: "commit_result",
  envelope_id: "0b5e7a1c-2d3f-4a5b-8c9d-0e1f2a3b4c5d",
  status: "committed",
  id_map_delta: [{ logical_id: "W-001", element_id: 316222 }],
  errors: [],
};

const brief = {
  meta: {
    project_id: "6f1c2a3e-9b4d-4c5e-8f70-123456789abc",
    brief_version: 1,
    source_sessions: ["session_01"],
    confirmed_by_client: true,
  },
  rooms_required: [{ program: "bedroom", count: 2 }],
  adjacency_rules: [{ a: "kitchen", b: "dining", relation: "open_to" }],
  style_tags: ["prewar", "warm minimal"],
};

describe("wss-messages v1", () => {
  it("hello and commit_result validate (ajv + zod)", () => {
    for (const msg of [hello, commitResult]) {
      expect(validateWss(msg)).toBe(true);
      expect(() => wssMessageSchema.parse(msg)).not.toThrow();
    }
  });

  it("rejects an unknown message type and a malformed ack reason", () => {
    expect(validateWss({ type: "exec_shell", cmd: "rm -rf /" })).toBe(false);
    expect(
      validateWss({ type: "ack", envelope_id: hello.id_map_hash, status: "maybe" }),
    ).toBe(false);
  });
});

describe("brief v1", () => {
  it("a minimal brief validates (ajv + zod)", () => {
    expect(validateBrief(brief)).toBe(true);
    expect(() => clientBriefSchema.parse(brief)).not.toThrow();
  });

  it("rejects extra nested keys", () => {
    const bad = structuredClone(brief) as { rooms_required: Record<string, unknown>[] };
    bad.rooms_required[0]!["colour"] = "blue";
    expect(validateBrief(bad)).toBe(false);
  });
});
