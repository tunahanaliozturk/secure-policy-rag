<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'

import { excerpt } from '@/shared/api/policy'
import ClearanceLadder from '@/shared/ui/ClearanceLadder.vue'

// A column heading for one cited source. Its classification and owning department are read as the person who cited
// it, the one reader known to be allowed. The request is the same one that person's cell makes, so it is sent once.
const props = defineProps<{ chunkId: string; title: string; section: string; citedBy: string }>()

const reading = useQuery({
  queryKey: computed(() => ['excerpt', props.citedBy, props.chunkId] as const),
  queryFn: ({ signal }) => excerpt(props.citedBy, props.chunkId, signal),
})
</script>

<template>
  <span class="source">
    <span class="ref">{{ chunkId }}</span>
    <span class="title">{{ title }}</span>
    <span class="section">{{ section }}</span>
    <span class="labels">
      <template v-if="reading.data.value">
        <ClearanceLadder :level="reading.data.value.classification" />
        <span>{{ reading.data.value.department }}</span>
      </template>
    </span>
  </span>
</template>

<style scoped>
.source {
  display: grid;
  gap: 0.1rem;
  font-weight: 400;
}

.ref {
  font-family: var(--font-ref);
  font-weight: 650;
}

.title {
  font-weight: 650;
}

.section {
  color: var(--ink-soft);
}

.labels {
  display: grid;
  min-height: 3rem;
  margin-top: 0.25rem;
}
</style>
