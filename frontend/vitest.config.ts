import { defineConfig, mergeConfig } from "vitest/config"
import viteConfig from "./vite.config"

// Kept separate from vite.config.ts so `tsc -b` (build) never type-checks the
// test block — Vitest's bundled Vite types otherwise clash with Vite 8.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: "./src/test-setup.ts",
    },
  }),
)
