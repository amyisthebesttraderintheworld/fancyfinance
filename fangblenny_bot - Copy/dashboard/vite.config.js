import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],

  server: {
    allowedHosts: 'all',
    port: 5173,
  },

  build: {
    // Inline small assets so the app works without extra requests in Telegram's
    // constrained network environment
    assetsInlineLimit: 8192,
    sourcemap: false,
  },
})
