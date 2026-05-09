from __future__ import annotations

import random

# 已带 @；归档图在末尾再接全角冒号后接图；文本走 drift_at_nickname 后再拼「：正文」
PSEUDO_SENDER_AT = (
    "@陆",
    "@不知名企鹅",
    "@某位博士",
    "@预言家",
    "@牛牛",
    "@女祭司",
)


def pick_pseudo_sender_at() -> str:
    return random.choice(PSEUDO_SENDER_AT)
