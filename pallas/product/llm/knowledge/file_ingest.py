"""从 data/pallas_knowledge 加载 Markdown / JSONL 知识块。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nonebot import logger

from pallas.core.foundation.paths import PROJECT_ROOT
from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.knowledge.models import KnowledgeChunkDecl, KnowledgeSourceDecl

if TYPE_CHECKING:
    from pathlib import Path

_KNOWLEDGE_DIR = PROJECT_ROOT / "data" / "pallas_knowledge"
_FILE_SOURCE_ID = "pallas.file_ingest"
MAX_FILE_KNOWLEDGE_CHUNKS = 200
_registered = False


def knowledge_ingest_dir() -> Path:
    return _KNOWLEDGE_DIR


def _chunk_markdown(text: str, *, source_name: str) -> list[KnowledgeChunkDecl]:
    lines = (text or "").splitlines()
    sections: list[tuple[str, list[str]]] = []
    title = source_name
    buf: list[str] = []
    for line in lines:
        if line.startswith("#"):
            if buf and any(part.strip() for part in buf):
                sections.append((title, buf))
            title = line.lstrip("#").strip() or source_name
            buf = []
            continue
        buf.append(line)
    if buf and any(part.strip() for part in buf):
        sections.append((title, buf))
    chunks: list[KnowledgeChunkDecl] = []
    for sec_title, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if len(body) < 8:
            continue
        keywords = ",".join(sec_title.replace(" ", ",").split(",")[:8]) if sec_title else ""
        chunks.append(
            KnowledgeChunkDecl(
                title=sec_title[:80] or source_name,
                content=body[:2000],
                keywords=keywords[:120],
            )
        )
    return chunks


def _chunk_jsonl(text: str) -> list[KnowledgeChunkDecl]:
    chunks: list[KnowledgeChunkDecl] = []
    for line in (text or "").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        content = str(data.get("content") or "").strip()
        if len(content) < 8:
            continue
        title = str(data.get("title") or content[:24]).strip()
        keywords = str(data.get("keywords") or "").strip()
        chunks.append(
            KnowledgeChunkDecl(
                title=title[:80],
                content=content[:2000],
                keywords=keywords[:120],
            )
        )
    return chunks


def load_file_knowledge_decl(*, root: Path | None = None) -> KnowledgeSourceDecl | None:
    base = root or _KNOWLEDGE_DIR
    if not base.is_dir():
        return None
    chunks: list[KnowledgeChunkDecl] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith(".") or path.name.upper() == "README.MD":
            continue
        suffix = path.suffix.lower()
        if suffix not in {".md", ".jsonl"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("knowledge ingest read failed path={} err={}", path, exc)
            continue
        stem = path.stem
        if suffix == ".md":
            chunks.extend(_chunk_markdown(text, source_name=stem))
        elif suffix == ".jsonl":
            chunks.extend(_chunk_jsonl(text))
        if len(chunks) >= MAX_FILE_KNOWLEDGE_CHUNKS:
            break
    if not chunks:
        return None
    return KnowledgeSourceDecl(
        source_id=_FILE_SOURCE_ID,
        title="本地知识目录",
        description=f"来自 {base.relative_to(PROJECT_ROOT) if base.is_relative_to(PROJECT_ROOT) else base}",
        chunks=chunks[:MAX_FILE_KNOWLEDGE_CHUNKS],
    )


def ensure_file_knowledge_registered(*, cfg: LlmConfig | None = None, force: bool = False) -> bool:
    global _registered
    if _registered and not force:
        return True
    c = cfg or get_llm_config()
    if not c.llm_knowledge_file_ingest_enabled:
        return False
    try:
        decl = load_file_knowledge_decl()
        if decl is None:
            return False
        from pallas.product.llm.knowledge.registry import register_builtin_knowledge_source

        register_builtin_knowledge_source(source_id=decl.source_id, decl=decl)
    except Exception as exc:
        logger.warning("knowledge file ingest register failed err={}", exc)
        return False
    _registered = True
    return True


def reset_file_knowledge_registration_for_tests() -> None:
    global _registered
    _registered = False
