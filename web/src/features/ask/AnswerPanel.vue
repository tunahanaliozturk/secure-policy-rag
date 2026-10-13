<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'

import type { Answer } from '@/shared/api/policy'
import OutcomeState from '@/shared/ui/OutcomeState.vue'
import { describeRedactions } from '@/shared/ui/words'

// What came back for one question: the outcome in words, the answer as plain text, what was taken out of the question,
// and the sources as links. The answer is never rendered as HTML or linkified: it is model output (docs/threat-model.md).
const props = defineProps<{
  answer: Answer
  opened: string | null
  linkTo: (chunkId: string) => RouteLocationRaw
}>()

const redactions = computed(() => describeRedactions(props.answer.question_redactions))
</script>

<template>
  <section class="answer" aria-labelledby="answer-title">
    <h2 id="answer-title">Result</h2>
    <OutcomeState :outcome="answer.outcome" />
    <p v-if="answer.answer !== ''" class="text">{{ answer.answer }}</p>

    <p v-if="redactions !== null" class="redacted">
      <strong>Removed from the question</strong> before it was searched or sent to the model: {{ redactions }}.
    </p>

    <template v-if="answer.citations.length > 0">
      <h3 id="sources-title">Sources cited</h3>
      <ul class="sources" aria-labelledby="sources-title">
        <li v-for="citation in answer.citations" :key="citation.chunk_id">
          <RouterLink
            :id="`cite-${citation.chunk_id}`"
            :to="linkTo(citation.chunk_id)"
            :aria-current="opened === citation.chunk_id ? 'true' : undefined"
          >
            <span class="ref">{{ citation.chunk_id }}</span>
            <span>{{ citation.title }}, {{ citation.section }}</span>
          </RouterLink>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.answer {
  margin-top: 1.5rem;
  padding-top: 1rem;
  border-top: 2px solid var(--ink);
}

h2 {
  margin: 0 0 0.5rem;
  font-size: 1.125rem;
}

h3 {
  margin: 1.25rem 0 0.25rem;
  font-size: 1rem;
}

.text {
  max-width: 44rem;
  margin: 0.75rem 0 0;
  font-size: 1.125rem;
  line-height: 1.55;
}

.redacted {
  max-width: 44rem;
  margin: 1rem 0 0;
  padding: 0.6rem 0.9rem;
  border-left: 4px solid var(--ink);
  background: var(--band);
}

.sources {
  margin: 0;
  padding: 0;
  list-style: none;
}

.sources a {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 0.25rem 0.75rem;
  padding: 0.35rem 0;
  color: var(--green);
}

.sources a[aria-current='true'] {
  color: var(--ink);
  font-weight: 650;
  text-decoration: none;
}

.ref {
  font-family: var(--font-ref);
}
</style>
