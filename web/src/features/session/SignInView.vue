<script setup lang="ts">
import { useMutation, useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { afterSignIn } from '@/router'
import { failureIn } from '@/shared/api/http'
import { people, tokenFor, type Person } from '@/shared/api/login'
import AppButton from '@/shared/ui/AppButton.vue'
import FailureNotice from '@/shared/ui/FailureNotice.vue'
import PersonTag from '@/shared/ui/PersonTag.vue'

import { signIn } from '@/shared/session'

const props = defineProps<{ next: string | null }>()

const router = useRouter()
const roster = useQuery({ queryKey: ['people'], queryFn: ({ signal }) => people(signal) })

// Signing in fetches the person's first token, so a login that is down is found here and not on the first question.
const entering = useMutation({
  mutationFn: async (person: Person) => {
    await tokenFor(person.subject, true)
    return person
  },
  onSuccess: (person) => {
    signIn(person)
    void router.push(afterSignIn(router, props.next))
  },
})

const status = computed(() => {
  if (roster.isPending.value) return 'Loading the six people.'
  if (entering.isPending.value) return `Signing in as ${entering.variables.value?.subject ?? ''}.`
  return ''
})
const rosterFailure = computed(() => (roster.error.value === null ? null : failureIn(roster.error.value)))
const enteringFailure = computed(() => (entering.error.value === null ? null : failureIn(entering.error.value)))
</script>

<template>
  <div class="page">
    <h1 tabindex="-1">Sign in as a member of staff</h1>
    <p class="lede">
      Six people work at this bank. Each belongs to a department and holds a clearance, and the policy library shows
      each of them a different set of documents.
    </p>
    <p class="demo">
      This is a demonstration with no passwords: anyone who can open this page can sign in as any of the six.
    </p>

    <p class="status" role="status">{{ status }}</p>

    <FailureNotice v-if="rosterFailure" :failure="rosterFailure" who="This page">
      <AppButton quiet @click="roster.refetch()">Try again</AppButton>
    </FailureNotice>
    <FailureNotice
      v-if="enteringFailure"
      :failure="enteringFailure"
      :who="entering.variables.value?.subject ?? 'This person'"
    />

    <ul class="roster" aria-label="Staff you can sign in as">
      <li v-for="person in roster.data.value" :key="person.subject">
        <PersonTag :person="person" />
        <AppButton :disabled="entering.isPending.value" @click="entering.mutate(person)">
          Sign in as {{ person.subject }}
        </AppButton>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.page {
  max-width: 44rem;
}

h1 {
  margin: 0;
  font-size: 1.75rem;
  line-height: 1.2;
}

.lede {
  margin: 0.75rem 0 0;
  font-size: 1.125rem;
}

.demo {
  margin: 0.75rem 0 0;
  padding: 0.6rem 0.9rem;
  border-left: 4px solid var(--ink);
  background: var(--band);
}

.status {
  min-height: 1.5rem;
  margin: 1rem 0 0.25rem;
  color: var(--ink-soft);
}

/* Room for exactly six rows before they arrive, so nothing below the list moves when they do: a row is a fixed height
   and the list reserves six of them. */
.roster {
  --row: 6.25rem;

  box-sizing: border-box;
  min-height: calc(6 * var(--row) + 2px);
  margin: 0;
  padding: 0;
  border-top: 2px solid var(--ink);
  list-style: none;
}

.roster li {
  display: flex;
  box-sizing: border-box;
  gap: 1rem;
  align-items: center;
  justify-content: space-between;
  height: var(--row);
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--rule);
}
</style>
