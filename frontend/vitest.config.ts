import { defineConfig } from "vitest/config";

// Deliberately does not load @vitejs/plugin-react: that plugin exists to give
// the dev server Fast Refresh, which tests never use, and loading it here drags
// in Vite's types a second time (Vitest pins its own copy) which breaks the
// build. esbuild picks up `jsx: react-jsx` from tsconfig.app.json on its own.
export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
