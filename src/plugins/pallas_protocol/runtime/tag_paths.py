"""Release tag → 解压目录名。"""

from __future__ import annotations


def sanitize_release_tag_for_path(tag: str) -> str:
    """将 Release tag 转为 ``runtime_extract/<后端>/<本返回值>/`` 目录名。

    - 空视为 ``latest``
    - 保留字母数字与 ``._-+``；其余字符替换为 ``_``
    """
    t = (tag or "").strip()
    if not t:
        t = "latest"
    out: list[str] = []
    for ch in t:
        if ch.isalnum() or ch in "._-+":
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out).strip("._-+ ")
    return s[:180] if s else "latest"
