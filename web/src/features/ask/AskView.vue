<script setup lang="ts">
import { useMutation } from '@tanstack/vue-query'
import { computed, nextTick, watch } from 'vue'
import { useRouter, type RouteLocationRaw } from 'vue-router'

import { signedIn } from '@/shared/session'
import { failureIn } from '@/shared/api/http'
import { ask } from '@/shared/api/policy'
import ExcerptPanel from '@/shared/policy/ExcerptPanel.vue'
import QuestionForm from '@/shared/policy/QuestionForm.vue'
import StandInNote from '@/shared/policy/StandInNote.vue'
import AppButton from '@/shared/ui/AppButton.vue'
import FailureNotice from '@/shared/ui/FailureNotice.vue'
import PersonTag from '@/shared/ui/PersonTag.vue'
import { OUTCOME_WORDS } from '@/shared/ui/words'

import AnswerPanel from './AnswerPanel.vue'

// The question and the opened source come from the address bar (router.ts), so a result can be reloaded, sent to a
// colleague, or left with the back button. The person comes from the session.
const props = defineProps<{ question: string; source: string | null }>()

const router = useRouter()
const person = signedIn

const asking = useMutation({
  mutationFn: (request: { subject: string; question: string }) => ask(request.subject, request.question),
})

// Asking is an effect of the address changing: a new question, or the same address opened as someone else.
watch(
  () => [props.question, person.value?.subject] as const,
  ([question, subject]) => {
    if (question === '' || subject === undefined) asking.reset()
    else asking.mutate({ subject, question })
  },
  { immediate: true },
)

function submit(question: string): void {
  const subject = person.value?.subject
  if (subject === undefined) return
  // The same question again is a new request, but not a new address.
  if (question === props.question) asking.mutate({ subject, question })
  else void router.push({ name: 'ask', query: { q: question } })
}

const linkTo = (chunkId: string): RouteLocationRaw => ({ name: 'ask', query: { q: props.question, source: chunkId } })

async function closeSource(): Promise<void> {
  const opened = props.source
  await router.push({ name: 'ask', query: { q: props.question } })
  await nextTick()
  // Back to the link that opened it, so the keyboard carries on from where it was.
  if (opened !== null) document.getElementById(`cite-${opened}`)?.focus()
}

const failure = computed(() => (asking.error.value === null ? null : failureIn(asking.error.value)))
const status = computed(() => {
  if (asking.isPending.value) return `Asking as ${person.value?.subject ?? ''}.`
  const answer = asking.data.value
  if (answer === undefined) return ''
  const cited = answer.citations.length
  return `${OUTCOME_WORDS[answer.outcome].title}. ${cited} ${cited === 1 ? 'source' : 'sources'} cited.`
})
</script>

<template>
  <div v-if="person" class="page">
    <h1 tabindex="-1">Ask the policy library</h1>
    <div class="as">
      <p>You are asking as</p>
      <PersonTag :person="person" />
    </div>

    <QuestionForm :question="question" action="Ask" :busy="asking.isPending.value" @ask="submit" />
    <StandInNote />

    <p class="status" role="status">{{ status }}</p>

    <FailureNotice v-if="failure" :failure="failure" :who="person.subject">
      <RouterLink v-if="failure.kind === 'unauthorised'" :to="{ name: 'sign-in', query: { next: $route.fullPath } }">
        Sign in again
      </RouterLink>
      <AppButton v-else quiet @click="submit(question)">Ask again</AppButton>
    </FailureNotice>
    <AnswerPanel v-else-if="asking.data.value" :answer="asking.data.value" :opened="source" :link-to="linkTo" />

    <ExcerptPanel v-if="source !== null" :subject="person.subject" :chunk-id="source" @close="closeSource" />
  </div>
</template>

<style scoped>
h1 {
  margin: 0;
  font-size: 1.75rem;
  line-height: 1.2;
}

.as {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 1rem;
  align-items: center;
  margin: 0.75rem 0 1.25rem;
  padding: 0.6rem 0;
  border-top: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule);
}

.as p {
  margin: 0;
  color: var(--ink-soft);
}

.status {
  min-height: 1.5rem;
  margin: 1rem 0 0;
  color: var(--ink-soft);
}
</style>
