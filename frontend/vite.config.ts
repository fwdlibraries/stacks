import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/lti': 'http://localhost:8000',
    },
  },
  build: {
    rollupOptions: {
      /**
       * Two entry points:
       * - editor: full SPA with auth, WebSockets, drag-and-drop
       * - public: lightweight unauthenticated student list view
       *
       * Students loading a public list don't download the editor bundle.
       */
      input: {
        editor: resolve(__dirname, 'index.html'),
        public: resolve(__dirname, 'public.html'),
      },
    },
  },
})
