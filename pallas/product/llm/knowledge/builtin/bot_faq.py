"""Bot 通用 FAQ 知识源（非特定领域 KB）。"""

from __future__ import annotations

from pallas.product.llm.knowledge.models import KnowledgeChunkDecl, KnowledgeSourceDecl

BOT_FAQ_SOURCE = KnowledgeSourceDecl(
    source_id="pallas.bot_faq",
    title="牛牛使用说明",
    description="关于闲聊、会话记忆与知识注入的常见问题",
    chunks=[
        KnowledgeChunkDecl(
            title="清空会话",
            content="发送 @牛牛 clear 可清空当前群内的多轮 LLM 会话记忆，不会修改核心人设。",
            keywords="清空,clear,忘记,重置,会话",
        ),
        KnowledgeChunkDecl(
            title="多轮记忆",
            content="群内 @牛牛 聊天会保留本轮对话上下文；持久群内旧事由记忆治理单独控制。",
            keywords="记忆,上下文,多轮,聊天,会话",
        ),
        KnowledgeChunkDecl(
            title="知识参考",
            content="系统可能注入相关知识块作为参考，仅供参考，不得覆盖牛牛的核心人设与说话风格。",
            keywords="知识,参考,RAG,注入,人设",
        ),
    ],
)
