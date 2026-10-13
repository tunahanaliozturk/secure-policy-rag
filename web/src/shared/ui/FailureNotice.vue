<script setup lang="ts">
import { computed } from 'vue'

import type { Failure } from '@/shared/api/http'

import { describeFailure } from './words'

// A request that failed, said out loud: the alert role makes a screen reader read it when it appears. The slot is
// for the one thing the person can do next, when there is one.
const props = defineProps<{ failure: Failure; who: string }>()

const words = computed(() => describeFailure(props.failure, props.who))
</script>

<template>
  <div class="failure" role="alert">
    <p class="title">{{ words.title }}</p>
    <p class="detail">{{ words.detail }}</p>
    <slot />
  </div>
</template>

<style scoped>
.failure {
  padding: 0.75rem 1rem;
  border-left: 4px solid var(--red);
  background: var(--red-wash);
}

.title {
  margin: 0;
  color: var(--red);
  font-weight: 650;
}

.detail {
  margin: 0.15rem 0 0;
}
</style>
