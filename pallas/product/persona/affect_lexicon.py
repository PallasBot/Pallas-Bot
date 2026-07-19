"""情感启发式词表：内置温和/粗鄙基表，可挂载扩展文件或与 scrub 词表合并。"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.foundation.paths import project_path, resource_dir

_BASELINE_PATH = resource_dir("persona", "affect_lexicon_baseline.txt")
_SECTION_RE = re.compile(r"^\[(polite|harsh)\]\s*$", re.IGNORECASE)
_PUNCT_BURST_RE = re.compile(r"[!?！？]{2,}")
_PUNCT_SINGLE_RE = re.compile(r"[!?！？]")

LEXICON_VERSION = 1


def parse_lexicon_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"polite": [], "harsh": []}
    current = ""
    seen: dict[str, set[str]] = {"polite": set(), "harsh": set()}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        section_match = _SECTION_RE.match(line)
        if section_match:
            current = section_match.group(1).lower()
            continue
        if current not in sections:
            continue
        token = line.lower()
        if token in seen[current]:
            continue
        seen[current].add(token)
        sections[current].append(token)
    return sections


def read_lexicon_file(path: Path) -> dict[str, list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"polite": [], "harsh": []}
    return parse_lexicon_sections(text)


def merge_lexicon_sections(*parts: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    polite_seen: set[str] = set()
    harsh_seen: set[str] = set()
    polite: list[str] = []
    harsh: list[str] = []
    for part in parts:
        for token in part.get("polite", []):
            key = token.lower()
            if key and key not in polite_seen:
                polite_seen.add(key)
                polite.append(key)
        for token in part.get("harsh", []):
            key = token.lower()
            if key and key not in harsh_seen:
                harsh_seen.add(key)
                harsh.append(key)
    return {"polite": tuple(polite), "harsh": tuple(harsh)}


def try_load_scrub_lexicon_harsh() -> tuple[str, ...]:
    raw = repo_env_raw_value("PERSONA_AFFECT_MERGE_SCRUB_LEXICON")
    if raw is None or raw.strip().lower() not in ("1", "true", "yes", "on"):
        return ()
    try:
        from pallas.product.message_scrub.local_lexicon import _all_patterns_lower

        return tuple(p for p in _all_patterns_lower() if p)
    except Exception:
        return ()


def resolve_lexicon_path(raw_path: str) -> Path:
    path = Path(raw_path.strip())
    if not path.is_absolute():
        path = project_path(path)
    return path


@lru_cache(maxsize=4)
def load_affect_lexicon() -> dict[str, tuple[str, ...]]:
    baseline = read_lexicon_file(_BASELINE_PATH)
    extras: list[dict[str, list[str]]] = [baseline]
    extra_path = (repo_env_raw_value("PERSONA_AFFECT_LEXICON_EXTRA") or "").strip()
    if extra_path:
        extras.append(read_lexicon_file(resolve_lexicon_path(extra_path)))
    merged = merge_lexicon_sections(*extras)
    scrub_harsh = try_load_scrub_lexicon_harsh()
    if scrub_harsh:
        merged = merge_lexicon_sections(
            {"polite": list(merged["polite"]), "harsh": list(merged["harsh"])},
            {"polite": [], "harsh": list(scrub_harsh)},
        )
    return merged


def clear_affect_lexicon_cache() -> None:
    load_affect_lexicon.cache_clear()


def baseline_polite_examples(limit: int = 8) -> list[str]:
    lex = load_affect_lexicon()
    return list(lex["polite"][: max(0, int(limit))])


def punct_aggression_score(text: str) -> float:
    plain = str(text or "").strip()
    if not plain:
        return 0.0
    score = 0.0
    burst = len(_PUNCT_BURST_RE.findall(plain))
    singles = len(_PUNCT_SINGLE_RE.findall(plain))
    score += min(1.0, burst * 0.35)
    score += min(0.5, singles * 0.06)
    if len(plain) <= 6 and singles >= 1:
        score += 0.15
    return min(1.0, score)


def scan_content_tags(text: str) -> tuple[bool, bool]:
    plain = str(text or "").strip().lower()
    if not plain:
        return False, False
    lex = load_affect_lexicon()
    polite_hit = any(token in plain for token in lex["polite"])
    harsh_hit = any(token in plain for token in lex["harsh"])
    return polite_hit, harsh_hit
