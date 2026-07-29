# 牛牛画画 `draw`

按文字描述生图，或带参考图改图。需要文生图 / 图生图时安装本官方插件。默认由扩展直连画画网关，不依赖 AI Runtime。

**类型**：官方插件（需安装）

## 安装

控制台插件商店，或：

```bash
uv run pallas ext install pallas-plugin-draw
```

## 用法

| 命令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛画画 …` | 群内 | 按描述生成；可附图或回复图片作参考图改图 |

精确命令与「何人可用」以群内 **牛牛帮助** 为准。连通性可用 `牛牛连通` 测画图服务。

## 命令权限（代码默认）

| 命令 ID | 默认等级 |
| --- | --- |
| `draw.draw` | 所有人 |

实际生效等级以控制台「命令权限」为准。

## 配置

控制台 **插件 → 牛牛画画**：主 / 备画图线路在「画图网关」面板配置（第一条为主线）。可沿用 **AI 配置 · 接入** 的 Provider，也可手填地址与密钥。字段前缀多为 `pallas_image_*`。

保存后写入 `data/pallas_config/webui.json`。

## 排障

| 现象 | 处理 |
| --- | --- |
| 生成失败 | 看返回提示，再发 `牛牛连通` 查画图服务 |
| 次数或额度用尽 | 等待额度重置，或在服务端调整配额 |

## 源码

扩展仓 [`src/pallas_plugin_draw/`](https://github.com/PallasBot/Plugin-Draw/tree/main/src/pallas_plugin_draw)。主仓参考图逻辑：[`pallas/core/platform/media/draw_reference.py`](../../../pallas/core/platform/media/draw_reference.py)。

仓库：[Plugin-Draw](https://github.com/PallasBot/Plugin-Draw)

## 相关链接

- [命令权限](../../common/cmd_perm/README.md)
- [AI 扩展](../../guide/ai.md)
