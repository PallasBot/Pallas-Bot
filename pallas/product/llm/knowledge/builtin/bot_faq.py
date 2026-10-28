"""Bot 通用 FAQ 知识源（非特定领域 KB）。"""

from __future__ import annotations

from pallas.product.llm.knowledge.models import KnowledgeChunkDecl, KnowledgeSourceDecl

BOT_FAQ_SOURCE = KnowledgeSourceDecl(
    source_id="pallas.bot_faq",
    title="牛牛使用说明",
    description="关于 Pallas 历史会话记录、MaiBot 记忆与知识参考的常见问题",
    chunks=[
        KnowledgeChunkDecl(
            title="清空会话",
            content="发送 @牛牛 clear 仅清理 Pallas 侧当前用户在本群的历史会话记录，不影响 MaiBot 的记忆或核心人设。",
            keywords="清空,clear,忘记,重置,会话",
        ),
        KnowledgeChunkDecl(
            title="多轮记忆",
            content="LLM 聊天的上下文与记忆由独立 MaiBot 管理；Pallas 的历史会话、知识与记忆不会自动同步到 MaiBot。",
            keywords="记忆,上下文,多轮,聊天,会话",
        ),
        KnowledgeChunkDecl(
            title="知识参考",
            content=(
                "Pallas 知识源供本平台能力检索参考，不会自动注入 MaiBot；参考内容不得覆盖牛牛的核心人设与说话风格。"
            ),
            keywords="知识,参考,RAG,注入,人设",
        ),
    ],
)
