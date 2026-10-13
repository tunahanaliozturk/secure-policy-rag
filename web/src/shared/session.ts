// Who is signed in. One value the whole page reads and the router guards on, so it is a module, not a store: there is
// nothing to it but a name with a clearance. It lives in memory, like the token, and a reload signs the person out.

import { computed, shallowRef } from 'vue'

import type { Person } from '@/shared/api/login'

const current = shallowRef<Person | null>(null)

export const signedIn = computed(() => current.value)

export function signIn(person: Person): void {
  current.value = person
}

export function signOut(): void {
  current.value = null
}
