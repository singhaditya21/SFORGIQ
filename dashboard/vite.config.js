import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Served from https://<user>.github.io/SFORGIQ/ on GitHub Pages, so the app must
// be built with that base path. import.meta.env.BASE_URL resolves to it, which
// is how the app locates sample-scan.json.
// https://vite.dev/config/
export default defineConfig({
  base: '/SFORGIQ/',
  plugins: [react()],
})
