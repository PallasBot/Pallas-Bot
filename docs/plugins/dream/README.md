<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="牛牛做梦">
</p>

<h1 align="center">牛牛做梦 dream</h1>

<p align="center">让牛牛进入做梦状态，接收梦话、漂流和历史内容。</p>

<p align="center">
  <img alt="官方插件" src="https://img.shields.io/badge/%E5%AE%98%E6%96%B9%E6%8F%92%E4%BB%B6-FE7D37">
  <img alt="控制台插件商店" src="https://img.shields.io/badge/%E6%8E%A7%E5%88%B6%E5%8F%B0-%E6%8F%92%E4%BB%B6%E5%95%86%E5%BA%97-4EA94B">
  <img alt="安装命令" src="https://img.shields.io/badge/uv%20run%20pallas%20ext%20install%20pallas--plugin--dream-586069">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

可在控制台插件商店安装，或执行 `uv run pallas ext install pallas-plugin-dream`。

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛做梦` | 群内 | 进入做梦状态，持续约 5 到 15 分钟。 |
| `牛牛醒梦` / `牛牛别做梦` | 群内 | 结束做梦。 |
| `牛牛醒一醒` | 群内 | 醒酒时一并结束做梦。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `dream.ban_cleanup` | 群管或号主 |

无独立命令权限的日常做梦口令可不在本节重复展开。

## 配置项

> 可在控制台对应插件页中修改。

牛牛做梦的常用配置包括梦话间隔、保留天数等，具体字段以扩展仓 `config.py` 为准。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无梦话 | 先确认已发送 `牛牛做梦`；若其他群没人做梦，也不会收到漂流。 |
| 内容过多 | 调小保留天数，或清理梦库。 |

## 实现

源码位置：官方插件扩展仓 `pallas-plugin-dream`

关键文件：

- 扩展仓 `src/pallas_plugin_dream/__init__.py`：注册命令与元数据。
- 扩展仓核心处理文件：负责做梦状态、梦话推送与漂流逻辑。
- 主仓 `packages/drink/`：醉酒状态会影响做梦频率与表现。

实现要点：

- 做梦是一个持续状态，不是单次命令执行完就结束。
- 梦话来源可能是历史内容、其他群漂流或图片，因此不同群的体验会互相影响。
- 与喝酒状态存在联动，醉酒时梦话会更活跃。

## 相关链接

- [命令权限说明](../common/cmd_perm/README.md)
- [喝酒插件说明](../drink/README.md)
- [牛牛做梦插件仓库](https://github.com/TogetsuDo/pallas-plugin-dream)
