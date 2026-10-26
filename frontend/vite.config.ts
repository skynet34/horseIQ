import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The FastAPI backend runs on :8000; the browser only ever talks to /api (no keys client-side).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
})
