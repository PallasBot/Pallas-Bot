# Docker 部署

> 导航：[`README`](../README.md) · [`标准部署`](Deployment.md) · [`3.0 迁移`](Migration-v3.md) · [`FAQ`](FAQ.md)

如果你不想自己配置环境，可以使用 `Docker Compose` 一键部署已构建好的镜像。镜像中集成了 `Pallas-Bot` 运行所需要的所有环境并经过充分测试，你只需要安装 `Docker` 和 `Docker Compose`（较新版本的 `Docker` 已集成 `Compose` 插件）即可。`Pallas-Bot` 提供的镜像支持 `amd64` 与 `arm64` 架构。

## 准备工作

### 安装 `Docker` 与 `Docker Compose`

- [Windows Docker Desktop 安装](https://docs.docker.com/desktop/install/windows-install/) ，推荐使用基于 [WSL 2](https://learn.microsoft.com/zh-cn/windows/wsl/install) 的 `Docker CE`。

- [Linux Docker 安装](https://docs.docker.com/engine/install/ubuntu/)，推荐使用 `curl -fsSL https://get.docker.com | bash -s docker --mirror Aliyun` 命令一键安装。

- 较新版本的 `Docker` 已集成 `Compose` 插件，可以通过 `docker compose version` 查看 `Compose` 插件是否已安装。

- 如果你需要为之前已经安装过的老版本 `Docker` 安装 `Docker Compose` 插件，推荐 [单独安装 Docker Compose](https://docs.docker.com/compose/install/other/)。Windows 用户可以直接在 `Docker Desktop` 中启用 `Docker Compose`（`Settings -> General -> Use Docker Compose V2`）。

- （可选）Linux Rootless 模式
  如果你希望以非 root 用户运行 Docker，可以参考 [Docker Rootless 模式](https://docs.docker.com/engine/security/rootless/)。
  如果你使用的是一键安装方式，可以使用以下命令配置 Rootless 模式：

    ```bash
    sudo apt-get install -y uidmap
    dockerd-rootless-setuptool.sh install
    ```

如果你使用的是 Linux 一键安装方式，安装脚本会为你自动配置 Docker 镜像加速。其他安装方式推荐手动[配置镜像加速](https://www.runoob.com/docker/docker-mirror-acceleration.html)。

### 配置 docker-compose.yml

1. 复制一份 [docker-compose.yml](../docker-compose.yml) 文件到本地单独的目录并按需修改 `volumes` 的路径：

    ```yml
    ...
    volumes:
    # 根据需求修改冒号左边路径，推荐保持默认，即在当前目录下自动创建映射目录
    # Windows 用户如需使用绝对路径，请修改冒号左边为 D:\Pallas-Bot 这样的路径
    # 建议与 docker-compose.yml 在同一目录下
        - ./pallas-bot/resource/:/app/resource
        - ./pallas-bot/.env:/app/.env
    ...
    volumes:
    # mongodb 数据与日志存储路径，修改方法同上
      - ./mongo/data:/data/db
      - ./mongo/logs:/var/log/mongodb
    ...
    # NapCat 数据与配置存储路径，修改方法同上
    volumes:
      - ./NapCat/QQ:/app/.config/QQ
      - ./NapCat/config:/app/napcat/config
    ```

2. 默认提供的 `docker-compose.yml` 中包含了 `NapCat` 作为 QQ 客户端，你可以根据需要将其替换为 [Lagrange](https://github.com/LagrangeDev/Lagrange.Core/blob/master/Docker_zh.md) 或其他支持 `Docker` 部署的客户端。如果你想手动部署，可将 `NapCat` service 删除。

3. （可选）如有需要，在你映射的目录下复制一份 [`.env`](../.env) 文件，并根据需要填写相关参数。具体请参考 [`.env`](../.env) 文件中的注释。

4. 3.0 同时支持 `MongoDB` 与 `PostgreSQL` 数据后端；如果你是从历史数据升级，请先参考 [`3.0 迁移指南`](Migration-v3.md)。

## 启动与登录牛牛

### 启动牛牛

一键启动！

```bash
# Linux root 用户在 docker-compose.yml 所在目录下执行
NAPCAT_UID=$(id -u) NAPCAT_GID=$(id -g) docker compose up -d
# Windows 请使用 powershell 直接执行，无需管理员权限，请不要在 wsl 内执行
```

你也可以通过 `id -u` 和 `id -g` 手动获取并修改 docker-compose.yml 中的 `NAPCAT_UID` 与 `NAPCAT_GID`，然后直接使用以下命令启动：

```bash
docker compose up -d
```

和手动部署一样，牛牛也会自动下载语音文件到你映射的 `resource/voices/` 目录下。

### 登录账号

浏览器访问 `http://<宿主机ip>:6099/webui`，默认 token 为 `napcat`。

扫码登录后，按下面步骤配置：

1. 点击 `网络配置` -> `新建` -> `WebSocket 客户端`
2. 打开 `启用` 开关，名称随便填（例如 `PallasBot`）
3. 在 `URL` 栏填写 `pallasbot:8088/onebot/v11/ws`，协议选择 `ws`
4. 点击保存，看到连接成功后就表示 `Pallas-Bot` 已接通

### 查看日志

在 `docker-compose.yml` 的目录下通过 `docker compose logs -f` 查看实时日志，启动完成后就可以访问 `NapCat` 后台并登陆账号了。

### 访问 3.0 控制台

容器启动后可访问：

- 控制台页面：`http://<宿主机ip>:8088/pallas/`
- 控制台接口基址：`http://<宿主机ip>:8088/pallas/api`

如果你在 `docker-compose.yml` 里修改了 `pallasbot` 的端口映射，请按实际端口访问。

## 后续更新

```bash
# Linux root 用户在 docker-compose.yml 所在目录下执行
docker compose down     # 停止容器
docker compose pull     # 拉取最新镜像
docker compose up -d    # 重新启动容器
# Windows 请使用 powershell 直接执行，无需管理员权限，请不要在 wsl 内执行
```
