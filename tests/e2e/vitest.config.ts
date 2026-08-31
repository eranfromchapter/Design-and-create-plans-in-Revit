import { defineConfig } from "vitest/config";

// The e2e suite orchestrates real child processes against one Postgres — strictly
// serial, generous single-place timeouts (the only two timing knobs in the suite).
export default defineConfig({
  test: {
    fileParallelism: false,
    testTimeout: 60_000,
    hookTimeout: 60_000,
  },
});
