"""Turning text into vectors, on the CPU, with no network after the first model download.

Production uses BAAI/bge-small-en-v1.5 (MIT licence, 384 dimensions) through fastembed and onnxruntime: no PyTorch,
no GPU, about 66 MB on disk. Tests use :class:`HashingEmbedder`, a deterministic hashed bag of words that needs no
download. It exercises every code path but says nothing about relevance, so the retrieval evaluation always runs with
the real model.
"""

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt

type Vectors = npt.NDArray[np.float32]

DIMENSIONS = 384
"""The width of the vector column in the schema."""


class Embedder(Protocol):
    @property
    def name(self) -> str: ...

    def embed_passages(self, texts: Sequence[str]) -> Vectors:
        """One unit-length row per text. CPU-bound: call it through ``asyncio.to_thread`` from async code."""
        ...

    def embed_query(self, text: str) -> Vectors: ...


class FastEmbedder:
    # bge models were trained with this instruction in front of short queries and nothing in front of passages.
    QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5", cache_dir: Path | None = None, threads: int = 2) -> None:
        import onnxruntime  # noqa: PLC0415  # only processes that embed pay for loading it
        from fastembed import TextEmbedding  # noqa: PLC0415

        onnxruntime.disable_telemetry_events()  # nothing in a bank process collects telemetry it was not asked to

        # Two threads, not onnxruntime's default of one per core. With the default, its worker threads keep spinning
        # after each one-query inference and starve the event loop: retrieval right after an embedding took 84 ms
        # instead of 5.5 ms on a 16-thread laptop, while the embedding itself was only 0.6 ms faster with the default
        # (docs/benchmark-results/2026-10-06-laptop.md).
        self._model = TextEmbedding(model_name=model, cache_dir=str(cache_dir) if cache_dir else None, threads=threads)
        self._name = model

    @property
    def name(self) -> str:
        return self._name

    def embed_passages(self, texts: Sequence[str]) -> Vectors:
        vectors: Vectors = np.asarray(list(self._model.embed(list(texts), batch_size=16)), dtype=np.float32)
        return vectors.reshape(len(texts), DIMENSIONS)

    def embed_query(self, text: str) -> Vectors:
        vector: Vectors = self.embed_passages([self.QUERY_PREFIX + text])[0]
        return vector


_TOKEN = re.compile(r"[a-z0-9]+")


class HashingEmbedder:
    """Hashed bag of words, signed to cancel collisions on average, then normalised. For tests only."""

    @property
    def name(self) -> str:
        return "hashing"

    def _one(self, text: str) -> Vectors:
        vector = np.zeros(DIMENSIONS, dtype=np.float32)
        for token in _TOKEN.findall(text.lower()):
            value = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "little")
            vector[value % DIMENSIONS] += 1.0 if value >> 63 else -1.0
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    def embed_passages(self, texts: Sequence[str]) -> Vectors:
        return np.stack([self._one(t) for t in texts]) if texts else np.zeros((0, DIMENSIONS), np.float32)

    def embed_query(self, text: str) -> Vectors:
        return self._one(text)


def create(kind: str, cache_dir: Path | None = None) -> Embedder:
    if kind == "hashing":
        return HashingEmbedder()
    if kind == "fastembed":
        return FastEmbedder(cache_dir=cache_dir)
    raise ValueError(f"unknown embedder {kind!r}")
