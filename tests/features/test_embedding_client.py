from __future__ import annotations

from pallas.product.llm.knowledge.embedding_client import parse_embeddings_response


def test_parse_embeddings_response_sorts_by_index() -> None:
    payload = {
        "data": [
            {"index": 1, "embedding": [0.2, 0.8]},
            {"index": 0, "embedding": [1.0, 0.0]},
        ]
    }
    vectors = parse_embeddings_response(payload)
    assert vectors == [[1.0, 0.0], [0.2, 0.8]]
