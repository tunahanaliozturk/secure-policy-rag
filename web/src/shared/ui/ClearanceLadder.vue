<script setup lang="ts">
import type { Clearance } from '@/shared/api/login'

// Four rungs, filled up to the level. The same drawing sits next to a person's clearance and a document's
// classification, so the rule "high enough, and in the right department" can be read off the page. The word is the
// information; the rungs repeat it for the eye and are hidden from a screen reader.
defineProps<{ level: Clearance }>()
</script>

<template>
  <span class="ladder" :class="level">
    <span class="rungs" aria-hidden="true"><i /><i /><i /><i /></span>
    <span class="word">{{ level }}</span>
  </span>
</template>

<style scoped>
.ladder {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  white-space: nowrap;
}

.rungs {
  display: inline-flex;
  gap: 2px;
}

.rungs i {
  box-sizing: border-box;
  width: 0.5rem;
  height: 0.75rem;
  border: 1px solid var(--ink-soft);
}

.public i:nth-child(-n + 1),
.internal i:nth-child(-n + 2),
.confidential i:nth-child(-n + 3),
.restricted i:nth-child(-n + 4) {
  border-color: var(--ink);
  background: var(--ink);
}
</style>
