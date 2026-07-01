import path from "node:path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// base '/app/' so built asset URLs resolve under the FastAPI static mount (AC1).
// esbuild jsx automatic keeps the Vitest transform emitting the React 17+ runtime
// (no per-file React import); the production build still goes through plugin-react.
export default defineConfig({
  base: "/app/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  esbuild: { jsx: "automatic" },
})
