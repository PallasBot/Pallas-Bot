<div align="center">
  <img alt="Pallas-Bot" src="https://user-images.githubusercontent.com/18511905/195892994-c1a231ec-147a-4f98-ba75-137d89578247.png" width="360" height="270" />
</div>

# pallas-plugin-draw

Pallas-Bot 4.0 官方扩展：**牛牛画画**（AI 生图网关）。

## 安装

需已安装 [Pallas-Bot](https://github.com/PallasBot/Pallas-Bot) **≥ 4.0**。

```bash
uv sync --extra plugins-draw
```

## 功能说明

群内 AI 生图；可纯文字或带参考图（附图/回复图）。依赖画画网关，次数受限。

### 用户命令

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛画画 … | 群内 | 按描述生图或改图 |

### 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `draw.draw` | 所有人 |

### 配置

WebUI **插件 → 牛牛画画** 或 **服务网关 / 连通性**；字段前缀为 `pallas_image_*`（历史命名，见文档站）。

完整键：本仓库 [`config.py`](src/pallas_plugin_draw/config.py)

### 排障

| 现象 | 处理 |
| --- | --- |
| 失败提示 | 看返回文案；用 `牛牛连通` 测网关 |
| 次数用尽 | 等待重置或调配额 |

## 文档

| 说明 | 链接 |
| --- | --- |
| 牛牛画画 · 用户文档 | [文档站 · draw](https://PallasBot.github.io/Pallas-Bot-Docs/plugins/draw) |
| 插件开发入门 | [develop/plugin/getting-started](https://PallasBot.github.io/Pallas-Bot-Docs/develop/plugin/getting-started) |

## 源码

[`src/pallas_plugin_draw/`](src/pallas_plugin_draw/)
