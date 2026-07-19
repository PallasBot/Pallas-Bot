# 发布

三条分发路径；归属层见 [Core vs 扩展](/developer/architecture/core-vs-extensions)。

## 路径矩阵

| 路径 | 归属 | 交付物 | 细节 |
| --- | --- | --- | --- |
| 官方插件 PyPI | Official | wheel、Git tag、README、semver | [extension-pypi-publish](../../develop/extension-pypi-publish.md) |
| 社区生态分发 | Community | README、metadata、图标、索引/Git | [community-plugin-author](../../guide/community-plugin-author.md) |
| 站点本地投放 | `local/plugins/` | 可维护目录 + 最小 README/metadata | 本页「本地」节 |

Core 不按独立插件发行，随主仓版本。

## 官方插件

| MUST | 检查 |
| --- | --- |
| 包名 / 仓名 / 版本一致 | `pyproject.toml` ↔ tag ↔ README 徽章 |
| 可独立安装升级 | PyPI 或文档化依赖入口 |
| 治理完备 | metadata、`activation_policy`、权限 |
| 发布链路可用 | 按 extension-pypi-publish 执行 |

## 社区插件

| MUST | 说明 |
| --- | --- |
| README | 用途、安装、依赖、最低 Pallas 版本 |
| metadata | 可被帮助 / 治理 / 索引消费 |
| 结构 | 插件 ID、目录、图标符合收录规范 |
| API | 仅 `pallas.api.*` |

分发方式：索引收录、Git 直装、或拷入本地插件目录。

## 本地插件

| MUST | MUST NOT |
| --- | --- |
| 目录清晰、最小 README | 依赖 `pallas.core.*` 作为长期稳定面 |
| 基本 metadata | 以「本机能跑」替代可维护结构 |

## 通用发布前检查

- [ ] README：用途、安装、依赖、版本范围
- [ ] metadata 接入现行治理
- [ ] ID / 目录 / 图标清楚
- [ ] 最小测试存在

官方额外：版本、tag、徽章、PyPI。  
社区额外：索引字段、Git 可达、商店展示文案。  
本地额外：确认无需公共发行、保留未来迁移空间。

## 相关

- [Core 与扩展](/developer/architecture/core-vs-extensions)
- [仓库结构](/developer/reference/repo-layout)
