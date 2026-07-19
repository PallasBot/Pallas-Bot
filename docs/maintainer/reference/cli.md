# CLI 参考

维护者在 **Pallas-Bot 仓库根**用的命令行入口：`uv run pallas <子命令>`（无子命令时默认启动单进程 Bot）。

**分工约定**：CLI 侧重 **拉代码、同步依赖、启停、升级 Bot/WebUI**；**官方插件的装/卸/更新、运行中配置** 优先在 [网页控制台](../../guide/web-console.md) 完成。

完整子命令：`uv run pallas --help`。

## 升级与维护（CLI 主战场）

### 无痛升级（3.x → 4.0 或版本对齐）

```bash
uv run pallas maintenance run \
  --update-bot \
  --update-webui \
  --sync-extra pg \
  --dev
```

等价分步：

```bash
uv run pallas update bot
uv run pallas update webui
uv run pallas sync --dev --extra pg
uv run pallas restart
```

升级完成后，若要补装或更新官方插件，登录控制台 **插件商店** 操作（不必为插件专门记 CLI）。

### 依赖同步

```bash
uv run pallas sync --extra pg --extra coord-redis
```

### 启停

```bash
uv run pallas status
uv run pallas restart
uv run pallas stop
uv run pallas run unified          # 单进程
uv run pallas run shard            # 分片
```

## 官方插件（CLI 备选）

日常装卸更新请用 **WebUI 插件商店**。CLI 仅在无 UI、脚本化或排障时使用：

```bash
uv run pallas ext list
uv run pallas ext install pallas-plugin-duel --restart
uv run pallas ext uninstall pallas-plugin-duel --restart
```

社区插件（git 索引）仍可用 CLI：

```bash
uv run pallas plugin install <id>
uv run pallas plugin list
```

## AI Runtime

```bash
uv run pallas ai path
uv run pallas ai setup                 # LLM-only（不装 torch）
uv run pallas ai setup --check-only
uv run pallas ai setup --remote-only
uv run pallas ai setup --with-media    # 唱歌/TTS（装 torch CPU）
uv run pallas ai setup --with-media --gpu
```

详见 [AI Runtime 安装](../install/ai-runtime.md)。

## 体检

```bash
uv run pallas doctor
```

## 什么时候用 CLI vs WebUI

| 场景 | 优先 |
| --- | --- |
| 初次 clone、SSH 升级 Bot / WebUI | CLI |
| `maintenance run` 拉齐本体与 dist | CLI |
| 装 / 卸 / **更新**官方插件 | **WebUI 插件商店** |
| 改插件配置、命令权限、治理 | **WebUI** |
| 看运行态、分片聚合 | **WebUI** |
| 无 `uv`、无 SSH，只有浏览器 | **WebUI** |
| 批量脚本、CI、Docker 构建期 | CLI |

## 后续可聚合的方向

| 缺口 | 现状 | 说明 |
| --- | --- | --- |
| 官方插件更新 | 商店已有「更新」 | CLI 不必重复造轮子；缺省留给 WebUI |
| AI 仓 git 对齐 | `pallas ai setup` | 升级时 AI 仓手动 `git pull` 或待 `pallas update ai` |
| `.env` 迁移 | 独立脚本 | 待 `pallas config migrate` |
| 全栈一键升级 | `maintenance` + 控制台 | Bot 侧 CLI，插件侧 WebUI |

维护者清单：[升级](../deploy/upgrade.md)、[4.0 迁移指南](../../guide/4.0-migration.md)。

## 相关阅读

- [安装官方插件](../install/official-extensions.md)
- [网页控制台](../../guide/web-console.md)
- [分片部署](../deploy/sharded.md)
