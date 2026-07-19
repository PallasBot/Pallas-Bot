# 安装官方插件

装、卸、更新官方插件。

## 三类包

| 类型 | 说明 |
| --- | --- |
| `core` | 随主仓启动，无需额外安装 |
| 官方插件 | PyPI 包；日常用 WebUI 插件商店装 / 卸 / 更新 |
| `local` / community | 站点私有或社区插件，一般放在 `local/plugins/` |

4.0 起多数玩法与站点能力从本体拆成独立 pip 包。

## 适用场景

- 主仓已跑，帮助菜单无决斗、MAA、谁是卧底等能力
- 新站点按需装插件；**从 3.x 升级且玩法已在跑则通常不必重装**
- Docker / 分片：确认生效的是 pip、镜像预装，还是 `local/plugins/` 副本

## 推荐顺序

1. **WebUI 插件商店**（装、卸、更新、看加载态）——日常运维
2. **CLI**（`pallas ext`）——初次部署、SSH、脚本化、商店不可用时
3. **镜像构建期** `uv sync --extra ...`——精简 Docker 无现场装包条件时

## 方式一：WebUI 插件商店（推荐）

1. 打开 `http://<主机>:8088/pallas/` 并登录
2. 侧栏「插件商店」→「安装」「更新」或「安装并重启」

| 状态 | 含义 |
| --- | --- |
| 未安装 | 当前环境无 pip 包 |
| 已安装待重启 | 包已装入环境，当前进程未加载 |
| 已加载 | 当前运行进程已在使用 |

插件配置、命令权限、治理页在控制台完成即可。

## 方式二：CLI（备选）

```bash
uv run pallas ext list
uv run pallas ext install pallas-plugin-duel --restart
uv run pallas ext uninstall pallas-plugin-duel --restart
```

适合无图形界面、CI/CD 或批量初始化。有控制台时，官方插件装卸更新仍以商店为主。

## 运行前提（CLI / 商店共用）

商店一键安装需要：完整 Pallas-Bot 工作目录、能执行 `uv`、能访问 PyPI。

```bash
uv --version
uv run pallas --help
```

::: warning 精简 Docker 镜像例外
精简镜像往往没有容器内现场装包条件。构建期预装，或部署后通过能访问 PyPI 的控制台商店安装。
:::

## 常见官方插件对照

| 包名 | 作用 |
| --- | --- |
| `pallas-plugin-protocol` | 协议端管理、账号上号、relologin 相关能力 |
| `pallas-plugin-duel` | 决斗与八角笼玩法 |
| `pallas-plugin-who-is-spy` | 谁是卧底 |
| `pallas-plugin-maa` | MAA 远控 |
| `pallas-plugin-ai-media` | 唱歌、酒后聊天等媒体类能力 |
| `pallas-plugin-draw` | 绘图相关能力 |
| `pallas-plugin-dream` | 做梦相关能力 |
| `pallas-plugin-bot-status` | 在吗、报数等状态类能力 |

以下能力已在 4.0 回归 core，无需再装：

- `llm_chat`
- `pb_stats`

## 安装后验收

1. 商店显示「已加载」（或 `pallas ext list` 为 `installed=yes`）
2. 群里发「牛牛帮助」，能看到新增能力
3. 有配置页时，WebUI 能打开并读到配置

::: warning 分片
部分插件只在 worker 侧运行。控制台加载态取决于 hub 聚合到的 worker 元数据。
:::

## 卸载与回滚

优先在 **插件商店** 卸载。无 UI 时用 `pallas ext uninstall`。

::: warning
- 卸载 pip 包不会删掉 `local/plugins/` 里的同名副本
- 装、卸、升级之后都重启一次
:::

## 相关阅读

- [网页控制台](../../guide/web-console.md)
- [CLI 参考](/maintainer/reference/cli)（Bot 升级与初次部署）
- [用户向安装说明](../../guide/install-plugins.md)
