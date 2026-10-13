import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import type { HtmlTagDescriptor, Plugin } from 'vite'
import { defineConfig } from 'vitest/config'

/** `npm run dev` and `npm run preview` talk to the compose stack: the same two paths nginx serves (nginx.conf). */
const toStack = (prefix: string, port: number) => ({
  target: `http://127.0.0.1:${port}`,
  rewrite: (path: string) => path.slice(prefix.length),
})

/**
 * Every route is loaded on demand, so the browser only learns which scripts the sign-in page needs after the entry
 * script has run: one extra round trip before anything is drawn. Sign-in is where every visit starts, so its scripts
 * are announced in the HTML and fetched alongside the entry. They stay separate files, out of the first chunk.
 */
function preloadFirstRoute(view: string): Plugin {
  return {
    name: 'preload-first-route',
    transformIndexHtml: {
      order: 'post',
      handler(html, context): HtmlTagDescriptor[] {
        const chunks = Object.values(context.bundle ?? {}).filter((file) => file.type === 'chunk')
        const first = chunks.find((chunk) => chunk.facadeModuleId?.endsWith(view) === true)
        if (first === undefined) return []
        return [first.fileName, ...first.imports]
          .filter((file) => !html.includes(file))
          .map((file) => ({
            tag: 'link',
            attrs: { rel: 'modulepreload', crossorigin: true, href: `/${file}` },
            injectTo: 'head',
          }))
      },
    },
  }
}

export default defineConfig({
  plugins: [vue(), preloadFirstRoute('/features/session/SignInView.vue')],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    proxy: {
      '/api': toStack('/api', 8400),
      '/login': toStack('/login', 8441),
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,vue}'],
      // The composition root is exercised by the Playwright journeys; the generated types and test helpers are not
      // code under test.
      exclude: ['src/**/*.test.ts', 'src/**/*.d.ts', 'src/main.ts', 'src/test/**'],
      reporter: ['text-summary', 'html'],
      // What the suite holds today, rounded down. A drop below it is a change someone should look at.
      thresholds: { statements: 99, branches: 94, functions: 100, lines: 99 },
    },
  },
})
