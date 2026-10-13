<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, nextTick, onMounted, useTemplateRef, watch } from 'vue'

import { failureIn } from '@/shared/api/http'
import { excerpt } from '@/shared/api/policy'
import AppButton from '@/shared/ui/AppButton.vue'
import ClearanceLadder from '@/shared/ui/ClearanceLadder.vue'
import FailureNotice from '@/shared/ui/FailureNotice.vue'

// One source, opened as one person. The request carries that person's token, and the database decides whether there
// is anything to show: this component never knows more about a source than the server said to this reader.
const props = defineProps<{ subject: string; chunkId: string }>()
const emit = defineEmits<{ close: [] }>()

const reading = useQuery({
  queryKey: computed(() => ['excerpt', props.subject, props.chunkId] as const),
  queryFn: ({ signal }) => excerpt(props.subject, props.chunkId, signal),
})
const failure = computed(() => (reading.error.value === null ? null : failureIn(reading.error.value)))

// Opening a source moves focus to it, so a keyboard or screen reader user lands on what they asked for.
const heading = useTemplateRef<HTMLElement>('heading')
const focus = (): void => void nextTick(() => heading.value?.focus())
onMounted(focus)
watch(() => [props.subject, props.chunkId], focus)
</script>

<template>
  <section class="excerpt" aria-labelledby="excerpt-title">
    <div class="top">
      <h2 id="excerpt-title" ref="heading" tabindex="-1">
        <span class="ref">{{ chunkId }}</span> opened as <span class="name">{{ subject }}</span>
      </h2>
      <AppButton quiet @click="emit('close')">Close this source</AppButton>
    </div>

    <p v-if="reading.isPending.value" role="status">Opening {{ chunkId }} as {{ subject }}.</p>

    <template v-else-if="reading.data.value">
      <p class="title">{{ reading.data.value.title }}</p>
      <p class="section">{{ reading.data.value.section }}</p>
      <dl>
        <div>
          <dt>Classification</dt>
          <dd><ClearanceLadder :level="reading.data.value.classification" /></dd>
        </div>
        <div>
          <dt>Owning department</dt>
          <dd>{{ reading.data.value.department }}</dd>
        </div>
      </dl>
      <p class="text">{{ reading.data.value.text }}</p>
    </template>

    <div v-else-if="failure?.kind === 'not_found'" class="none" role="alert">
      <p class="title">{{ subject }} cannot open {{ chunkId }}</p>
      <p>
        The server gives one answer for a source that does not exist and for a source this person may not read, so this
        page cannot tell which of the two this is.
      </p>
    </div>

    <FailureNotice v-else-if="failure" :failure="failure" :who="subject">
      <AppButton quiet @click="reading.refetch()">Try again</AppButton>
    </FailureNotice>
  </section>
</template>

<style scoped>
.excerpt {
  margin-top: 2rem;
  padding: 1rem 1.25rem 1.25rem;
  border-top: 4px solid var(--ink);
  background: var(--band);
}

.top {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
  justify-content: space-between;
}

h2 {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 650;
}

.ref {
  font-family: var(--font-ref);
}

.name {
  text-transform: capitalize;
}

.title {
  margin: 1rem 0 0;
  font-size: 1.125rem;
  font-weight: 650;
}

.section {
  margin: 0;
  color: var(--ink-soft);
}

dl {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 2.5rem;
  margin: 0.75rem 0;
}

dt {
  color: var(--ink-soft);
  font-size: 0.875rem;
}

dd {
  margin: 0;
}

.text {
  max-width: 44rem;
  margin: 0;
  padding-left: 1rem;
  border-left: 2px solid var(--ink-soft);
  line-height: 1.6;
}

.none .title {
  text-transform: none;
}

.none .title::first-letter {
  text-transform: uppercase;
}

.none p + p {
  max-width: 44rem;
  margin: 0.25rem 0 0;
}
</style>
