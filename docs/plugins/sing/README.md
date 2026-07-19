<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="牛牛唱歌">
</p>

<h1 align="center">牛牛唱歌 sing</h1>

<p align="center">智能翻唱、续唱、点歌与查歌名。</p>

<p align="center">
  <img alt="官方插件" src="https://img.shields.io/badge/%E5%AE%98%E6%96%B9%E6%8F%92%E4%BB%B6-FE7D37">
  <img alt="WebUI 插件商店" src="https://img.shields.io/badge/WebUI-%E6%8F%92%E4%BB%B6%E5%95%86%E5%BA%97-4EA94B">
  <img alt="安装命令" src="https://img.shields.io/badge/uv%20run%20pallas%20ext%20install%20pallas--plugin--ai--media-586069">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

可在控制台插件商店安装，或执行 `uv run pallas ext install pallas-plugin-ai-media`。使用前还需要部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)。

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛唱歌 歌曲名 [key=±N]` | 群内 | 让牛牛翻唱指定歌曲，可附带升降调参数。 |
| `牛牛继续唱` / `牛牛接着唱` | 群内 | 续唱上一首歌。 |
| `牛牛点歌 歌曲名` | 群内 | 播放网易云原曲。 |
| `牛牛什么歌` / `牛牛哪首歌` | 群内 | 查询当前播放曲目。 |
| `网易云登录` / `网易云登出` | 私聊 | 维护网易云账号登录状态。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

| 命令 ID | 默认等级 | 说明 |
| --- | --- | --- |
| `sing.sing` | 所有人 | 牛牛唱歌 / 牛牛继续唱 |
| `sing.play` | 所有人 | 牛牛唱歌（随机，无歌名） |
| `sing.request_song` | 所有人 | 牛牛点歌 |
| `sing.song_title` | 所有人 | 牛牛什么歌 |
| `sing.ncm_login` | 仅超管 | 网易云登录 |
| `sing.ncm_logout` | 仅超管 | 网易云登出 |

## 配置项

> 可在控制台对应插件页中修改。

主要在控制台的插件页和 **通用配置 → 外部服务地址** 中配置唱歌服务地址。

## 排障

| 现象 | 处理 |
| --- | --- |
| 没有返回语音 | 先确认 AI 服务在线，再发送 `牛牛连通` 测唱歌服务。 |
| 点歌失败 | 检查网易云账号是否已登录。 |

## 实现

源码位置：`pallas-plugin-ai-media` 扩展仓中的 `sing` 插件目录

关键文件：

- 扩展仓 `sing` 插件的 `__init__.py`：注册命令、权限和帮助文案。
- 扩展仓 `sing` 相关命令处理文件：负责翻唱、续唱、点歌和查歌名流程。
- 主仓 AI 服务连通性相关文档与能力：用于定位服务地址、检查接口是否可用。

实现要点：

- 翻唱与续唱依赖外部 AI 服务生成语音，Bot 侧主要负责收集口令参数并回传音频结果。
- `点歌` 与 `查歌名` 依赖网易云侧能力，所以服务在线不代表一定能点歌，还要看登录状态。
- 这个插件和 `chat` 共用 `pallas-plugin-ai-media` 扩展包，但命令权限、触发方式和故障定位要分别看。

## 相关链接

- [命令权限说明](../common/cmd_perm/README.md)
- [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)
- [牛牛唱歌插件仓库](https://github.com/TogetsuDo/pallas-plugin-ai-media)
