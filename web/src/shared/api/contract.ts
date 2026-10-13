// Ties each hand-written Zod schema to the type generated from the server's OpenAPI document (api.schema.d.ts,
// login.schema.d.ts). The schema checks a response at run time; these two types check the schema at compile time.
// Rename, add or drop a field on the server, regenerate, and `npm run type-check` fails at the schema that fell behind.

/** True when `Parsed` and `Promised` are the same type in both directions, otherwise false. */
export type Exact<Parsed, Promised> = [Parsed] extends [Promised] ? ([Promised] extends [Parsed] ? true : false) : false

/** Compiles only for `true`. `type _X = Holds<Exact<A, B>>` is a type error the moment A and B differ. */
export type Holds<T extends true> = T
