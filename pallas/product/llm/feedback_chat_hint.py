"""提供给 feedback_learning 的中文 trigger 匹配工具。"""

from __future__ import annotations


def correction_matches_query(user_text: str, query_text: str) -> bool:
    user = str(user_text or "").strip()
    query = str(query_text or "").strip()
    if not user or not query:
        return False
    if len(user) >= 3 and user in query:
        return True
    if len(query) >= 3 and query in user:
        return True
    shorter, longer = (user, query) if len(user) <= len(query) else (query, user)
    for size in range(min(len(shorter), 12), 3, -1):
        for start in range(len(shorter) - size + 1):
            chunk = shorter[start : start + size]
            if chunk in longer:
                return True
    return False
