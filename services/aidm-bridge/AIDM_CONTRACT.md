# AIDM render contract (PROPOSED — a documented assumption)

Chapter's AIDM service is referenced by PLAN.md Part I (`AIDM_ENDPOINT`, "existing AIDM service;
mocked when empty") but its API is not known to this repository. `aidm_bridge.aidm.HttpRenderer`
implements the contract below; `MockRenderer` stands in whenever `AIDM_ENDPOINT` is empty. Gate
question G2 (docs/PHASE7_DESIGN.md) asks Eran to confirm or replace it. Like
`services/scan-converter/PROFILE.md`, this file is the assumption of record.

## Submit
`POST {AIDM_ENDPOINT}/v1/renders` — `Authorization: Bearer {AIDM_API_KEY}` when a key is set.
```json
{"render_id": "<blobRef charset>", "view": {"name": "plan", "kind": "plan|section|3d_hidden"},
 "prompt": "<the fixed template with the <style_tags> data block>",
 "control_maps": {"canny_png_base64": "...", "lines_png_base64": "..."},
 "size": {"width": 2048, "height": 1536}, "seed": 123456789}
```
Response `202 {"job_id": "<string>"}`. The bridge retries on 429/500/502/503/504 and transport
errors with sleeps of 0.5 s and 1.0 s between three attempts; any other 4xx fails the view
without retry. `seed` = the first four bytes of `sha256("<render_id>/<view name>")`, so a repeated
render request is reproducible on a seeded backend.

## Poll
`GET {AIDM_ENDPOINT}/v1/jobs/{job_id}` →
`{"status": "queued|running|succeeded|failed", "images": [{"png_base64": "..."}], "error": "..."}`.
The bridge polls every 1 s, at most 120 times, and never past the request deadline (120 s for the
whole `/render` call); the first image of a `succeeded` job is the render. Failures and timeouts
are `info` review items — the render is illustrative; the finish selection is the data.

## Not in the contract
Authentication beyond a bearer token, per-image URLs (only inline base64), callbacks/webhooks,
image sizes other than the exported view's, multiple images per view.
