# 四、WebUI 配置热重载

权威页：[config-and-webui.md](../../../developer/plugin-development/config-and-webui.md)、[webui/README.md](../../../common/webui/README.md)。

| 事实 | 值 |
| --- | --- |
| 落盘 | `data/pallas_config/webui.json`（**最高优先级**） |
| 静态产物 | 默认 `data/pb_webui/public-react/` |
| 插件页 | `install_hot_reload_config` |
| 横切段 | 侧栏 **通用配置**（`env_sections.py`） |
| Provider / 聊天 / 媒体 | 侧栏 **AI 配置**（Bot Provider；非通用配置段） |

REST：[webui/api/README.md](../../../common/webui/api/README.md) · [02-plugins.md](../../../common/webui/api/02-plugins.md)。

## 4.1 标准接入

```python
from pydantic import BaseModel, Field
from pallas.api.config import install_hot_reload_config

class Config(BaseModel, extra="ignore"):
    threshold: int = Field(default=3, description="触发阈值。")

plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_config = plugin_webui.get
```

业务代码**始终** `get_config()`；不要在模块 import 时把配置存到全局变量。
`Field(..., description=...)` 即控制台表单文案。

## 4.2 进阶

- `parse_env_value` / `on_reload`：复杂类型与缓存刷新（参考 `packages/help/config.py`；外部扩展如 `draw` 同理）
- 未接热重载：`get_plugin_config(Config)`，保存后需重启
- `reload_policy: metadata`：改 help/ingress/`command_permissions` 声明时重建索引（不卸 matcher）→ [Reload 与 Activation](../../../developer/plugin-development/reload-and-activation.md)

## 4.3 插件页 vs 通用配置 vs AI 配置

| 场景 | 入口 |
| --- | --- |
| 插件自有开关/阈值 | 插件页 + `install_hot_reload_config` |
| 跨插件/维护者向（scrub、gateway、cmd_perm…） | **通用配置**段（`env_sections.py`） |
| LLM Provider / 聊天 / 媒体连接 | **AI 配置**（Bot Provider；普通聊天不依赖 Pallas-Bot-AI） |

段 ID 可与包名不同。在线统计 **`pb_stats`** 使用插件页热重载（旧通用段 ID `community_stats` 仅作重定向兼容）。

## 4.4 自检

- [ ] 可调项有 `Field(description=...)`
- [ ] handler 内 `get_config()` 而非读缓存
- [ ] 复杂解析已测 WebUI 保存 → 行为立即变化
- [ ] 若会改 help/ingress 声明且不想重启，已设 `reload_policy: metadata`
- [ ] 未把 Provider/聊天项塞进通用配置段

## 4.5 下一步

- 路径与数据 → [五、路径与数据](./05-paths-and-data.md)
- message_scrub → [六、message_scrub](./06-message-scrub.md)
