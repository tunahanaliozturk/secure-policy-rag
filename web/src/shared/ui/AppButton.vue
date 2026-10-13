<script setup lang="ts">
defineProps<{ quiet?: boolean; type?: 'button' | 'submit'; disabled?: boolean }>()
</script>

<template>
  <button class="button" :class="{ quiet }" :type="type ?? 'button'" :disabled="disabled"><slot /></button>
</template>

<style scoped>
.button {
  padding: 0.5rem 0.9rem;
  border: 1px solid var(--green);
  border-radius: 2px;
  background: var(--green);
  color: #fff;
  font: 600 1rem / 1.25 var(--font-ui);
  cursor: pointer;
}

.button:hover {
  border-color: var(--ink);
  background: var(--ink);
}

.button.quiet {
  border-color: var(--ink-soft);
  background: var(--paper);
  color: var(--ink);
  font-weight: 400;
  text-align: left;
}

.button.quiet:hover {
  border-color: var(--ink);
  background: var(--band);
}

/* Still readable at 4.5:1: a disabled button here means "wait", and the person should be able to read what for. */
.button:disabled {
  border-color: var(--ink-soft);
  background: var(--band);
  color: var(--ink-soft);
  cursor: progress;
}
</style>
