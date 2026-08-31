/* eslint-disable */
// GENERATED from schemas/command-envelope.v1.json by scripts/codegen.mjs — DO NOT EDIT.
import { z } from "zod"

export const commandEnvelopeSchema = z.object({ "payload": z.string().min(2).max(2000000).describe("EnvelopeBody as a JSON string, produced once by the gateway"), "sig": z.string().regex(new RegExp("^[0-9a-f]{64}$")).describe("hex HMAC-SHA256 over the UTF-8 bytes of payload, keyed with HKDF(master, project_id)") }).strict().describe("Wire format for signed command envelopes. The gateway serializes EnvelopeBody ONCE (RFC 8785 canonical JSON) into `payload`; verifiers (plugin, revit-sim) compute HMAC-SHA256 over the exact received UTF-8 bytes of `payload` BEFORE any parsing, then parse and validate the body against $defs/EnvelopeBody and each op's args against ops/registry.json. Cross-language canonicalization is therefore never a verification dependency.")
export type CommandEnvelope = z.infer<typeof commandEnvelopeSchema>
