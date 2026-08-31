// Regenerates src/generated/*.ts from packages/contracts/schemas/*.json.
// Pinned generator: json-schema-to-zod (see package.json). Run via `pnpm codegen` / `make codegen`.
import { jsonSchemaToZod } from "json-schema-to-zod";
import $RefParser from "@apidevtools/json-schema-ref-parser";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const schemasDir = join(here, "..", "..", "schemas");
const outDir = join(here, "..", "src", "generated");
mkdirSync(outDir, { recursive: true });

const targets = [
  { file: "chapter-layout.v2.3.json", name: "chapterLayoutSchema", out: "chapter-layout.ts", type: "ChapterLayout" },
  { file: "brief.v1.json", name: "clientBriefSchema", out: "brief.ts", type: "ClientBrief" },
  { file: "command-envelope.v1.json", name: "commandEnvelopeSchema", out: "command-envelope.ts", type: "CommandEnvelope" },
  { file: "wss-messages.v1.json", name: "wssMessageSchema", out: "wss-messages.ts", type: "WssMessage" },
];

// json-schema-to-zod understands draft-7 tuple syntax (items: [...]) but not draft
// 2020-12 prefixItems; rewrite tuples so they generate real z.tuple(...) types.
function draft7Tuples(node) {
  if (Array.isArray(node)) return node.map(draft7Tuples);
  if (node === null || typeof node !== "object") return node;
  const out = {};
  for (const [k, v] of Object.entries(node)) out[k] = draft7Tuples(v);
  if (Array.isArray(out.prefixItems)) {
    out.items = out.prefixItems;
    delete out.prefixItems;
    delete out.minItems;
    delete out.maxItems;
  }
  return out;
}

for (const t of targets) {
  const schema = JSON.parse(readFileSync(join(schemasDir, t.file), "utf8"));
  // json-schema-to-zod does not resolve $refs — dereference (inline) them first.
  const deref = draft7Tuples(await $RefParser.dereference(schema, { dereference: { circular: false } }));
  delete deref.$id; // avoid the generator emitting id-based artifacts
  const module_ = jsonSchemaToZod(deref, { name: t.name, module: "esm", type: t.type });
  const header = `/* eslint-disable */\n// GENERATED from schemas/${t.file} by scripts/codegen.mjs — DO NOT EDIT.\n`;
  writeFileSync(join(outDir, t.out), header + module_);
  console.log(`generated src/generated/${t.out}`);
}
