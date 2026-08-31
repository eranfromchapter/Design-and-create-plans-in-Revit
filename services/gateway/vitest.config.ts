import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Both DB-backed suites TRUNCATE the same database between tests — they must
    // never run concurrently (same rule as tests/e2e).
    fileParallelism: false,
  },
});
