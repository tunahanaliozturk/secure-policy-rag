<script setup lang="ts">
import { useMutation, useQuery } from '@tanstack/vue-query'
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter, type RouteLocationRaw } from 'vue-router'

import { failureIn } from '@/shared/api/http'
import { people, type Person } from '@/shared/api/login'
import { askSettled, type Asked } from '@/shared/api/policy'
import ExcerptPanel from '@/shared/policy/ExcerptPanel.vue'
import QuestionForm from '@/shared/policy/QuestionForm.vue'
import StandInNote from '@/shared/policy/StandInNote.vue'
import AppButton from '@/shared/ui/AppButton.vue'
import FailureNotice from '@/shared/ui/FailureNotice.vue'
import OutcomeState from '@/shared/ui/OutcomeState.vue'
import PersonTag from '@/shared/ui/PersonTag.vue'
import { describeFailure, OUTCOME_WORDS } from '@/shared/ui/words'

import AccessCell from './AccessCell.vue'
import SourceHeading from './SourceHeading.vue'

// One question, asked as all six people at once, each with their own token. The table then shows two things the
// server said: what each person was told, and, for every source anyone cited, whether each person may open it.
const props = defineProps<{
  question: string
  open: { source: string; reader: string } | null
  /** True when this address was how the page was opened, not somewhere the person went inside it (router.ts). */
  byLink: boolean
}>()

type Row = { person: Person } & Asked

const router = useRouter()
const roster = useQuery({ queryKey: ['people'], queryFn: ({ signal }) => people(signal) })

const asking = useMutation({
  mutationFn: (request: { question: string; staff: Person[] }): Promise<Row[]> =>
    Promise.all(
      request.staff.map(async (person) => ({ person, ...(await askSettled(person.subject, request.question)) })),
    ),
})

// A question that arrives in the address this page was opened at is shown in the box and not sent. One request here
// is six questions, six model calls with a real model behind it, and six audit rows: a link someone was sent must
// not be able to spend that by being opened. It is sent when the person presses the button.
const unsent = ref(props.byLink && props.question !== '' ? props.question : null)
const holding = computed(() => unsent.value !== null && unsent.value === props.question)

watch(
  () => [props.question, roster.data.value, holding.value] as const,
  ([question, staff, held]) => {
    if (question === '' || staff === undefined || held) asking.reset()
    else asking.mutate({ question, staff })
  },
  { immediate: true },
)

function submit(question: string): void {
  const wasHolding = holding.value
  unsent.value = null
  if (question !== props.question) {
    void router.push({ name: 'compare', query: { q: question } })
    return
  }
  // The same question again is a new request, but not a new address. One that was being held is sent by the watch
  // above the moment it is released, and one pressed before the six people have loaded is sent when they arrive.
  const staff = roster.data.value
  if (!wasHolding && staff !== undefined) asking.mutate({ question, staff })
}

// A source is opened as one of the six. A reader the login does not list is not a person to open anything as, so it
// is dropped from the address before anything is asked on its behalf.
const reading = computed(() => {
  const opened = props.open
  if (opened === null) return null
  return roster.data.value?.some((person) => person.subject === opened.reader) === true ? opened : null
})

watch(
  () => [props.open, roster.data.value] as const,
  ([opened, staff]) => {
    if (opened === null || staff === undefined || staff.some((person) => person.subject === opened.reader)) return
    void router.replace({ name: 'compare', query: props.question === '' ? {} : { q: props.question } })
  },
  { immediate: true },
)

const rows = computed(() => asking.data.value ?? [])

/** Every source anyone cited, once, in the order the people are listed, with the first person who cited it. */
const sources = computed(() => {
  const seen = new Map<string, { chunkId: string; title: string; section: string; citedBy: string }>()
  for (const row of rows.value) {
    for (const citation of row.answer?.citations ?? []) {
      if (!seen.has(citation.chunk_id)) {
        seen.set(citation.chunk_id, {
          chunkId: citation.chunk_id,
          title: citation.title,
          section: citation.section,
          citedBy: row.person.subject,
        })
      }
    }
  }
  return [...seen.values()]
})

const cites = (row: Row, chunkId: string): boolean =>
  row.answer?.citations.some((citation) => citation.chunk_id === chunkId) ?? false

const openAs = (reader: string, source: string): RouteLocationRaw => ({
  name: 'compare',
  query: { q: props.question, source, reader },
})

async function closeSource(): Promise<void> {
  const opened = props.open
  await router.push({ name: 'compare', query: { q: props.question } })
  await nextTick()
  if (opened !== null) document.getElementById(`open-${opened.reader}-${opened.source}`)?.focus()
}

const rosterFailure = computed(() => (roster.error.value === null ? null : failureIn(roster.error.value)))
const askingFailure = computed(() => (asking.error.value === null ? null : failureIn(asking.error.value)))

const status = computed(() => {
  if (roster.isPending.value) return 'Loading the six people.'
  if (holding.value) {
    return 'This question came with the link and has not been sent. Press Ask as all six to send it.'
  }
  if (asking.isPending.value) return `Asking as ${roster.data.value?.length ?? 0} people.`
  if (rows.value.length === 0) return ''
  const counts = new Map<string, number>()
  for (const row of rows.value) {
    const title = row.answer === undefined ? 'request failed' : OUTCOME_WORDS[row.answer.outcome].title.toLowerCase()
    counts.set(title, (counts.get(title) ?? 0) + 1)
  }
  const outcomes = [...counts].map(([title, count]) => `${count} ${title}`).join(', ')
  const cited = sources.value.length
  return `Asked as ${rows.value.length} people: ${outcomes}. ${cited} ${cited === 1 ? 'source' : 'different sources'} cited.`
})
</script>

<template>
  <div class="page">
    <h1 tabindex="-1">Ask as everyone</h1>
    <p class="lede">
      The same question goes to the policy library six times, once as each person. Nothing on this page decides who sees
      what: every difference below is the database answering a different reader.
    </p>

    <QuestionForm :question="question" action="Ask as all six" :busy="asking.isPending.value" @ask="submit" />
    <StandInNote />

    <p class="status" role="status">{{ status }}</p>

    <FailureNotice v-if="rosterFailure" :failure="rosterFailure" who="This page">
      <AppButton quiet @click="roster.refetch()">Try again</AppButton>
    </FailureNotice>
    <FailureNotice v-if="askingFailure" :failure="askingFailure" who="This page" />

    <template v-if="rows.length > 0">
      <h2 id="ledger-title">One question, six readers</h2>
      <!-- Wider than a phone: the region scrolls sideways, so it takes focus and has a name (WCAG 2.1.1). -->
      <div class="ledger" role="region" aria-labelledby="ledger-title" tabindex="0">
        <table aria-labelledby="ledger-title">
          <thead>
            <tr>
              <th scope="col" class="who">Person</th>
              <th v-for="source in sources" :key="source.chunkId" scope="col" class="source">
                <SourceHeading v-bind="source" />
              </th>
              <th scope="col" class="told">What they were told</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.person.subject">
              <th scope="row" class="who"><PersonTag :person="row.person" /></th>
              <td v-for="source in sources" :key="source.chunkId" class="source">
                <AccessCell
                  :subject="row.person.subject"
                  :chunk-id="source.chunkId"
                  :cited="cites(row, source.chunkId)"
                  :to="openAs(row.person.subject, source.chunkId)"
                />
              </td>
              <td class="told">
                <template v-if="row.answer">
                  <OutcomeState :outcome="row.answer.outcome" brief />
                  <p class="said">{{ row.answer.answer }}</p>
                </template>
                <template v-else>
                  <p class="failed">{{ describeFailure(row.failure, row.person.subject).title }}</p>
                  <p class="said">{{ describeFailure(row.failure, row.person.subject).detail }}</p>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <dl class="legend">
        <div>
          <dt>Cited</dt>
          <dd>This person's answer quotes the source.</dd>
        </div>
        <div>
          <dt>Can read</dt>
          <dd>The database returns the source to this person, but their answer came from another one.</dd>
        </div>
        <div>
          <dt>No access</dt>
          <dd>
            The database returned nothing to this person, which is also what it returns for a source that does not
            exist.
          </dd>
        </div>
      </dl>
      <p class="how">
        Each mark is one request to the excerpt endpoint, sent with that person's token. Select a mark that says Cited
        or Can read to open the source as that person.
      </p>
    </template>

    <ExcerptPanel v-if="reading !== null" :subject="reading.reader" :chunk-id="reading.source" @close="closeSource" />
  </div>
</template>

<style scoped>
h1 {
  margin: 0;
  font-size: 1.75rem;
  line-height: 1.2;
}

.lede {
  max-width: 52rem;
  margin: 0.75rem 0 1.25rem;
  font-size: 1.125rem;
}

.status {
  min-height: 1.5rem;
  margin: 1rem 0 0;
  color: var(--ink-soft);
}

h2 {
  margin: 1.25rem 0 0;
  font-size: 1.125rem;
}

.ledger {
  margin-top: 0.5rem;
  overflow-x: auto;
}

/* Separate borders, not collapsed: a collapsed border does not travel with a sticky cell. */
table {
  width: 100%;
  border-top: 4px solid var(--ink);
  border-bottom: 2px solid var(--ink);
  border-spacing: 0;
}

th,
td {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--rule);
  text-align: left;
  vertical-align: top;
}

thead th {
  border-bottom: 2px solid var(--ink);
  vertical-align: bottom;
}

tbody tr:last-child > * {
  border-bottom: 0;
}

/* The person stays in view while the table is scrolled sideways on a narrow screen. */
.who {
  position: sticky;
  left: 0;
  min-width: 8.5rem;
  padding-left: 0;
  background: var(--paper);
}

/* The source columns are the comparison: ruled off and tinted, next to the people, so the eye reads down them. */
.source {
  min-width: 8rem;
  border-left: 1px solid var(--rule);
  background: var(--band);
}

.told {
  min-width: 17rem;
  border-left: 1px solid var(--rule);
}

.said {
  margin: 0.25rem 0 0;
  color: var(--ink-soft);
}

.failed {
  margin: 0;
  color: var(--red);
  font-weight: 650;
}

.legend {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
  gap: 0.5rem 2rem;
  margin: 1rem 0 0;
}

.legend dt {
  font-weight: 650;
}

.legend dd {
  margin: 0;
  color: var(--ink-soft);
}

.how {
  max-width: 52rem;
  margin: 0.75rem 0 0;
  color: var(--ink-soft);
}
</style>
