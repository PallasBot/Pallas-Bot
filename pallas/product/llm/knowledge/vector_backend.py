"""可插拔向量检索后端（hybrid RAG）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pallas.product.llm.config import VectorRetrieveMode, resolve_llm_vector_retrieve

if TYPE_CHECKING:
    from pallas.product.llm.knowledge.models import KnowledgeSourceDecl, RetrievedKnowledgeChunk


class VectorRetrieveBackend(Protocol):
    def retrieve(
        self,
        decl: KnowledgeSourceDecl,
        query_text: str,
        *,
        top_k: int,
        max_chunk_len: int,
    ) -> list[RetrievedKnowledgeChunk]: ...


def vector_retrieve_mode() -> VectorRetrieveMode:
    return resolve_llm_vector_retrieve()


class KeywordVectorBackend:
    def retrieve(
        self,
        decl: KnowledgeSourceDecl,
        query_text: str,
        *,
        top_k: int,
        max_chunk_len: int,
    ) -> list[RetrievedKnowledgeChunk]:
        from pallas.product.llm.knowledge.retrieve import retrieve_chunks_keyword

        return retrieve_chunks_keyword(decl, query_text, top_k=top_k, max_chunk_len=max_chunk_len)


def chunk_embedding_text(title: str, content: str) -> str:
    title_text = (title or "").strip()
    body = (content or "").strip()
    if title_text and body:
        return f"{title_text}\n{body}"
    return title_text or body


def blend_hybrid_score(*, embedding_score: int, keyword_score: int) -> int:
    if embedding_score <= 0 and keyword_score <= 0:
        return 0
    if embedding_score <= 0:
        return keyword_score
    if keyword_score <= 0:
        return embedding_score
    return max(embedding_score, keyword_score) + min(embedding_score, keyword_score) // 2


class EmbeddingAugmentedBackend:
    """embedding / hybrid / vector：优先 AI `/v1/embeddings`；失败回落关键词。"""

    def retrieve(
        self,
        decl: KnowledgeSourceDecl,
        query_text: str,
        *,
        top_k: int,
        max_chunk_len: int,
    ) -> list[RetrievedKnowledgeChunk]:
        mode = vector_retrieve_mode()
        keyword_hits = KeywordVectorBackend().retrieve(decl, query_text, top_k=top_k, max_chunk_len=max_chunk_len)
        embedding_hits = retrieve_chunks_embedding(
            decl,
            query_text,
            top_k=top_k,
            max_chunk_len=max_chunk_len,
            mode=mode,
        )
        if embedding_hits is not None:
            return embedding_hits
        return keyword_hits


def retrieve_chunks_embedding(
    decl: KnowledgeSourceDecl,
    query_text: str,
    *,
    top_k: int,
    max_chunk_len: int,
    mode: VectorRetrieveMode,
) -> list[RetrievedKnowledgeChunk] | None:
    from pallas.product.llm.knowledge.embedding_client import fetch_embeddings_sync
    from pallas.product.llm.knowledge.embedding_score import embedding_relevance_score
    from pallas.product.llm.knowledge.models import KnowledgeChunkDecl, RetrievedKnowledgeChunk
    from pallas.product.llm.memory.retrieve import memory_relevance_score

    query = (query_text or "").strip()
    if not query or not decl.chunks:
        return []

    chunk_rows: list[KnowledgeChunkDecl] = []
    embed_inputs: list[str] = [query]
    for raw in decl.chunks:
        chunk = raw if isinstance(raw, KnowledgeChunkDecl) else KnowledgeChunkDecl.model_validate(raw)
        text = chunk_embedding_text(chunk.title, chunk.content)
        if not text.strip():
            continue
        chunk_rows.append(chunk)
        embed_inputs.append(text)

    if not chunk_rows:
        return []

    vectors = fetch_embeddings_sync(embed_inputs)
    if vectors is None or len(vectors) != len(embed_inputs):
        return None

    query_vec = vectors[0]
    scored: list[RetrievedKnowledgeChunk] = []
    for chunk, chunk_vec in zip(chunk_rows, vectors[1:], strict=True):
        emb_score = embedding_relevance_score(query_vec, chunk_vec)
        kw_score = memory_relevance_score(query, keywords=chunk.keywords, content=chunk.content)
        if mode == "hybrid":
            score = blend_hybrid_score(embedding_score=emb_score, keyword_score=kw_score)
        else:
            score = emb_score
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


_active_backend: VectorRetrieveBackend | None = None


def get_vector_retrieve_backend() -> VectorRetrieveBackend:
    global _active_backend
    if _active_backend is not None:
        return _active_backend
    if vector_retrieve_mode() in ("embedding", "hybrid", "vector"):
        _active_backend = EmbeddingAugmentedBackend()
    else:
        _active_backend = KeywordVectorBackend()
    return _active_backend


def set_vector_retrieve_backend(backend: VectorRetrieveBackend | None) -> None:
    global _active_backend
    _active_backend = backend
