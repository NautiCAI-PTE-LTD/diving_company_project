import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    open: true,
    proxy: {
      // Forward API calls to the FastAPI/Flask backend you'll add later
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // Large reports (700+ photos) — PDF generate can run several minutes
        timeout: 900_000,
      },
    },
  },
})
