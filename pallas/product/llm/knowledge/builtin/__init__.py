"""内置知识源注册。"""

from __future__ import annotations

from pallas.product.llm.knowledge.builtin.bot_faq import BOT_FAQ_SOURCE
from pallas.product.llm.knowledge.registry import register_builtin_knowledge_source

register_builtin_knowledge_source(source_id=BOT_FAQ_SOURCE.source_id, decl=BOT_FAQ_SOURCE)
