# DynamicConfigPanel

插件配置页按 Bot 返回的 `fields[]` 渲染表单，并展示 unexpected keys 兜底区。实现在 WebUI 的 `DynamicConfigPanel` / `PluginConfigWorkspace`。

## Pydantic `json_schema_extra`

插件 `config.py` 的 `Field` 上声明 UI 元数据：

```python
from pydantic import BaseModel, Field

class Config(BaseModel):
    api_base: str = Field(
        default="",
        description="API 根地址",
        json_schema_extra={
            "secret": False,
            "multiline": False,
            "ui_group": "连接",
            "ui_order": 10,
            "ui_hidden": False,
        },
    )
```

| 键 | 类型 | 说明 |
| --- | --- | --- |
| `secret` | bool | 密码框 + 打码 |
| `multiline` | bool | 多行文本 |
| `ui_group` | str | 分组标题（同组字段相邻展示） |
| `ui_order` | int | 组内排序，越小越靠前 |
| `ui_hidden` | bool | 维护者进阶项，默认折叠 |
| `ui_widget` | str | 非默认控件；当前支持 `provider_gateway` |
| `ui_gateway` | dict | 与 `ui_widget=provider_gateway` 配套的绑定（见下节） |

Bot 侧 `field_meta_for_model_field()` 会把上述键透传到 `fields[]` 项。推荐用 `pallas.api.config.ui_provider_gateway(...)` 生成，勿手写残缺结构。

## Provider 主备线路（`provider_gateway`）

用于「主线优先、失败按备线顺序尝试」的 LLM / 画图 Provider 选择。WebUI 挂载通用 `ProviderGatewayPanel`，并把绑定字段从普通表单中隐藏。

```python
from pallas.api.config import field_help, ui_provider_gateway
from pydantic import BaseModel, Field

class Config(BaseModel, extra="ignore"):
    # unified：单 JSON 数组字段（推荐新插件）
    my_ai_gateways: list[dict] = Field(
        default_factory=list,
        description=field_help("AI 线路（主线 + 备线）", "按顺序尝试"),
        json_schema_extra=ui_provider_gateway(
            mode="unified",
            allow_manual=False,
            capability="chat",
            field="my_ai_gateways",
            title="AI 线路",
            label="AI 线路",
            group="AI",
        ),
    )
```

| 参数 | 说明 |
| --- | --- |
| `mode` | `unified`：单数组字段；`split`：主线散字段 + `backends` 备线数组（画画现网） |
| `allow_manual` | `False`（默认）仅沿用「AI 配置 · 接入」Provider；`True` 可选手填 base_url / api_key |
| `capability` | 过滤 Provider 能力，如 `chat` / `image` |
| `field` | unified 下的数组字段名（可省略，前端用 anchor 字段名） |
| `primary` / `backends` | split 下主线字段映射与备线数组键 |
| `currency_field` | 可选费用币种字段（画画） |
| `title` / `label` / `group` | 面板标题、表单项标签、分组 |

参考：画画（`split` + `allow_manual=True`）、社区插件 memes（`unified` + 仅 Provider）。

旧版 Bot 若无 `ui_provider_gateway`，插件应对 import 做兼容回退（返回空 `json_schema_extra`），避免加载失败。

## unexpected keys

`webui.json` 的 `env` 中存在、但当前 `config.py` 未声明的键，会出现在 GET payload 的 `unexpected_keys` 中。面板底部以只读列表展示，避免静默丢配置。

保存可视化表单时仍只提交已知字段；raw TOML 模式可编辑 unexpected 键（见 OPT-WEB-014）。

## 相关

- [配置与 WebUI](config-and-webui.md)
- `pallas/console/webui/field_meta.py`
- `pallas/console/webui/provider_gateway.py`
- WebUI：`src/components/provider/ProviderGatewayPanel.tsx`、`src/utils/providerGateways.ts`
