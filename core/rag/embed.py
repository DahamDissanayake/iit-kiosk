"""Embedding models. FastEmbed runs ONNX on the CPU; HashEmbedder is for tests and dev."""

import math
import re
import zlib
from pathlib import Path
from typing import Protocol


class Embedder(Protocol):
    name: str
    dim: int

    def passages(self, texts: list[str]) -> list[list[float]]: ...

    def query(self, text: str) -> list[float]: ...


class FastEmbedder:
    dim = 384

    def __init__(self, name: str, cache_dir: Path | None = None) -> None:
        from fastembed import TextEmbedding

        self.name = name
        self._model = TextEmbedding(
            model_name=name, cache_dir=str(cache_dir) if cache_dir else None
        )

    def passages(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.passage_embed(texts)]

    def query(self, text: str) -> list[float]:
        return next(iter(self._model.query_embed(text))).tolist()


class HashEmbedder:
    """Bag-of-words hashed into 384 buckets. Deterministic, no download."""

    dim = 384

    def __init__(self, name: str = "test-hash") -> None:
        self.name = name

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            v[zlib.crc32(word.encode()) % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v))
        if norm == 0:
            v[0], norm = 1.0, 1.0
        return [x / norm for x in v]

    def passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def query(self, text: str) -> list[float]:
        return self._vec(text)
