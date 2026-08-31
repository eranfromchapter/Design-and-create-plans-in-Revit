/* eslint-disable */
// GENERATED from schemas/wss-messages.v1.json by scripts/codegen.mjs — DO NOT EDIT.
import { z } from "zod"

export const wssMessageSchema = z.any().superRefine((x, ctx) => {
    const schemas = [z.object({ "type": z.literal("hello"), "workstation_id": z.string().regex(new RegExp("^[a-z0-9][a-z0-9_-]{0,63}$")), "plugin_version": z.string().min(1), "open_project_id": z.string().uuid().optional(), "last_committed_seq": z.number().int().gte(0).describe("read from Extensible Storage at document open; 0 = no committed envelope. The gateway resumes from the model's truth."), "id_map_hash": z.string().regex(new RegExp("^[0-9a-f]{64}$")).describe("hash of the persisted id-map; gateway-side mismatch marks the project dirty (drift gate)") }).strict(), z.object({ "type": z.literal("auth_ok") }).strict(), z.object({ "type": z.literal("auth_error"), "reason": z.string().min(1) }).strict(), z.object({ "type": z.literal("envelope"), "payload": z.string().min(2).max(2000000), "sig": z.string().regex(new RegExp("^[0-9a-f]{64}$")) }).strict().describe("gateway->plugin; payload/sig semantics per command-envelope.v1.json"), z.object({ "type": z.literal("ack"), "envelope_id": z.string().uuid(), "status": z.enum(["accepted","rejected"]), "reason": z.enum(["bad_signature","expired_ttl","bad_seq","unknown_op","invalid_args","wrong_workstation","wrong_document","schema_invalid","internal"]).describe("required when status=rejected").optional() }).strict(), z.object({ "type": z.literal("busy"), "envelope_id": z.string().uuid(), "reason": z.string().min(1) }).strict().describe("plugin->gateway: accepted but execution deferred (modal Revit session, no document open); gateway timeout policy applies"), z.object({ "type": z.literal("progress"), "envelope_id": z.string().uuid(), "ops_done": z.number().int().gte(0), "ops_total": z.number().int().gte(1) }).strict(), z.object({ "type": z.literal("commit_result"), "envelope_id": z.string().uuid(), "status": z.enum(["committed","rolled_back"]), "id_map_delta": z.array(z.object({ "logical_id": z.string().min(1), "element_id": z.number().int() }).strict()), "errors": z.array(z.object({ "op_index": z.number().int().gte(0).optional(), "code": z.string().min(1), "message": z.string() }).strict()) }).strict(), z.object({ "type": z.literal("export_ready"), "kind": z.enum(["view","parameters","deviation","model_state"]), "blob_ref": z.string().regex(new RegExp("^[a-z0-9][a-z0-9_-]{0,63}$")) }).strict(), z.object({ "type": z.literal("clash_delta"), "envelope_id": z.string().uuid(), "pairs": z.array(z.object({ "a_id": z.string().min(1), "b_id": z.string().min(1), "kind": z.string().min(1) }).strict()) }).strict().describe("returned with a rolled_back Commit #2; consumed by the merge-gate re-plan loop (Part G clash recovery)"), z.object({ "type": z.literal("state_divergence"), "last_valid_seq": z.number().int().gte(0), "id_map_hash": z.string().regex(new RegExp("^[0-9a-f]{64}$")), "detail": z.string().optional() }).strict().describe("plugin->gateway on detected undo/redo or missing HUB-created elements (DocumentChanged); gateway marks the project dirty and forces the drift gate"), z.object({ "type": z.literal("error"), "code": z.string().min(1), "message": z.string() }).strict()];
    const { errors, failed } = schemas.reduce<{
      errors: z.core.$ZodIssue[];
      failed: number;
    }>(
      ({ errors, failed }, schema) =>
        ((result) =>
          result.error
            ? {
                errors: [...errors, ...result.error.issues],
                failed: failed + 1,
              }
            : { errors, failed })(
          schema.safeParse(x),
        ),
      { errors: [], failed: 0 },
    );
    const passed = schemas.length - failed;
    if (passed !== 1) {
      ctx.addIssue(errors.length ? {
        path: [],
        code: "invalid_union",
        errors: [errors],
        message: "Invalid input: Should pass single schema. Passed " + passed,
      } : {
        path: [],
        code: "custom",
        errors: [errors],
        message: "Invalid input: Should pass single schema. Passed " + passed,
      });
    }
  }).describe("Every frame on the gateway<->plugin(sim) WSS channel, both directions, discriminated on `type`.")
export type WssMessage = z.infer<typeof wssMessageSchema>
