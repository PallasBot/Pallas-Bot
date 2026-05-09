# sing（牛牛唱歌）

群内通过 **角色名前缀 + 唱歌/点歌/继续唱** 等触发，请求本机 **AI 唱歌服务**（HTTP），由异步任务 + [`callback`](../callback/README.md) 回传语音或文本结果；歌曲检索与进度依赖 **网易云** 相关逻辑。

## 前置条件

1. 部署与 Bot 配置一致的 **AI 服务**（默认 `127.0.0.1:9099`），且服务能访问 **回调地址** `POST /callback/{task_id}`（由 `callback` 插件注册）。
2. 在配置中开启 `sing_enable`（默认关闭）。

## 配置

见 [`src/plugins/sing/config.py`](../../../src/plugins/sing/config.py)：`ai_server_host`、`ai_server_port`、`sing_endpoint`、`play_endpoint`、`request_endpoint`、`sing_length`、`sing_speakers`（角色名到 speaker id 映射）。

## 用法摘要

- `[角色名]唱歌 [歌名]`，可选 `key=` 变调
- `[角色名]继续唱` / `接着唱`
- `牛牛点歌 [歌名]`（原曲，受 VIP 等逻辑影响）
- `[角色名]什么歌` / `哪首歌` / `啥歌`
- 仅 `[角色名]唱歌`：随机播放曾唱过的片段

具体以插件内规则与 `__plugin_meta__` 为准。

## 排障

| 现象 | 说明 |
|------|------|
| 无反应 | 确认 `sing_enable=true`、AI 服务可达、群冷却未挡住。 |
| 一直失败 | 看 AI 服务日志与 Bot 日志；确认 `/callback/{task_id}` 对 AI 服务网络可达。 |

实现见 [`src/plugins/sing/__init__.py`](../../../src/plugins/sing/__init__.py)。
