"""Latency of everything around the model: redaction, query embedding, retrieval under row-level security, prompt
building, verification, output redaction and the audit insert. The model is the scripted one, which answers in
microseconds, so the numbers are the overhead this design adds on top of whatever the real model call costs.

    uv run python benchmarks/pipeline_latency.py --rounds 5

Needs the compose database with the corpus ingested by the real embedder, and SPR_DATABASE_URL pointing at it.
Sequential, one request at a time: this is a per-request cost, not a throughput figure.
"""

import argparse
import asyncio
import platform
import statistics
import time
from pathlib import Path

from secure_policy_rag import embedding, evaluation, store, telemetry
from secure_policy_rag.identity import DEMO_IDENTITIES
from secure_policy_rag.model import ScriptedModel
from secure_policy_rag.pipeline import Assistant
from secure_policy_rag.settings import Settings


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))]


async def main(rounds: int) -> None:
    settings = Settings()
    telemetry.configure("WARNING", "none")
    cases = evaluation.load_cases(Path("eval/retrieval.jsonl"), evaluation.RetrievalCase)
    embedder = embedding.create("fastembed", settings.model_cache_dir)
    pool = await store.create_pool(settings.database_url)
    assistant = Assistant(pool, embedder, ScriptedModel(), settings.link_hosts())
    try:
        for case in cases[:5]:  # warm-up: model load, connection pool, Postgres caches
            await assistant.ask(DEMO_IDENTITIES[case.user], case.question)
        samples: list[float] = []
        for _ in range(rounds):
            for case in cases:
                started = time.perf_counter()
                await assistant.ask(DEMO_IDENTITIES[case.user], case.question)
                samples.append((time.perf_counter() - started) * 1000)
    finally:
        await pool.close()
    machine = platform.processor() or platform.machine()
    print(f"{len(samples)} requests on {machine}, Python {platform.python_version()}")
    print(
        f"p50 {percentile(samples, 50):.1f} ms, p95 {percentile(samples, 95):.1f} ms, "
        f"p99 {percentile(samples, 99):.1f} ms, mean {statistics.mean(samples):.1f} ms"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=5)
    asyncio.run(main(parser.parse_args().rounds))
