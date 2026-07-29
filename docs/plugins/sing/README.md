# 牛牛唱歌 `sing`

智能翻唱、续唱、点歌与查歌名。需要媒体翻唱 / 点歌时安装；依赖 **Pallas-Bot-AI（AI Runtime）**，与普通 `@牛牛` 聊天无关。

**类型**：官方插件（需安装）

## 安装

控制台插件商店，或：

```bash
uv run pallas ext install pallas-plugin-ai-media
```

另需部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)，并在控制台配置媒体服务。见 [LLM 对话、媒体与 AI Runtime](../../guide/ai-runtime-choice.md)。

自 `pallas-plugin-ai-media` **4.1.0** 起，本包仅含唱歌与 TTS；酒后对话已由本体 [llm_chat](../llm_chat/README.md) 承接。

## 用法

| 命令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛唱歌 歌曲名 [key=±N]` | 群内 | 翻唱；可附升降调 |
| `牛牛继续唱` / `牛牛接着唱` | 群内 | 续唱上一首 |
| `牛牛点歌 歌曲名` | 群内 | 播放网易云原曲 |
| `牛牛什么歌` / `牛牛哪首歌` | 群内 | 查询当前曲目 |
| `网易云登录` / `网易云登出` | 私聊 | 维护网易云登录 |

精确命令与「何人可用」以群内 **牛牛帮助** 为准。

## 命令权限（代码默认）

| 命令 ID | 默认等级 |
| --- | --- |
| `sing.sing` | 所有人 |
| `sing.play` | 所有人 |
| `sing.request_song` | 所有人 |
| `sing.song_title` | 所有人 |
| `sing.ncm_login` | 仅超管 |
| `sing.ncm_logout` | 仅超管 |

实际生效等级以控制台「命令权限」为准。面向用户的 usage 不要写死角色名。

## 配置

推荐在控制台 **AI 配置 → 媒体**：

| 面板 | 配置什么 |
| --- | --- |
| **媒体服务 · 连接** | 服务地址与 **Bearer Token**（同步 `AI_SERVER_*` / `TTS_API_TOKEN`；须与 AI 侧 `PALLAS_AI_API_TOKEN` 一致） |
| **媒体资产** | 官方权重一键下载（`sing_pallas` / `sing_pretrain` 等） |
| **唱歌** | 侧车默认 Speaker / 后端；嵌入插件配置（启停、音色映射、合成时长） |
| **网易云** | 点歌所需登录 |

自 `pallas-plugin-ai-media` **4.3.0** 起，插件页不再展示服务地址 / endpoint（由媒体连接统一管理）。

### 自备音色

在 **Pallas-Bot-AI** 仓库根下新建目录：

```text
resource/sing/models/<音色名>/
```

- `<音色名>` 即 Speaker id（例如 `pallas`）；**不要**占用 `pretrain`（公共预训练权重）
- 放入对应 SVC 后端的 `.pt` / `.pth`，刷新控制台「唱歌」页应能探测到
- 在插件「音色映射」里把命令前缀（如「牛牛」「帕拉斯」）指到该 id

官方包也可在「媒体资产」下载 `sing_pallas` / `sing_pretrain`。

保存后写入 `data/pallas_config/webui.json`。

## 排障

| 现象 | 处理 |
| --- | --- |
| 没有返回语音 | 确认 AI Runtime 在线，再发 `牛牛连通` 测唱歌服务；音色放在 `resource/sing/models/<音色名>/` |
| 点歌失败 | 检查网易云是否已登录（**AI 配置 → 媒体 → 网易云**） |
| 插件配置加载失败 | 先在插件商店安装 `pallas-plugin-ai-media` |

## 源码

扩展仓 `pallas-plugin-ai-media` 中的 `sing` 目录。

仓库：[Plugin-Ai-Media](https://github.com/PallasBot/Plugin-Ai-Media)

## 相关链接

- [智能对话 llm_chat](../llm_chat/README.md)
- [牛牛说 tts](../tts/README.md)
- [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)
- [命令权限](../../common/cmd_perm/README.md)
