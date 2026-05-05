# 🎨 牛牛画画 (Pallas Image)

**牛牛画画** 允许用户在群聊中通过自然语言描述生成图像，或提供参考图进行图生图/修图操作。

## ✨ 功能特性

- **文生图 (Text-to-Image)**：输入提示词，AI 根据描述生成图像。
- **图生图/修图 (Image-to-Image/Edit)**：支持附带参考图或回复图片消息，基于参考图生成新图像。
- **多传输层支持**：内置 `httpx`、`curl-cffi` (支持 TLS 指纹模拟) 和系统 `curl` 三种 HTTP 客户端，自动回退以确保连通性。
- **用量限制与冷却**：
  - 支持按群、按用户设置每日绘画次数上限。
  - 支持群级命令冷却时间，防止刷屏。
  - 支持白名单群组和无限制用户/群组配置。
- **原子化存储**：每日使用次数持久化存储至 JSON 文件，重启不丢失，且保证数据写入安全。

## 📋 前置要求

1. **NoneBot2** 环境已搭建。
2. **OneBot v11** 适配器已安装并运行。
3. **AI 绘图 API 服务**：需要一个兼容 OpenAI Images API 格式的后端服务（如 Stable Diffusion WebUI with API, Midjourney Proxy, DALL-E 3 等）。
4. (可选) **curl**：如果选择使用系统 curl 作为传输层，需确保服务器安装了 curl。

## ⚙️ 配置说明

在 NoneBot 的配置文件（`.env` 或 `.env.prod`）中添加以下配置项：
生成图片的参数可以全部交给服务接口

### 基础配置

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| [pallas_image_min_priority](../../../src/plugins/pallas_image/config.py#L6) | `int` | `5` | 插件优先级 |
| [pallas_image_base_url](../../../src/plugins/pallas_image/config.py#L7) | `str` | `""` | AI 绘图 API 的基础 URL (例如: `http://127.0.0.1:7860/`) |
| [pallas_image_api_key](../../../src/plugins/pallas_image/config.py#L8) | `str` | `""` | API 认证密钥 (Bearer Token) |
| [pallas_image_model](../../../src/plugins/pallas_image/config.py#L9) | `str` | `gpt-image-2` | 使用的模型名称 |
| [pallas_image_request_timeout](../../../src/plugins/pallas_image/config.py#L21) | `float` | `180` | 请求超时时间 (秒) |
| [pallas_image_max_concurrency](../../../src/plugins/pallas_image/config.py#L22) | `int` | `2` | 进程内并发生成请求上限 |

### 高级配置

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| [pallas_image_http_transport](../../../src/plugins/pallas_image/config.py#L23) | `str` | `"auto"` | HTTP 传输方式: `auto`, `httpx`, `cffi`, `curl` |
| [pallas_image_tls_impersonate](../../../src/plugins/pallas_image/config.py#L24) | `str` | `chrome124` | 当使用 `cffi` 时，模拟的浏览器 TLS 指纹 |
| [pallas_image_http_user_agent](../../../src/plugins/pallas_image/config.py#L25) | `str` | `curl/8.5.0` | 自定义 User-Agent |
| [pallas_image_size](../../../src/plugins/pallas_image/config.py#L15) | `str` | `""` | 生成图片的尺寸 (例如: `1024x1024`) |
| [pallas_image_aspect_ratio](../../../src/plugins/pallas_image/config.py#L11) | `str` | `""` | 宽高比 (如果 API 支持，例如: `16:9`) |
| [pallas_image_quality](../../../src/plugins/pallas_image/config.py#L16) | `str` | `auto` | 图片质量 (例如: `standard`, `hd`, `auto`) |
| [pallas_image_response_format](../../../src/plugins/pallas_image/config.py#L17) | `str` | `b64_json` | 响应格式 (例如: `url`, `b64_json`) |
| [pallas_image_use_edits_for_reference_images](../../../src/plugins/pallas_image/config.py#L18) | `bool` | `True` | 当有参考图时，是否优先使用 `/edits` 接口而非 `/generations` |
| [pallas_image_merge_reference_urls_into_prompt](../../../src/plugins/pallas_image/config.py#L19) | `bool` | `False` | 是否将参考图 URL 合并到提示词中发送 |
| [pallas_image_default_edit_prompt](../../../src/plugins/pallas_image/config.py#L20) | `str` | `按参考图调整` | 图生图时的默认提示词（如果用户未提供） |

### 权限与限制配置

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| [pallas_image_draw_group_whitelist](../../../src/plugins/pallas_image/config.py#L26) | `list[int]` | `[]` | 允许使用画图的群号列表，为空则所有群可用 |
| [pallas_image_draw_per_user_limit](../../../src/plugins/pallas_image/config.py#L27) | `int` | `0` | 每人每天在每群可调用次数上限；`0` 表示不限制 |
| [pallas_image_draw_unlimited_group_ids](../../../src/plugins/pallas_image/config.py#L33) | `list[int]` | `[]` | 不受次数限制的群号列表 |
| [pallas_image_draw_unlimited_user_ids](../../../src/plugins/pallas_image/config.py#L34) | `list[int]` | `[]` | 不受次数限制的用户 QQ 号列表 |
| [pallas_image_draw_command_cooldown](../../../src/plugins/pallas_image/config.py#L35) | `int` | `3` | 群内命令冷却时间 (秒) |

## 🚀 使用方法

在支持的群聊中发送以下指令：

### 1. 文生图
```text
牛牛画画 一只穿着宇航服的柯基犬，在火星表面，赛博朋克风格
```

### 2. 图生图 / 参考图生成
**方式 A：附带图片**
发送图片的同时，在消息中包含指令：
> [图片] 牛牛画画 把这只猫变成油画风格

**方式 B：回复图片**
回复某条包含图片的消息，并发送：
> 牛牛画画 背景换成海滩

### 3. 多图参考
可以一次性发送多张图片作为参考，AI 将综合这些图像的特征进行生成。

## 📂 数据存储

插件会在 `data/pallas_image/` 目录下生成以下文件：

- `pallas_draw_daily_usage.json`: 记录每个用户在各群的每日使用次数。
  - 结构示例：
    ```json
    {
      "version": 1,
      "entries": {
        "123456789:987654321": {
          "day": "2023-10-27",
          "count": 3
        }
      }
    }
    ```
## 🛠️ 故障排查

1. **连接失败**：
   - 检查 [pallas_image_base_url](../../../src/plugins/pallas_image/config.py#L7) 是否正确。
   - 尝试将 [pallas_image_http_transport](../../../src/plugins/pallas_image/config.py#L23) 设置为 `curl` 或 `cffi`，某些 API 服务可能对 TLS 指纹有严格要求。
   - 查看日志中的 `image api connection failed` 或 `curl 退出码` 错误信息。

2. **生成失败/报错**：
   - 检查 API Key 是否有效。
   - 检查模型名称 [pallas_image_model](../../../src/plugins/pallas_image/config.py#L9) 是否受服务端支持。
   - 查看日志中 `image generations failed` 的具体返回 body，通常包含 API 端的详细错误原因。

3. **次数未重置**：
   - 插件基于本地日期 (`date.today()`) 判断。如果服务器跨天未重启，内存中的数据会在次日首次调用时自动清理过期条目并持久化。
