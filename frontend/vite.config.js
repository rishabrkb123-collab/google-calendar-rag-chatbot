import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/auth': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
      '/chat': 'http://localhost:8000',
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test-setup.js',
    fakeTimers: {
      shouldAdvanceTime: true,
    },
  },
})
