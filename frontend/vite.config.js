import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The dev proxy: React runs on :5173, Django on :8000. When the
    // page asks for /api/..., Vite quietly forwards the request to
    // Django and hands the response back. To the browser it looks like
    // one server — which is exactly how production will work later,
    // when Django serves this built app itself.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
