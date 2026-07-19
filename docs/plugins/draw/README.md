<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="牛牛画画">
</p>

<h1 align="center">牛牛画画 draw</h1>

<p align="center">按文字描述生图，或带参考图改图。</p>

<p align="center">
  <img alt="官方插件" src="https://img.shields.io/badge/%E5%AE%98%E6%96%B9%E6%8F%92%E4%BB%B6-FE7D37">
  <img alt="WebUI 插件商店" src="https://img.shields.io/badge/WebUI-%E6%8F%92%E4%BB%B6%E5%95%86%E5%BA%97-4EA94B">
  <img alt="安装命令" src="https://img.shields.io/badge/uv%20run%20pallas%20ext%20install%20pallas--plugin--draw-586069">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

可在控制台插件商店安装，或执行 `uv run pallas ext install pallas-plugin-draw`。

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛画画 …` | 群内 | 按描述生成图片，也可以附图或回复图片做参考图改图。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `draw.draw` | 所有人 |

## 配置项

> 可在控制台对应插件页中修改。

牛牛画画的主要连通性配置在控制台的服务网关 / 连通性页面，常见字段前缀为 `pallas_image_*`。

## 排障

| 现象 | 处理 |
| --- | --- |
| 生成失败 | 先看返回提示，再发送 `牛牛连通` 检查画图服务是否可用。 |
| 提示次数或额度用尽 | 等待额度重置，或在服务端调整配额。 |

## 实现

源码位置：扩展仓 [`src/pallas_plugin_draw/`](https://github.com/TogetsuDo/pallas-plugin-draw/tree/main/src/pallas_plugin_draw)

关键文件：

- `src/pallas_plugin_draw/__init__.py`：注册插件、命令与元数据。
- `src/pallas_plugin_draw/commands.py` 或同级命令文件：解析 `牛牛画画` 触发、组织请求参数。
- 主仓 [`pallas/core/platform/media/draw_reference.py`](../../pallas/core/platform/media/draw_reference.py)：处理参考图输入与兼容逻辑。

实现要点：

- 画图请求优先走 AI 服务的 `image.generate` 能力，Bot 侧主要负责收集文本、参考图和上下文。
- 附图、回复图片等输入会先整理成统一的参考图数据，再交给扩展仓执行具体生成流程。
- 主仓保留了扩展加载与回调衔接的基础槽位，所以即使插件本体在外部仓库，行为仍会接入现有消息与任务体系。

## 相关链接

- [命令权限说明](../common/cmd_perm/README.md)
- [牛牛画画插件仓库](https://github.com/TogetsuDo/pallas-plugin-draw)
