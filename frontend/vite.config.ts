import { defineConfig, type Plugin } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

/**
 * Where the dev server proxies /api and /lti. Defaults to a backend on the host;
 * the dev compose file sets it to http://app:8000 inside the Docker network.
 */
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000'

/**
 * Dev-server rewrite so student URLs (/public/:orgSlug/:courseCode/:term) load the
 * lightweight public.html entry, mirroring the production nginx `try_files` rule.
 */
function publicEntryRewrite(): Plugin {
  return {
    name: 'stacks-public-entry-rewrite',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (req.url?.startsWith('/public/')) {
          req.url = '/public.html'
        }
        next()
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), publicEntryRewrite()],
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
  css: {
    preprocessorOptions: {
      scss: {
        api: 'modern-compiler',
        // Bootstrap 5.3's Sass still uses @import and global functions; silence
        // the Dart Sass deprecation noise coming from it.
        quietDeps: true,
        silenceDeprecations: ['import', 'global-builtin', 'color-functions', 'if-function'],
      },
    },
  },
  server: {
    port: 5173,
    // Vite rejects unknown Host headers (DNS-rebinding protection). Allow the dev
    // tunnel's hostname, set in VITE_ALLOWED_HOSTS (comma-separated; see the tunnel
    // service in deploy/docker-compose.dev.yml), plus Cloudflare quick tunnels.
    allowedHosts: [
      '.trycloudflare.com',
      ...(process.env.VITE_ALLOWED_HOSTS?.split(',').map((h) => h.trim()).filter(Boolean) ?? []),
    ],
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true, ws: true },
      '/lti': { target: apiTarget, changeOrigin: true },
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
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
