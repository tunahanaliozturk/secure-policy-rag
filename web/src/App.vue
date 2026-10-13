<script setup lang="ts">
import { useQueryClient } from '@tanstack/vue-query'
import { RouterLink, RouterView, useRouter } from 'vue-router'

import { loadFailure } from '@/router'
import { forgetTokens } from '@/shared/api/tokens'
import { signedIn, signOut } from '@/shared/session'

const router = useRouter()
const queries = useQueryClient()

// Signing out drops everything this person could see from memory: the tokens, and every answer and excerpt the page
// has cached, so the next person does not start on the last one's reading. It also ends what is under way: requests
// in flight are cancelled, and a token still on its way from the login is thrown away when it lands (tokens.ts).
async function leave(): Promise<void> {
  signOut()
  forgetTokens()
  await queries.cancelQueries()
  queries.clear()
  await router.push({ name: 'sign-in' })
}
</script>

<template>
  <a class="skip" href="#content">Skip to the page content</a>
  <header class="bar">
    <div class="inner">
      <p class="desk">Policy desk</p>
      <nav aria-label="Pages">
        <RouterLink :to="{ name: 'ask' }">Ask</RouterLink>
        <RouterLink :to="{ name: 'compare' }">Ask as everyone</RouterLink>
      </nav>
      <div v-if="signedIn" class="session">
        <span
          >Signed in as <strong>{{ signedIn.subject }}</strong></span
        >
        <RouterLink :to="{ name: 'sign-in', query: { next: $route.fullPath } }">Change person</RouterLink>
        <button type="button" @click="leave">Sign out</button>
      </div>
      <div v-else class="session">
        <span>Nobody is signed in</span>
        <RouterLink :to="{ name: 'sign-in' }">Sign in</RouterLink>
      </div>
    </div>
  </header>
  <main id="content" tabindex="-1">
    <!-- In place of the view, not above it: the page that was asked for is not there, and the one before it is not
         what the person wanted. The heading keeps the page a page for a screen reader. -->
    <div v-if="loadFailure !== null" class="unloaded" role="alert">
      <h1>This page could not be loaded</h1>
      <p>A part of it did not arrive from the server. Check the connection, then load it again.</p>
      <a :href="loadFailure">Load it again</a>
    </div>
    <RouterView v-else />
  </main>
  <footer>
    <p>A demonstration. The policies, the people and every identifier in them are invented.</p>
  </footer>
</template>

<style scoped>
.skip {
  position: absolute;
  left: -200vw;
  padding: 0.5rem 0.75rem;
  background: var(--ink);
  color: #fff;
}

.skip:focus {
  left: 0.5rem;
  top: 0.5rem;
  z-index: 1;
}

.bar {
  border-top: 6px solid var(--green);
  border-bottom: 1px solid var(--rule);
}

.inner {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 2rem;
  align-items: baseline;
  max-width: var(--page);
  margin: 0 auto;
  padding: 0.75rem 1.5rem;
}

.desk {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 700;
  letter-spacing: -0.01em;
}

nav {
  display: flex;
  flex: 1;
  gap: 1.5rem;
}

a {
  color: var(--green);
}

nav a {
  color: var(--ink);
  text-decoration: none;
}

nav a:hover {
  text-decoration: underline;
}

nav a.router-link-active {
  font-weight: 650;
  box-shadow: 0 2px 0 var(--green);
}

.session {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 1rem;
  align-items: baseline;
}

.session strong {
  text-transform: capitalize;
}

.session button {
  padding: 0;
  border: 0;
  background: none;
  color: var(--green);
  font: inherit;
  text-decoration: underline;
  cursor: pointer;
}

main {
  max-width: var(--page);
  margin: 0 auto;
  padding: 2rem 1.5rem 3rem;
}

main:focus {
  outline: none;
}

.unloaded {
  margin-bottom: 1.5rem;
  padding: 0.75rem 1rem;
  border-left: 4px solid var(--red);
  background: var(--red-wash);
}

.unloaded p {
  margin: 0 0 0.15rem;
}

.unloaded h1 {
  margin: 0 0 0.15rem;
  color: var(--red);
  font-size: 1.125rem;
  font-weight: 650;
}

footer {
  max-width: var(--page);
  margin: 0 auto;
  padding: 0 1.5rem 2rem;
  color: var(--ink-soft);
  font-size: 0.9375rem;
}

footer p {
  margin: 0;
  padding-top: 1rem;
  border-top: 1px solid var(--rule);
}

@media (max-width: 34rem) {
  .inner,
  main,
  footer {
    padding-left: 1rem;
    padding-right: 1rem;
  }
}
</style>
