<script setup lang="ts">
import { computed } from 'vue'

import type { Person } from '@/shared/api/login'

import ClearanceLadder from './ClearanceLadder.vue'

const props = defineProps<{ person: Person }>()

const departments = computed(() =>
  props.person.departments.length === 0 ? 'no department' : props.person.departments.join(', '),
)
</script>

<template>
  <span class="person">
    <span class="name">{{ person.subject }}</span>
    <span class="departments">{{ departments }}</span>
    <ClearanceLadder :level="person.clearance" />
  </span>
</template>

<style scoped>
.person {
  display: inline-grid;
  gap: 0.1rem;
  justify-items: start;
  font-weight: 400;
  text-align: left;
}

.name {
  font-weight: 650;
  font-size: 1.0625rem;
  text-transform: capitalize;
}

.departments {
  color: var(--ink-soft);
}
</style>
