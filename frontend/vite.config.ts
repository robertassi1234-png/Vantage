import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
// Test configuration lives in vitest.config.ts: Vitest bundles its own Vite,
// so mixing the two configs here makes the plugin types collide under `tsc -b`.
export default defineConfig({
  plugins: [react()],
})
