"""向量相似度打分（供 hybrid RAG）。"""

from __future__ import annotations

import math


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    norm_left = 0.0
    norm_right = 0.0
    for a, b in zip(left, right, strict=True):
        dot += a * b
        norm_left += a * a
        norm_right += b * b
    if norm_left <= 0.0 or norm_right <= 0.0:
        return 0.0
    return dot / math.sqrt(norm_left * norm_right)


def embedding_relevance_score(query_vec: list[float], chunk_vec: list[float]) -> int:
    sim = cosine_similarity(query_vec, chunk_vec)
    if sim <= 0.0:
        return 0
    return int(round(sim * 100))
