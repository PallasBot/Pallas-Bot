"""插件作者稳定入口。

公开面经 curation：`pallas.api.*` 为社区插件唯一推荐 import 路径。
内核插件在 perm / commands / limits / storage / config 等横切能力上亦优先走 api，
深层的 `pallas.core.platform.*` 等待 `--strict-packages` 迁移完成后再收口。
"""
