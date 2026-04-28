# pallas_protocol

`pallas_protocol` 用来在 Bot 内管理 NapCat 实例（创建、启动、停止、重启、看日志、改配置）。


- 运行模式：`Docker` / `AppImage` / `Shell`
- Docker 镜像版本
- 下载平台
- 是否跟随 Bot 生命周期

这些都可以直接在管理页的「更新/下载」页面里设置，然后点击「保存设置」。

## 推荐使用方式

推荐顺序如下：

1. 启动 Bot
2. 打开协议端管理页
3. 进入「更新/下载」
4. 选择运行模式、镜像版本等
5. 点击「保存设置」
6. 再去创建或启动实例

这些页面设置会保存到：

- `data/pallas_protocol/runtime_profile.json`

## 真正可能需要放进 `.env` 的，通常只有少数全局项

```env
PALLAS_PROTOCOL_ENABLED=true
PALLAS_PROTOCOL_WEBUI_ENABLED=true
PALLAS_PROTOCOL_TOKEN=你的管理口令
```

说明：

- `PALLAS_PROTOCOL_ENABLED`：是否启用插件
- `PALLAS_PROTOCOL_WEBUI_ENABLED`：是否启用管理页
- `PALLAS_PROTOCOL_TOKEN`：如果你希望给管理页/API 加访问口令，就设置它

很多情况下，默认值就已经够用，连这几项都不一定需要额外改。

## 常见场景怎么配

### 场景 A：Linux + Docker（最省心）

说明：

- 镜像版本建议在管理页里选好并保存（会写入 `data/pallas_protocol/runtime_profile.json`）
- 如果 Bot 不在宿主机本机，才可能需要设置 `PALLAS_PROTOCOL_DOCKER_ONEBOT_HOST`
- 如果不设置，常见默认值是 `172.17.0.1`

### 场景 B：Linux + AppImage（不用 Docker）

说明：

- 一般直接在管理页选择 `AppImage` 并保存即可
- 不想自动下载时，可改为手动下载，然后设置 `PALLAS_PROTOCOL_PROGRAM_DIR`

### 场景 C：Windows

通常无需额外配置，按管理页下载并创建实例即可；如有自定义运行目录，再设置：

```env
PALLAS_PROTOCOL_PROGRAM_DIR=你的运行时目录
```

## WS 地址到底从哪来

实例里的 WS 留空时，会按以下顺序解析：

1. `PALLAS_PROTOCOL_ONEBOT_WS_URL`（完整地址，优先级最高）
2. `PALLAS_PROTOCOL_ONEBOT_WS_HOST` + `PALLAS_PROTOCOL_ONEBOT_WS_PORT` + `PALLAS_PROTOCOL_ONEBOT_WS_PATH`
3. 全局回退：`HOST` / `PORT` / `ACCESS_TOKEN`（以及驱动配置）

## 哪些情况才更像需要手改 `.env`

只有下面这些场景，更像是需要你手动配置：

- 你想给管理页/API 单独加口令：`PALLAS_PROTOCOL_TOKEN`
- 你想固定运行时目录：`PALLAS_PROTOCOL_PROGRAM_DIR`
- 你想让启动时缺失运行时就自动下载：`PALLAS_PROTOCOL_AUTO_DOWNLOAD_RUNTIME`
- 你是 Docker 部署，且容器访问 Bot 需要指定宿主机地址：`PALLAS_PROTOCOL_DOCKER_ONEBOT_HOST`
- 你想手动写死完整 WS 地址：`PALLAS_PROTOCOL_ONEBOT_WS_URL`

## 常见的进阶配置项

- `PALLAS_PROTOCOL_TOKEN`：管理页/API 鉴权
- `PALLAS_PROTOCOL_PROGRAM_DIR`：运行时目录（手动模式常用）
- `PALLAS_PROTOCOL_AUTO_DOWNLOAD_RUNTIME`：无运行时时自动下载
- `PALLAS_PROTOCOL_DOCKER_IMAGE`：Docker 模式镜像版本
- `PALLAS_PROTOCOL_DOCKER_ONEBOT_HOST`：容器访问 Bot 的地址
- `PALLAS_PROTOCOL_ONEBOT_WS_URL`：一条完整 WS 地址（最直接）

## 排障速查

- 创建/启动时报 `program_dir 为空`：先在「更新/下载」页下载运行时，或设置 `PALLAS_PROTOCOL_PROGRAM_DIR`
- Docker 启动失败并提示端口冲突：当前版本会自动换可用端口；若仍失败，检查是否有外部服务长期占用端口段
- 重启后镜像版本变回 `latest`：确认你在「更新/下载」页点过「保存设置」，并检查 `data/pallas_protocol/runtime_profile.json`
- 页面改了设置但没生效：确认右上角「保存设置」已点击（页面会显示“有未保存修改”提示）

## 数据目录

- 实例数据：`data/pallas_protocol/instances/<account_id>/`
- 运行模式与镜像偏好：`data/pallas_protocol/runtime_profile.json`

---

需要完整字段清单时，请查看 `src/plugins/pallas_protocol/config.py`。
