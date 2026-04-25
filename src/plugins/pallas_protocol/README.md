# pallas_protocol

`pallas_protocol` 用于管理 NapCat 协议端实例，包括：

- 多账号运行与状态管理
- 协议端管理页与操作 API
- 运行时（zip/AppImage）下载、安装、重扫

## 运行模式概览

- Windows：默认走 OneKey zip（`NapCat.Shell.Windows.OneKey.zip`）
- Linux：默认走 AppImage（按架构自动偏好）
- Linux 可选 Docker 模式（`pallas_protocol_linux_use_docker=true`）
- 非 Linux 且非 Windows：默认走 `NapCat.Shell.zip`

## 运行时下载策略（当前实现）

当触发运行时下载时，逻辑如下：

1. 若 `pallas_protocol_release_asset` 是完整 URL（http/https），直接下载。
2. 否则按仓库候选 + tag 候选解析 release 资产列表：
   - repo：优先配置仓库；Linux 下会自动补充候选仓库回退
   - tag：优先配置 tag，再回退 latest
3. 资产选择顺序：
   - 先精确匹配 `release_asset`
   - 再按后缀匹配（`.AppImage` / `.zip`）
   - 再按架构 token 匹配（如 `x86_64/amd64`、`aarch64/arm64`）
   - 最后兜底选第一个可用资产
4. 候选下载地址逐个尝试，直到成功；全部失败时报错并附候选失败信息。

这样做的原因：减少 Linux/多平台在 `.env` 中写死资产名与 tag 的维护负担。

## 主要配置项

基础控制：

- `pallas_protocol_enabled`：启用插件
- `pallas_protocol_webui_enabled`：启用协议管理页
- `pallas_protocol_web_implementation` / `pallas_protocol_webui_path`：管理页挂载路径
- `pallas_protocol_token`：协议管理页鉴权 token
- `pallas_protocol_instances_root`：实例目录根路径
- `pallas_protocol_auto_download_runtime`：启动时缺失运行时是否自动下载

下载相关：

- `pallas_protocol_github_repo`：默认仓库（平台相关默认值）
- `pallas_protocol_release_tag`：版本标签（空=latest）
- `pallas_protocol_release_asset`：资产名（支持 `auto`/`latest` 语义，或直接 URL）

Linux 相关：

- `pallas_protocol_linux_use_docker`
- `pallas_protocol_linux_use_xvfb`
- `pallas_protocol_linux_xvfb_command`
- `pallas_protocol_linux_xvfb_args`
- `pallas_protocol_linux_appimage_args`
- `pallas_protocol_docker_image`
- `pallas_protocol_docker_onebot_host`
- `pallas_protocol_docker_internal_webui_port`

OneBot 连接相关：

- `pallas_protocol_onebot_client_name`

说明：`host`/`port`/`access_token` 默认会回落读取全局环境变量
`HOST`、`PORT`、`ACCESS_TOKEN`（以及驱动配置），通常不需要额外重复配置
插件内不再提供单独的 `pallas_protocol_onebot_host`、`pallas_protocol_onebot_port`、`pallas_protocol_access_token` 配置项。

## 推荐配置（尽量少硬编码）

### Linux（AppImage，自动选择）

```env
PALLAS_PROTOCOL_GITHUB_REPO=
PALLAS_PROTOCOL_RELEASE_TAG=
PALLAS_PROTOCOL_RELEASE_ASSET=auto
```

### Windows（OneKey，自动选择）

```env
PALLAS_PROTOCOL_GITHUB_REPO=
PALLAS_PROTOCOL_RELEASE_TAG=
PALLAS_PROTOCOL_RELEASE_ASSET=auto
```

如需锁定版本，只填 `PALLAS_PROTOCOL_RELEASE_TAG` 即可；如需强制某资产，再填 `PALLAS_PROTOCOL_RELEASE_ASSET`。

