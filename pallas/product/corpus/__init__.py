"""多语料源：local + 可选 fed / community。"""

from pallas.product.corpus.composite_repo import CompositeContextRepository
from pallas.product.corpus.config import clear_corpus_config_cache, get_corpus_config
from pallas.product.corpus.factory import maybe_wrap_composite
from pallas.product.corpus.merge import merge_contexts

__all__ = [
    "CompositeContextRepository",
    "clear_corpus_config_cache",
    "get_corpus_config",
    "maybe_wrap_composite",
    "merge_contexts",
]
