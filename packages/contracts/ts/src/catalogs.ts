// Catalog JSON the gateway reads at runtime (Phase 7): the product catalog (its
// catalog_version pins finish selections) and the set_parameter allowlist (SI-4, enforced
// by gateway + revit-sim + plugin). Same import mechanism as ops/registry.json in
// verify.ts — no schema, no codegen; the JSON files stay the single source of truth.
import products from "../../catalogs/products.json" with { type: "json" };
import allowlist from "../../ops/param_allowlist.json" with { type: "json" };

export interface ProductSku {
  sku: string;
  manufacturer: string;
  model: string;
  description: string;
  finish_tier: "economy" | "standard" | "premium" | "luxury";
  csi_section: string;
  unit: string;
}

export interface ProductsCatalog {
  catalog_version: string;
  skus: ProductSku[];
}

export interface ParamAllowlistEntry {
  name: string;
  kind: string;
  /** vocabulary: walls, doors, windows, furniture, casework, plumbing, electrical, "*" */
  categories: string[];
}

export interface ParamAllowlist {
  allowlist_version: string;
  params: ParamAllowlistEntry[];
}

export const productsCatalog: ProductsCatalog = products as unknown as ProductsCatalog;
export const paramAllowlist: ParamAllowlist = allowlist as unknown as ParamAllowlist;
