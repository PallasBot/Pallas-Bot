<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="牛牛决斗">
</p>

<h1 align="center">牛牛决斗 duel</h1>

<p align="center">泰拉风味多幕决斗，带剧情事件、抢答和八角笼玩法。</p>

<p align="center">
  <img alt="官方插件" src="https://img.shields.io/badge/%E5%AE%98%E6%96%B9%E6%8F%92%E4%BB%B6-FE7D37">
  <img alt="WebUI 插件商店" src="https://img.shields.io/badge/WebUI-%E6%8F%92%E4%BB%B6%E5%95%86%E5%BA%97-4EA94B">
  <img alt="安装命令" src="https://img.shields.io/badge/uv%20run%20pallas%20ext%20install%20pallas--plugin--duel-586069">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

可在控制台插件商店安装，或执行 `uv run pallas ext install pallas-plugin-duel`。

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛决斗 @对手 [N幕\|N回合]` | 群内 | 向指定对手发起决斗。 |
| `牛牛决斗 @牛A @牛B` | 群内 | 让两只牛牛直接开打。 |
| `八角笼牛 [N幕\|N回合]` | 群内 | 随机抽两只在线牛牛开战。 |
| `按幕面提示回复干员名或关键词` | 群内 | 在抢答环节限时作答。 |
| `决斗事件重载` | 群内 | 重新加载剧情事件资源。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `duel.duel` | 所有人 |
| `duel.cage` | 所有人 |
| `duel.reload_events` | 群管/群主 |

## 配置项

> 可在控制台对应插件页中修改。

对战流程、资源与玩法相关配置以扩展仓 `pallas-plugin-duel` 的 `config.py` 为准；安装后可在控制台对应插件页查看可改字段。

干员头像等资源：

```bash
uv run python scripts/fetch_arknights_duel_data.py
```

## 排障

| 现象 | 处理 |
| --- | --- |
| 无法开战 | 同群同时仅一场；检查 @ 与牛牛是否在线 |
| 乱入无头像 | 执行上方资源脚本 |

## 实现

源码位置：扩展仓 `pallas-plugin-duel`（插件本体不在主仓 `packages/` 内）

关键文件：

- 扩展仓 `src/pallas_plugin_duel/__init__.py`：注册命令、权限与帮助元数据。
- 扩展仓 `src/pallas_plugin_duel/` 下的玩法逻辑文件：处理决斗流程、抢答、事件与结算。
- [`scripts/fetch_arknights_duel_data.py`](../../scripts/fetch_arknights_duel_data.py)：拉取干员头像等静态资源。

实现要点：

- 决斗是多幕流程，命令入口只负责开局，后续回合、事件和抢答由扩展内部状态机推进。
- 八角笼玩法会从当前在线牛牛中抽取参战对象，所以是否在线会直接影响可玩性。
- 剧情事件与头像资源是分开的，本体逻辑可运行，但缺资源时部分展示会降级或缺图。

## 相关链接

- [命令权限说明](../common/cmd_perm/README.md)
- [安装插件](../guide/install-plugins.md)
- [牛牛决斗插件仓库](https://github.com/TogetsuDo/pallas-plugin-duel)
