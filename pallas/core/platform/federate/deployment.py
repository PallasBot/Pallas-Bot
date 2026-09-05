"""部署标识的惰性访问代理。

core 侧不直接依赖 ``pallas.product`` 的 community_stats 存储，
只在首次调用时经延迟 import 取平台部署标识，避免 core→product 编译期耦合。
底层 community_stats 存储自带状态缓存，重复调用为廉价读。
"""

from __future__ import annotations


def load_or_create_deployment_id() -> str:
    """返回本部署唯一标识，必要时惰性创建。"""
    from pallas.product.community_stats.store import load_or_create_deployment_id as _load

    return _load()
