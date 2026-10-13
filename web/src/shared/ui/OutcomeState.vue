<script setup lang="ts">
import { computed } from 'vue'

import type { Outcome } from '@/shared/api/policy'

import { OUTCOME_WORDS } from './words'

// Each outcome has its own words and its own mark, so none of them depends on colour to be told from the others.
const props = defineProps<{ outcome: Outcome; brief?: boolean }>()

const words = computed(() => OUTCOME_WORDS[props.outcome])
</script>

<template>
  <div class="outcome" :class="outcome">
    <svg class="mark" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      <path v-if="outcome === 'answered'" d="M1 1h14v14H1z M4 8.2l2.6 2.6L12 5.4" />
      <path v-else-if="outcome === 'refused'" d="M8 1.5a6.5 6.5 0 1 0 0 13a6.5 6.5 0 0 0 0-13z M4.5 8h7" />
      <path
        v-else-if="outcome === 'blocked'"
        d="M5.2 1.5h5.6l3.7 3.7v5.6l-3.7 3.7H5.2l-3.7-3.7V5.2z M5 5l6 6 M11 5l-6 6"
      />
      <path v-else-if="outcome === 'model_refused'" d="M1.5 1.5h13v13h-13z M4.5 8h7" />
      <path v-else d="M8 1.5l6.8 12.5H1.2z M8 6v4 M8 11.6v.4" />
    </svg>
    <p class="title">{{ words.title }}</p>
    <p v-if="!brief" class="detail">{{ words.detail }}</p>
  </div>
</template>

<style scoped>
.outcome {
  display: grid;
  grid-template-columns: auto 1fr;
  column-gap: 0.5rem;
  align-items: center;
}

.mark {
  fill: none;
  stroke: var(--ink);
  stroke-width: 1.6;
  stroke-linecap: square;
}

.answered .mark {
  stroke: var(--green);
}

.blocked .mark,
.error .mark {
  stroke: var(--red);
}

.title {
  margin: 0;
  font-weight: 650;
}

.answered .title {
  color: var(--green);
}

.blocked .title,
.error .title {
  color: var(--red);
}

.detail {
  grid-column: 2;
  margin: 0;
  color: var(--ink-soft);
}
</style>
