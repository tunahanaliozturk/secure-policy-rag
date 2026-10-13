-- Applied by `spr migrate` as the administrator. Idempotent: it can run on every deploy.
-- The application connects as spr_app, which owns nothing, cannot bypass row-level security, and holds two grants:
-- SELECT on chunks (filtered by the policy below) and INSERT on some columns of audit_log and excerpt_log. See ADR 0002.

create extension if not exists vector;

do $$
begin
    if not exists (select from pg_roles where rolname = 'spr_app') then
        create role spr_app login nosuperuser nobypassrls nocreatedb nocreaterole noinherit noreplication;
    end if;
end
$$;

create table if not exists chunks (
    id             text        primary key,              -- 'CR-001#2': document id and section number
    document_id    text        not null,
    title          text        not null,
    heading        text        not null,
    text           text        not null,
    department     text        not null,
    classification text        not null check (classification in ('public', 'internal', 'confidential', 'restricted')),
    -- The number the policy compares with the reader's clearance. Derived, so it cannot disagree with the label.
    class_rank     smallint    generated always as (
                       case classification when 'public' then 0 when 'internal' then 1
                                           when 'confidential' then 2 else 3 end
                   ) stored,
    tsv            tsvector    generated always as (
                       setweight(to_tsvector('english', title || ' ' || heading), 'A')
                       || setweight(to_tsvector('english', text), 'B')
                   ) stored,
    -- Exact cosine search, no HNSW index: at a few hundred chunks a sequential scan takes well under a millisecond,
    -- and an approximate index under a row-level filter can return fewer rows than asked for (docs/operations.md).
    embedding      vector(384) not null
);

create index if not exists chunks_tsv on chunks using gin (tsv);

-- Who may read a chunk. The reader's clearance and departments come from two settings that the application sets,
-- transaction-local, from the verified token before it runs any query (store.py). Unset settings read as no
-- clearance and no departments, so a query that forgot to set them sees nothing at all.
--   public and internal: anyone whose clearance reaches the level, whatever their department
--   confidential and restricted: the owning department only, and only with enough clearance
alter table chunks enable row level security;
alter table chunks force row level security;
drop policy if exists chunks_visible on chunks;
create policy chunks_visible on chunks for select to spr_app using (
    class_rank <= coalesce(nullif(current_setting('spr.clearance', true), '')::smallint, -1)
    and (
        class_rank <= 1
        or department = any (string_to_array(nullif(current_setting('spr.departments', true), ''), ','))
    )
);

-- Append-only record of every question. Never the raw question: only the redacted text, ids and counts.
create table if not exists audit_log (
    id                  uuid        primary key default uuidv7(),
    at                  timestamptz not null default now(),
    subject             text        not null,
    departments         text[]      not null,
    clearance           text        not null,
    question_redacted   text        not null,
    outcome             text        not null check (outcome in ('answered', 'refused', 'blocked', 'model_refused', 'error')),
    retrieved_chunk_ids text[]      not null,
    cited_chunk_ids     text[]      not null,
    redactions_in       jsonb       not null,
    redactions_out      jsonb       not null,
    violations          text[]      not null,
    model               text        not null,
    latency_ms          integer     not null check (latency_ms >= 0),
    input_tokens        integer,
    output_tokens       integer
);

create index if not exists audit_log_subject_at on audit_log (subject, at);

-- Append-only record of every request to open one chunk (GET /excerpts/{id}) that reached the database. outcome is
-- 'not_found' when the policy above returned no row, whether the chunk is hidden from this reader or does not exist,
-- and 'error' when the read itself failed. A request refused before that (401 no valid token, 422 an id that is not
-- shaped like one, 429 the rate limit) writes no row.
create table if not exists excerpt_log (
    id          uuid        primary key default uuidv7(),
    at          timestamptz not null default now(),
    subject     text        not null,
    departments text[]      not null,
    clearance   text        not null,
    chunk_id    text        not null,
    outcome     text        not null check (outcome in ('found', 'not_found', 'error'))
);

-- Builds of 0.2.0 before its release recorded a boolean, found, and no failed reads. Carry such a table over.
do $$
begin
    if exists (select from information_schema.columns
               where table_schema = current_schema() and table_name = 'excerpt_log' and column_name = 'found') then
        alter table excerpt_log add column outcome text check (outcome in ('found', 'not_found', 'error'));
        update excerpt_log set outcome = case when excerpt_log.found then 'found' else 'not_found' end;
        alter table excerpt_log alter column outcome set not null;
        alter table excerpt_log drop column found;
    end if;
end
$$;

create index if not exists excerpt_log_chunk_at on excerpt_log (chunk_id, at);

-- Least privilege, stated in full. Revoke first so a rerun after a grant change leaves exactly what is listed here.
revoke all on chunks, audit_log, excerpt_log from public, spr_app;
grant usage on schema public to spr_app;
grant select on chunks to spr_app;
-- Column list: the database stamps id and at, so the application cannot backdate a record.
grant insert (subject, departments, clearance, question_redacted, outcome, retrieved_chunk_ids, cited_chunk_ids,
              redactions_in, redactions_out, violations, model, latency_ms, input_tokens, output_tokens)
    on audit_log to spr_app;
grant insert (subject, departments, clearance, chunk_id, outcome) on excerpt_log to spr_app;
