import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // FILE SERVING (Vite 8.4): 'extended' applies the file-access
    // checks to modules loaded by plugins too, and allow: [] switches
    // the dev server to an allow-list — it only serves files that are
    // referenced from the entry point (imports, CSS url(), HTML), not
    // anything else under the project root. This is the mode Vite
    // plans to make the default in its next major, so adopting it now
    // hardens `npm run dev` against file-disclosure tricks and avoids
    // a surprise breakage later. Dev-only: production builds are
    // served by Django and are unaffected.
    fs: {
      strict: 'extended',
      allow: [],
    },
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
