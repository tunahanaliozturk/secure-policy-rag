"""``spr``: migrate, ingest, serve, mint a demo token, run the demo login, write the OpenAPI documents, and run the
two evaluations."""

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anthropic
import asyncpg

from secure_policy_rag import corpus, embedding, evaluation, identity, store, telemetry
from secure_policy_rag.api import RateLimiter, Services, create_app
from secure_policy_rag.demo_login import build_demo_login
from secure_policy_rag.model import AnswerModel, ClaudeModel, ScriptedModel
from secure_policy_rag.pipeline import Assistant
from secure_policy_rag.settings import Settings


def _out(text: str) -> None:
    sys.stdout.write(text + "\n")


def _admin_dsn(settings: Settings) -> str:
    if not settings.admin_database_url:
        raise SystemExit("SPR_ADMIN_DATABASE_URL is required for this command")
    return settings.admin_database_url


def build_model(settings: Settings) -> AnswerModel:
    if settings.model_provider == "scripted":
        return ScriptedModel("faithful")
    return ClaudeModel(anthropic.AsyncAnthropic(), settings.model, settings.effort)


async def _migrate(settings: Settings) -> None:
    if settings.app_db_password is None:
        raise SystemExit("SPR_APP_DB_PASSWORD is required: it becomes the spr_app role's password")
    conn = await asyncpg.connect(_admin_dsn(settings))
    try:
        await store.migrate(conn, settings.app_db_password.get_secret_value())
    finally:
        await conn.close()
    _out("schema, policies and grants are in place")


async def _ingest(settings: Settings, directory: Path) -> None:
    documents = corpus.load(directory)
    chunks = [c for d in documents for c in d.chunks()]
    embedder = embedding.create(settings.embedder, settings.model_cache_dir)
    vectors = await asyncio.to_thread(embedder.embed_passages, [c.for_embedding() for c in chunks])
    conn = await asyncpg.connect(_admin_dsn(settings))
    try:
        await store.replace_corpus(conn, chunks, vectors)
    finally:
        await conn.close()
    _out(f"{len(documents)} documents, {len(chunks)} chunks, embedded with {embedder.name}")


def _serve(settings: Settings, host: str, port: int) -> None:
    import uvicorn  # noqa: PLC0415

    secrets = settings.token_secrets()  # fails here, at start-up, not on the first request

    @asynccontextmanager
    async def services() -> AsyncIterator[Services]:
        pool = await store.create_pool(settings.database_url)
        try:
            embedder = embedding.create(settings.embedder, settings.model_cache_dir)
            assistant = Assistant(
                pool,
                embedder,
                build_model(settings),
                settings.link_hosts(),
                k=settings.top_k,
                retrievers=settings.retriever_set(),
            )
            yield Services(assistant, pool)
        finally:
            await pool.close()

    app = create_app(services, secrets, RateLimiter(settings.rate_limit_per_minute))
    uvicorn.run(app, host=host, port=port, log_config=None, server_header=False)


def _demo_login(settings: Settings, host: str, port: int, ttl_minutes: int) -> None:
    import uvicorn  # noqa: PLC0415

    app = build_demo_login(settings.token_secrets()[0], timedelta(minutes=ttl_minutes))
    uvicorn.run(app, host=host, port=port, log_config=None, server_header=False)


def _never_started() -> AbstractAsyncContextManager[Services]:
    raise RuntimeError("this app only describes itself; it is never started")


def openapi_documents() -> dict[str, dict[str, Any]]:
    """The two contracts the browser client is generated from, by file name. Building them opens no database and
    needs no secret, because neither app is started."""
    return {
        "api.openapi.json": create_app(_never_started, [], RateLimiter(per_minute=1)).openapi(),
        "login.openapi.json": build_demo_login(b"", timedelta(0)).openapi(),
    }


def render_openapi(document: dict[str, Any]) -> str:
    """Sorted keys and a fixed indent, so the committed file changes only when the contract does."""
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _openapi(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, document in openapi_documents().items():
        (directory / name).write_text(render_openapi(document), encoding="utf-8", newline="\n")
        _out(f"wrote {directory / name}")


def _token(settings: Settings, subject: str, ttl_minutes: int) -> None:
    if subject not in identity.DEMO_IDENTITIES:
        raise SystemExit(f"unknown demo identity {subject!r}; one of {', '.join(identity.DEMO_IDENTITIES)}")
    who = identity.DEMO_IDENTITIES[subject]
    _out(identity.issue(who, settings.token_secrets()[0], datetime.now(UTC), timedelta(minutes=ttl_minutes)))


async def _eval_retrieval(settings: Settings, args: argparse.Namespace) -> int:
    documents = corpus.load(args.corpus)
    cases = evaluation.load_cases(args.cases, evaluation.RetrievalCase)
    embedder = embedding.create(settings.embedder, settings.model_cache_dir)
    pool = await store.create_pool(settings.database_url)
    try:
        report = await evaluation.evaluate_retrieval(pool, embedder, documents, cases, k=args.k)
    finally:
        await pool.close()
    payload = {"embedder": embedder.name, **report.__dict__}
    if args.output:
        evaluation.write_report(args.output, payload)
    for name, scores in report.scores.items():
        _out(f"{name:8} recall@{report.k} {scores['recall']:.4f}  nDCG@{report.k} {scores['ndcg']:.4f}")
    _out(f"{report.cases} cases, {len(report.leaks)} leaks, {len(report.misses)} hybrid misses")
    for miss in report.misses:
        _out(f"  miss {miss}")
    if args.write_baseline:
        baseline = {"k": report.k, "embedder": embedder.name, "tolerance": 0.02, "hybrid": report.scores["hybrid"]}
        evaluation.write_report(args.baseline, baseline)
        _out(f"baseline written to {args.baseline}")
        return 1 if report.leaks else 0
    problems = evaluation.compare(report, json.loads(args.baseline.read_text(encoding="utf-8")))
    for problem in problems:
        _out(f"FAIL {problem}")
    return 1 if problems else 0


async def _eval_answers(settings: Settings, args: argparse.Namespace) -> int:
    documents = corpus.load(args.corpus)
    cases = evaluation.load_cases(args.cases, evaluation.AnswerCase)
    embedder = embedding.create(settings.embedder, settings.model_cache_dir)
    real = build_model(settings) if args.model == "anthropic" else None
    judge = (anthropic.AsyncAnthropic(), settings.model) if args.judge and real is not None else None
    pool = await store.create_pool(settings.database_url)
    try:
        results = await evaluation.evaluate_answers(
            pool, embedder, documents, cases, real_model=real, allowed_hosts=settings.link_hosts(), judge_with=judge
        )
    finally:
        await pool.close()
    failed = [r for r in results if r.failures]
    for r in results:
        status = "FAIL" if r.failures else "ok  "
        _out(f"{status} {r.case:5} {r.outcome:13} {'; '.join(r.failures)}{f'  judge: {r.judge}' if r.judge else ''}")
    _out(f"{len(results) - len(failed)}/{len(results)} cases pass ({'real model' if real else 'scripted model'})")
    if args.output:
        evaluation.write_report(args.output, {"results": [r.__dict__ for r in results]})
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spr", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="create or update the schema, policies and grants (administrator)")
    ingest = commands.add_parser("ingest", help="load the corpus, replacing what is there (administrator)")
    ingest.add_argument("corpus", type=Path, nargs="?", default=Path("corpus"))
    serve = commands.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1", help="127.0.0.1 unless you mean to expose it")
    serve.add_argument("--port", type=int, default=8000)
    token = commands.add_parser("token", help="mint a bearer token for a demo identity")
    token.add_argument("subject", help=", ".join(identity.DEMO_IDENTITIES))
    token.add_argument("--ttl-minutes", type=int, default=60)
    login = commands.add_parser("demo-login", help="run the demo's login: tokens for the six demo identities only")
    login.add_argument("--host", default="127.0.0.1", help="127.0.0.1 unless you mean to expose it")
    login.add_argument("--port", type=int, default=8000)
    login.add_argument("--ttl-minutes", type=int, default=10)
    openapi = commands.add_parser("openapi", help="write the OpenAPI documents the browser client is generated from")
    openapi.add_argument("--output", type=Path, default=Path("web/src/shared/api"))
    retrieval = commands.add_parser("eval-retrieval", help="score retrieval and fail on a regression or any leak")
    retrieval.add_argument("--cases", type=Path, default=Path("eval/retrieval.jsonl"))
    retrieval.add_argument("--corpus", type=Path, default=Path("corpus"))
    retrieval.add_argument("--baseline", type=Path, default=Path("eval/baseline.json"))
    retrieval.add_argument("--write-baseline", action="store_true")
    retrieval.add_argument("--output", type=Path)
    retrieval.add_argument("-k", type=int, default=5)
    answers = commands.add_parser("eval-answers", help="grade whole answers with deterministic graders")
    answers.add_argument("--cases", type=Path, default=Path("eval/answers.jsonl"))
    answers.add_argument("--corpus", type=Path, default=Path("corpus"))
    answers.add_argument("--model", choices=["scripted", "anthropic"], default="scripted")
    answers.add_argument("--judge", action="store_true", help="also grade faithfulness with a model (needs a key)")
    answers.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "openapi":  # before any configuration is read: the documents depend on the code alone
        _openapi(args.output)
        return 0

    settings = Settings()
    telemetry.configure(settings.log_level, settings.trace_exporter if args.command == "serve" else "none")
    match args.command:
        case "migrate":
            asyncio.run(_migrate(settings))
        case "ingest":
            asyncio.run(_ingest(settings, args.corpus))
        case "serve":
            _serve(settings, args.host, args.port)
        case "token":
            _token(settings, args.subject, args.ttl_minutes)
        case "demo-login":
            _demo_login(settings, args.host, args.port, args.ttl_minutes)
        case "eval-retrieval":
            return asyncio.run(_eval_retrieval(settings, args))
        case "eval-answers":
            return asyncio.run(_eval_answers(settings, args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
