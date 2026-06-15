# draw（牛牛画画）

群内 AI 生图；可纯文字或带参考图（附图/回复图）。依赖画画网关，次数受限。

## 用户命令

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛画画 … | 群内 | 按描述生图或改图 |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `draw.draw` | everyone |

## 配置

[`config.py`](../../../src/plugins/draw/config.py) 与 WebUI **插件 → 牛牛画画**；网关亦可在 **服务网关 / 连通性** 配置。

### 命名约定

| 层面 | 名称 |
| --- | --- |
| 插件包名 / 命令 ID | `draw`（如 `draw.draw`） |
| WebUI / 帮助展示 | 牛牛画画 |
| 配置键 / 环境变量 | `pallas_image_*`（如 `pallas_image_base_url`、`pallas_image_draw_per_user_limit`） |

历史原因：生图能力早于插件包统一命名，字段前缀沿用 `pallas_image_`；新增文档与 WebUI 文案以「牛牛画画 / draw」为准，勿再引入第二套别名。

## 排障

| 现象 | 处理 |
| --- | --- |
| 失败提示 | 看返回文案；用 `牛牛连通` 测网关 |
| 次数用尽 | 等待重置或调配额配置 |

## 实现

[`src/plugins/draw/`](../../../src/plugins/draw/)
