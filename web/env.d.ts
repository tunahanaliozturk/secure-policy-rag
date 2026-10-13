/// <reference types="vite/client" />

// For tools that read TypeScript without the Vue compiler (ESLint's type-aware rules). vue-tsc resolves each .vue
// file to its real type and never falls back to this.
declare module '*.vue' {
  import type { DefineComponent } from 'vue'

  const component: DefineComponent<object, object, unknown>
  export default component
}
