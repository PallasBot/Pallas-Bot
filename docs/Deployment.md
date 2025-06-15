# Pallas-Bot 的部署简单教程

快来部署属于你自己的牛牛吧 (｡･∀･)ﾉﾞ

## 看前提示

- 你需要一个额外的 QQ 小号，一台自己的 `电脑` 或 `服务器`，不推荐用大号进行部署
- 你自己部署的牛牛与其他牛牛数据并不互通，是一张白纸，需要从头调教
- 牛牛支持使用 Docker Compose 一键部署，可以参考 [Docker 部署](DockerDeployment.md)。

## 基本环境配置

1. 下载安装 [git](https://git-scm.com/downloads)，这是一个版本控制工具，可以用来方便的下载、更新牛牛的源码。
2. 下载牛牛源码

    在你想放数据的文件夹里，Shift + 鼠标右键，打开 Powershell 窗口，输入命令

    ```bash
    git clone https://github.com/PallasBot/Pallas-Bot.git
    ```

    受限于国内网络环境，请留意命令是否执行成功，若一直失败可以挂上代理。

3. 下载安装 [Python](https://www.python.org/downloads/)，推荐安装 3.12 以上版本，Windows 用户请确保安装时勾选了 “Add Python to PATH” 选项。

    如果你本地已有 Python 环境可以忽略本条，下方的 `uv` 会自动安装牛牛支持的 Python 版本。

4. 下载安装 [pipx](https://pypa.github.io/pipx/installation/)，用于安装 Python 应用（可执行文件）

    ```bash
    python -m pip install --user pipx
    python -m pipx ensurepath
    ```

5. 使用 `pipx` 安装 [uv](https://docs.astral.sh/uv/getting-started/installation/), 这是一个现代且高效的 Python 包和项目管理工具

    ```bash
    pipx install uv
    ```

    如果你本地已有 uv 环境可以忽略本条，下方的 `uv` 会自动安装牛牛支持的 Python 版本。

## 项目环境配置

1. 安装依赖

    ```bash
    cd Pallas-Bot # 进入项目目录
    uv sync
    ```

2. 安装并启动 Mongodb （这是启动核心功能所必须的）

    - [Windows 平台安装 MongoDB](https://www.runoob.com/mongodb/mongodb-window-install.html)
    - [Linux 平台安装 MongoDB](https://www.runoob.com/mongodb/mongodb-linux-install.html)

    只需要确认 Mongodb 启动即可，后面的部分会由 Pallas-Bot 自动完成

3. 配置 FFmpeg （如果不希望牛牛发送语音，可以跳过这一步）

    - [安装 FFmpeg](https://docs.go-cqhttp.org/guide/quick_start.html#%E5%AE%89%E8%A3%85-ffmpeg)
    - 下载 [牛牛语音文件](https://huggingface.co/pallasbot/Pallas-Bot/blob/main/voices.zip)，解压放到 `resource/` 文件夹下，参考 [path_structure.txt](../resource/voices/path_structure.txt)

4. 使用 `jieba-fast` 分词库

    项目默认安装 `jieba`， 加群较多、需要处理消息量大的用户可以自行安装 `jieba-fast`，以提升分词速度（若群较少也可跳过这一步）  

    ```bash
    uv sync --extra perf
    ```

    若安装失败，在 Windows 上可能需要额外安装 `Visual Studio`，Linux 上需要 `build-essential`  
    注：项目将优先尝试导入 `jieba-fast` 库，如果导入失败则使用 `jieba` 库，无需手动修改代码

5. 安装并配置 NapCat

    若使用 `NapCat` 作为 QQ 客户端，可支持戳一戳功能。具体部署方法参照 [NapCat](https://napneko.github.io/) 官方步骤。
    在 NapCat 配置文件中使用反向 WebSocket (NapCat作为WebSocket客户端角色) 连接牛牛

    ```bash
    ws://localhost:8088/onebot/v11/ws
    ```

## 启动 Pallas-Bot

```bash
cd Pallas-Bot # 进入项目目录
uv run nb run        # 运行
```

**注意！请不要关闭这个命令行窗口！这会导致 Pallas-Bot 停止运行！**
Linux 用户推荐使用 [termux](https://termux.dev/) 或 [GNU Screen](https://zhuanlan.zhihu.com/p/405968623) 来保持 Pallas-Bot 在后台运行。

## 后续更新

如果牛牛出了新功能你想要使用，同样在项目目录下打开 Powershell，执行命令后重新运行牛牛即可

```bash
git pull origin master --autostash
```

## AI 功能

至此，你已经完成了牛牛基础功能的配置，包括复读、轮盘、夺舍、基本的酒后乱讲话等所有非 AI 功能  
（AI 功能目前包括 唱歌、酒后闲聊、酒后 TTS 说话）  

AI 功能均对设备硬件要求较高（要么有一块 6G 显存或更高的英伟达显卡，要么可能占满 CPU 且吃 10G 以上内存）  
若设备性能不足，或对额外的 AI 功能不感兴趣，可以跳过这部分内容。

配置 AI 功能请移步单独的 AI 功能服务端 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)

## 开发者群

QQ 群: [牛牛听话！](https://jq.qq.com/?_wv=1027&k=tlLDuWzc)  
欢迎加入~
