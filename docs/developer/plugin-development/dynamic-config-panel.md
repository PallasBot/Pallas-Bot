# DynamicConfigPanel

`DynamicConfigPanel.vue` 按 Bot 返回的 `fields[]` 渲染插件/通用配置，并展示 unexpected keys 兜底区。

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

Bot 侧 `field_meta_for_model_field()` 会把上述键透传到 `fields[]` 项。

## unexpected keys

`webui.json` 的 `env` 中存在、但当前 `config.py` 未声明的键，会出现在 GET payload 的 `unexpected_keys` 中。面板底部以只读列表展示，避免静默丢配置。

保存可视化表单时仍只提交已知字段；raw TOML 模式可编辑 unexpected 键（见 OPT-WEB-014）。

## 组件用法

```vue
<DynamicConfigPanel
  :fields="data.fields"
  :unexpected-keys="data.unexpected_keys"
  v-model="fieldValues"
  :disabled="saving"
/>
```

## 相关

- [配置与 WebUI](config-and-webui.md)
- `pallas/console/webui/field_meta.py`
