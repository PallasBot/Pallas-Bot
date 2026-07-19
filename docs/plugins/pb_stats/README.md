<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="在线统计">
</p>

<h1 align="center">在线统计 pb_stats</h1>

<p align="center">把本实例的在线统计信息同步到社区页面。</p>

<p align="center">
  <img alt="本体 core" src="https://img.shields.io/badge/%E6%9C%AC%E4%BD%93%20core-4B5563">
  <img alt="默认加载" src="https://img.shields.io/badge/%E9%BB%98%E8%AE%A4%E5%8A%A0%E8%BD%BD-4EA94B">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

默认加载，无需单独安装。

## 怎么使用

无群内用户口令。这个插件会在后台持续同步在线统计信息。

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

无。

## 配置项

> 可在控制台对应插件页中修改。

在线统计配置在控制台的“在线统计与社区主站”相关区域，也可通过 `config/pallas.toml` 的对应段落管理。默认开启。

## 排障

| 现象 | 处理 |
| --- | --- |
| 社区页看不到本实例 | 检查是否关闭了统计、网络是否可达、上报是否成功。 |
| 数据延迟 | 后台上报是周期性的，不会每次状态变化都立刻刷新。 |

## 实现

源码位置：

- 插件壳：[`packages/pb_stats/`](../../packages/pb_stats/)
- 业务逻辑：[`pallas/product/community_stats/`](../../pallas/product/community_stats/)

关键文件：

- [`packages/pb_stats/__init__.py`](../../packages/pb_stats/__init__.py)：注册在线统计元数据。
- [`packages/pb_stats/startup.py`](../../packages/pb_stats/startup.py)：启动后台上报流程。
- [`packages/pb_stats/config.py`](../../packages/pb_stats/config.py)：定义在线统计相关配置。

实现要点：

- 这是后台上报能力，不会直接响应群聊命令。
- 主仓社区页、控制台统计页和部署心跳都依赖这条同步链路。
- 旧的 `community_stats` 已经内核化到 `pb_stats`，不再作为独立插件维护。

## 相关链接

- [在线统计与社区主站](../../common/community_stats.md)
- [Web 控制台](../pb_webui/README.md)
