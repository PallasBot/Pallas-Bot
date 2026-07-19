"""知识块关键词检索（无 embedding）；向量模式见 vector_backend。"""

from __future__ import annotations

from pallas.product.llm.knowledge.models import KnowledgeChunkDecl, KnowledgeSourceDecl, RetrievedKnowledgeChunk
from pallas.product.llm.memory.retrieve import memory_relevance_score


def retrieve_chunks_keyword(
    decl: KnowledgeSourceDecl,
    query_text: str,
    *,
    top_k: int,
    max_chunk_len: int,
) -> list[RetrievedKnowledgeChunk]:
    scored: list[RetrievedKnowledgeChunk] = []
    for raw in decl.chunks:
        chunk = raw if isinstance(raw, KnowledgeChunkDecl) else KnowledgeChunkDecl.model_validate(raw)
        score = memory_relevance_score(
            query_text,
            keywords=chunk.keywords,
            content=chunk.content,
        )
        if score <= 0:
            continue
        content = (chunk.content or "").strip()
        if len(content) > max_chunk_len:
            content = content[: max_chunk_len - 1] + "…"
        title = (chunk.title or decl.title or decl.source_id).strip()
        scored.append(
            RetrievedKnowledgeChunk(
                source_id=decl.source_id,
                title=title,
                content=content,
                score=score,
            )
        )
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[: max(1, top_k)]


def retrieve_chunks_from_decl(
    decl: KnowledgeSourceDecl,
    query_text: str,
    *,
    top_k: int,
    max_chunk_len: int,
) -> list[RetrievedKnowledgeChunk]:
    from pallas.product.llm.knowledge.vector_backend import get_vector_retrieve_backend

    return get_vector_retrieve_backend().retrieve(
        decl,
        query_text,
        top_k=top_k,
        max_chunk_len=max_chunk_len,
    )
