import react from '@vitejs/plugin-react'
import { searchForWorkspaceRoot, type Plugin } from 'vite'
import { defineConfig } from 'vitest/config'
import { APP_NAME } from './src/app-name.ts'

// - The dev server forwards /api to the FastAPI backend on port 8000, so no CORS is needed.
// - `shared/` (translation catalogs, provider test cases) sits beside `web/` and is allowed.
// - The page title comes from APP_NAME, and the Latin Archivo width-axis font is preloaded so
//   the logo does not change face after the first paint.
// - Vitest replaces CSS with empty strings, except `tokens.css`, which the contrast test
//   reads as text.

const FONT_FILE = 'archivo-latin-wdth-normal'

function appShell(): Plugin {
  return {
    name: 'app-shell',
    transformIndexHtml(html, ctx) {
      const font = ctx.bundle
        ? Object.keys(ctx.bundle).find((name) => name.includes(FONT_FILE) && name.endsWith('.woff2'))
        : `node_modules/@fontsource-variable/archivo/files/${FONT_FILE}.woff2`
      return {
        html: html.replace('%APP_NAME%', APP_NAME),
        tags: font
          ? [{ tag: 'link', attrs: { rel: 'preload', href: `/${font}`, as: 'font', type: 'font/woff2', crossorigin: '' }, injectTo: 'head' }]
          : [],
      }
    },
  }
}

export default defineConfig({
  plugins: [react(), appShell()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
    fs: {
      allow: [searchForWorkspaceRoot(process.cwd()), '../shared'],
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: { include: [/tokens\.css/] },
  },
})
