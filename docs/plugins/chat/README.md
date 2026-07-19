<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="酒后聊天">
</p>

<h1 align="center">酒后聊天 chat</h1>

<p align="center">牛牛喝酒后可进入智能聊天状态。</p>

<p align="center">
  <img alt="官方插件" src="https://img.shields.io/badge/%E5%AE%98%E6%96%B9%E6%8F%92%E4%BB%B6-FE7D37">
  <img alt="控制台插件商店" src="https://img.shields.io/badge/%E6%8E%A7%E5%88%B6%E5%8F%B0-%E6%8F%92%E4%BB%B6%E5%95%86%E5%BA%97-4EA94B">
  <img alt="安装命令" src="https://img.shields.io/badge/uv%20run%20pallas%20ext%20install%20pallas--plugin--ai--media-586069">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

可在控制台插件商店安装，或执行 `uv run pallas ext install pallas-plugin-ai-media`。使用前还需要部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)。

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `@牛牛` | 群内 | 醉酒时触发 AI 回复。 |
| `牛牛 + 文本` | 群内 | 醉酒时进入聊天。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

无独立命令 ID，依赖醉酒状态触发。

## 配置项

> 可在控制台对应插件页中修改。

新用户只需配置全局 `LLM_CHAT_ENABLED`。开启后，酒后聊天与随时闲聊共用同一套 LLM 服务。

遗留 `CHAT_ENABLE` / `chat_enable` 仍可读，但只在未显式配置 `LLM_CHAT_ENABLED` 时启用旧的 RWKV 路径。

`AI_SERVER_*`、`LLM_CHAT_ENABLED` 等环境项建议在控制台或 `pallas.toml` 的 `[env]` 中配置。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无回复 | 确认牛牛已喝酒，且 AI 服务可达；LLM 路径需 `LLM_CHAT_ENABLED=true`。 |
| 冷却中无响应 | 群级冷却期间可能静默。 |

## 实现

源码位置：官方插件扩展仓 `pallas-plugin-ai-media` 的 `chat` 插件目录

关键文件：

- 扩展仓 `chat` 插件的 `__init__.py`：注册触发逻辑与元数据。
- 扩展仓 `chat` 相关处理文件：负责醉酒状态下的对话提交与回复。
- 主仓 `packages/drink/`：负责喝酒、醒酒与醉酒状态变化。

实现要点：

- 这个插件本身不提供独立命令权限，是否触发主要取决于醉酒状态和消息内容。
- 新路径走统一的 LLM 服务，旧路径只用于兼容历史站点。
- 与 `llm_chat` 共用部分 AI 基础设施，但触发时机和用户感知完全不同。

## 相关链接

- [命令权限说明](../common/cmd_perm/README.md)
- [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)
- [酒后聊天插件仓库](https://github.com/TogetsuDo/pallas-plugin-ai-media)
