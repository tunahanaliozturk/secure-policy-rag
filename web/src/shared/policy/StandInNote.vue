<template>
  <p class="note">
    Unless this stack was started with a model API key, answers come from a scripted stand-in, not a language model: it
    quotes the first sentence of the best source the database returned for the person asking. What differs between
    people is the source, and the database chose it.
  </p>
</template>

<style scoped>
.note {
  max-width: 52rem;
  margin: 1rem 0 0;
  color: var(--ink-soft);
  font-size: 0.9375rem;
}
</style>
