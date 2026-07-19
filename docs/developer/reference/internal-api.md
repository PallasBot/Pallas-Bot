# Internal API

可 import ≠ 对外稳定面。内部路径可在重构中移动或删除。

## 默认内部

| 前缀 | 说明 |
| --- | --- |
| `pallas.core.*` | 运行时与平台实现（除非经 `pallas.api` re-export） |
| `pallas.console.*` | WebUI / CLI 维护者向 |
| 深层 `pallas.product.*` | 产品域实现；未文档化为公开入口则内部 |

## 允许依赖方

| 允许 | 禁止（默认） |
| --- | --- |
| 主仓自身 | 社区插件 |
| 内置 `packages/` | PyPI 社区扩展 |
| 文档显式批准的协作点 | 「当前能 import」即当长期 API |

## 与公开层关系

```text
社区插件  →  pallas.api.*（L1）
官方插件  →  L1 + 文档化的 pallas.api.platform（L2）
主仓内部  →  L1/L2/L3；对外传播前先提升边界
```

缺口：文档/设计提出需求 → 提升为 `pallas.api.*` 或 Platform → 再依赖。禁止先耦合再逼平台冻结布局。

## 禁止误用

| 误用 | 后果 |
| --- | --- |
| 为拿现成功能直 import 深层模块 | 与目录布局强耦合 |
| 把 `pallas.console.*` 当插件 SDK | 维护者实现泄漏 |
| 把产品域内部当 Platform | 语义与版本错位 |

## CI

`tools/check_plugin_imports.py` 与 `community_plugin_author check` 校验社区边界。

## 相关

- [Platform API](platform-api.md)
- [pallas.api Cookbook](/developer/plugin-development/pallas-api-cookbook)
- [仓库布局](/developer/reference/repo-layout)
