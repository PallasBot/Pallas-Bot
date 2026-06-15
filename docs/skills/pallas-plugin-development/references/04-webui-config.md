# 四、WebUI 配置热重载

控制台插件页与通用配置写入 `data/pallas_config/webui.json`（**WebUI 落盘优先级最高**）。详情：[webui/README.md](../../common/webui/README.md)。

后端 REST 契约（路径、鉴权、写操作）：[webui/api/README.md](../../common/webui/api/README.md) · 插件配置域 [02-plugins.md](../../common/webui/api/02-plugins.md)。

## 4.1 标准接入

```python
from pydantic import BaseModel, Field
from src.console.webui import install_hot_reload_config

class Config(BaseModel, extra="ignore"):
    threshold: int = Field(default=3, description="触发阈值。")

plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_config = plugin_webui.get
```

业务代码**始终** `get_config()`；不要在模块 import 时把配置存到全局变量。

## 4.2 Field description 即 WebUI 文案

`Field(..., description="...")` 会出现在控制台表单；写清楚用户能看懂的说明。

环境变量键名：由插件名与字段名推导，落盘为大写（见 `plugin_api`）。

## 4.3 进阶：`parse_env_value` / `on_reload`

复杂类型（列表、枚举、URL）参考 `draw/config.py`：

- `parse_env_value`：把 webui.json 字符串解析成模型字段
- `on_reload`：配置变更后刷新运行时单例（缓存、连接池）

已有自定义缓存的插件可登记 `plugin_webui_registry`（如决斗插件）。

## 4.4 未接热重载时

仍可用 `get_plugin_config(Config)`，但**保存后需重启**进程才与磁盘一致。新插件默认应接热重载。

## 4.5 通用配置段（非单插件页）

横切能力在 WebUI「通用配置」注册段，见 `src/console/webui/env_sections.py`：cmd_perm、message_scrub、ingress_fanout 等。插件作者扩展新**全局段**需改内核并同步 WebUI 前端——一般优先用插件自己的 `config.py` + 热重载。

## 4.6 自检

- [ ] 所有可调项在 Pydantic `Config` 中有 `Field(description=...)`
- [ ] handler 内 `get_config()` 而非读缓存
- [ ] 复杂解析已测 WebUI 保存 → 行为立即变化

## 4.7 下一步

- 路径与数据 → [五、路径与数据](./05-paths-and-data.md)
- message_scrub → [六、message_scrub](./06-message-scrub.md)
