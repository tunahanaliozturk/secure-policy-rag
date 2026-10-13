<script setup lang="ts">
import { ref, watch } from 'vue'

import AppButton from '@/shared/ui/AppButton.vue'

import { EXAMPLES } from './examples'

// The box holds a draft; the question that was asked lives in the address bar and arrives here as a prop. Going back
// or forward in the browser changes the prop, and the draft follows it.
const props = defineProps<{ question: string; action: string; busy: boolean }>()
const emit = defineEmits<{ ask: [question: string] }>()

const draft = ref(props.question)
watch(
  () => props.question,
  (question) => {
    draft.value = question
  },
)

function submit(): void {
  const question = draft.value.trim()
  if (question !== '') emit('ask', question)
}

function tryExample(question: string): void {
  draft.value = question
  emit('ask', question)
}
</script>

<template>
  <form class="form" @submit.prevent="submit">
    <label for="question">Question</label>
    <div class="row">
      <input id="question" v-model="draft" type="text" required maxlength="2000" autocomplete="off" />
      <AppButton type="submit" :disabled="busy">{{ action }}</AppButton>
    </div>
  </form>
  <div class="examples">
    <p id="examples-title">Questions that come out differently depending on who asks:</p>
    <ul aria-labelledby="examples-title">
      <li v-for="example in EXAMPLES" :key="example">
        <AppButton quiet :disabled="busy" @click="tryExample(example)">{{ example }}</AppButton>
      </li>
    </ul>
  </div>
</template>

<style scoped>
label {
  display: block;
  font-weight: 650;
}

.row {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.3rem;
}

input {
  box-sizing: border-box;
  flex: 1;
  min-width: 0;
  padding: 0.5rem 0.65rem;
  border: 1px solid var(--ink-soft);
  border-radius: 2px;
  background: var(--paper);
  color: var(--ink);
  font: inherit;
}

.examples {
  margin-top: 1rem;
}

.examples p {
  margin: 0 0 0.4rem;
  color: var(--ink-soft);
}

ul {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

@media (max-width: 34rem) {
  .row {
    flex-direction: column;
  }
}
</style>
