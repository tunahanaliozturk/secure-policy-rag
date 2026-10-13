<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'

import { failureIn } from '@/shared/api/http'
import { excerpt } from '@/shared/api/policy'
import { describeFailure } from '@/shared/ui/words'

// One cell of the comparison: can this person open this source? The cell does not work that out. It asks the excerpt
// endpoint as that person and shows what the database answered, which is the whole point of the table.
const props = defineProps<{ subject: string; chunkId: string; cited: boolean; to: RouteLocationRaw }>()

const reading = useQuery({
  queryKey: computed(() => ['excerpt', props.subject, props.chunkId] as const),
  queryFn: ({ signal }) => excerpt(props.subject, props.chunkId, signal),
})
const failure = computed(() => (reading.error.value === null ? null : failureIn(reading.error.value)))
const label = computed(() => (props.cited ? 'Cited' : 'Can read'))
</script>

<template>
  <span v-if="reading.isPending.value" class="cell checking"><span class="mark" aria-hidden="true" />Checking</span>
  <RouterLink
    v-else-if="reading.data.value"
    :id="`open-${subject}-${chunkId}`"
    class="cell"
    :class="cited ? 'cited' : 'readable'"
    :to="to"
    :aria-label="`${label}: open ${chunkId} as ${subject}`"
  >
    <span class="mark" aria-hidden="true" />{{ label }}
  </RouterLink>
  <span v-else-if="failure?.kind === 'not_found'" class="cell none">
    <span class="mark" aria-hidden="true" />No access
  </span>
  <span v-else-if="failure" class="cell unknown">Not checked: {{ describeFailure(failure, subject).title }}</span>
</template>

<style scoped>
.cell {
  display: inline-flex;
  gap: 0.45rem;
  align-items: center;
  white-space: nowrap;
}

.mark {
  box-sizing: border-box;
  flex: none;
  width: 0.875rem;
  height: 0.875rem;
  border: 2px solid var(--green);
}

.cited {
  color: var(--green);
  font-weight: 650;
}

.cited .mark {
  background: var(--green);
}

.readable {
  color: var(--ink);
}

/* A bar, not a box: nothing is there for this person. */
.none {
  color: var(--ink-soft);
}

.none .mark {
  height: 0;
  border-width: 2px 0 0;
  border-color: var(--ink-soft);
}

.checking {
  color: var(--ink-soft);
}

.checking .mark {
  border: 2px dotted var(--ink-soft);
}

.unknown {
  color: var(--red);
  white-space: normal;
}
</style>
