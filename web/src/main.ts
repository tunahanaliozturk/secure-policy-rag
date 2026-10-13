import './styles/tokens.css'

import { VueQueryPlugin } from '@tanstack/vue-query'
import { createApp } from 'vue'
import { createWebHistory } from 'vue-router'

import App from './App.vue'
import { queryClientConfig } from './query'
import { createAppRouter } from './router'

const router = createAppRouter(createWebHistory(), (path) => window.location.assign(path))
const app = createApp(App).use(router).use(VueQueryPlugin, { queryClientConfig })

// Every view is loaded when its route is, so the first one arrives a moment after the shell. Mounting before it does
// paints the header with the footer directly under it, and then moves the footer when the view lands: a layout shift
// of 0.114 on a phone viewport, measured. So the page is mounted once the first route is ready, and also when it
// failed to load: the shell is what says so (router.ts).
void router
  .isReady()
  .catch(() => undefined)
  .then(() => app.mount('#app'))
