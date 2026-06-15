<div align="center">
  <img alt="LOGO" src="https://user-images.githubusercontent.com/18511905/195892994-c1a231ec-147a-4f98-ba75-137d89578247.png" width="360" height="270" />
  <h1>Pallas-Bot</h1>

  <p>我是来自米诺斯的祭司帕拉斯，会在罗德岛休息一段时间......</p>
  <p>虽然这么说，我渴望以美酒和戏剧被招待，更渴望走向战场。</p>

  <p>
    <a href="https://github.com/PallasBot/Pallas-Bot/issues">报告 Bug</a> ·
    <a href="https://github.com/PallasBot/Pallas-Bot/issues">提出新特性</a>
  </p>

</div>


<div align="center">

[![license](https://img.shields.io/badge/license-AGPL3.0-FE7D37)](./LICENSE)
[![python](https://img.shields.io/badge/Python-3.12%2B-blue)](https://www.python.org)
[![nonebot2](https://img.shields.io/badge/nonebot2-%3E%3D2.4.4-EA5252)](https://nonebot.dev/)
[![onebot](https://img.shields.io/badge/OneBot-v11-black?style=social&logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEAAAABABAMAAABYR2ztAAAAIVBMVEUAAAAAAAADAwMHBwceHh4UFBQNDQ0ZGRkoKCgvLy8iIiLWSdWYAAAAAXRSTlMAQObYZgAAAQVJREFUSMftlM0RgjAQhV+0ATYK6i1Xb+iMd0qgBEqgBEuwBOxU2QDKsjvojQPvkJ/ZL5sXkgWrFirK4MibYUdE3OR2nEpuKz1/q8CdNxNQgthZCXYVLjyoDQftaKuniHHWRnPh2GCUetR2/9HsMAXyUT4/3UHwtQT2AggSCGKeSAsFnxBIOuAggdh3AKTL7pDuCyABcMb0aQP7aM4AnAbc/wHwA5D2wDHTTe56gIIOUA/4YYV2e1sg713PXdZJAuncdZMAGkAukU9OAn40O849+0ornPwT93rphWF0mgAbauUrEOthlX8Zu7P5A6kZyKCJy75hhw1Mgr9RAUvX7A3csGqZegEdniCx30c3agAAAABJRU5ErkJggg==)](https://onebot.dev/)
[![stars](https://img.shields.io/github/stars/PallasBot/Pallas-Bot?style=social)](https://github.com/PallasBot/Pallas-Bot/stargazers)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

[![maa-remote](https://img.shields.io/badge/Feature-MAA%20%E8%BF%9C%E6%8E%A7-FE7D37)](https://PallasBot.github.io/Pallas-Bot-Docs/plugins/maa)
![learning-repeater](https://img.shields.io/badge/Feature-%E5%AD%A6%E4%B9%A0%E5%9E%8B%E5%A4%8D%E8%AF%BB-8A2BE2)
![plugin-system](https://img.shields.io/badge/Feature-%E6%8F%92%E4%BB%B6%E5%8C%96-00A3FF)
[![ai-chat-sing-tts](https://img.shields.io/badge/AI-Chat%26Sing%26TTS-6A5ACD)](https://github.com/PallasBot/Pallas-Bot-AI.git)
![database](https://img.shields.io/badge/Database-MongoDB%20%7C%20PostgreSQL-4EA94B)

[![tencent-qq](https://img.shields.io/badge/%E7%BE%A4-开发者群-red?style=logo=tencent-qq)](https://jq.qq.com/?_wv=1027&k=tlLDuWzc)
[![tencent-qq](https://img.shields.io/badge/%E7%BE%A4-拉牛牛-c73e7e?style=logo=tencent-qq)](#qq-群)
![community-deployments](https://img.shields.io/endpoint?url=https%3A%2F%2Fstats.pallasbot.top%2Fv1%2Fbadges%2Fdeployments-online)
![community-bots](https://img.shields.io/endpoint?url=https%3A%2F%2Fstats.pallasbot.top%2Fv1%2Fbadges%2Fbots-online)

</div>

<p align="center">面向群聊场景的学习型机器人：会复读、会整活、可管理、可扩展。</p>
<p align="center">基于 <b>NoneBot2</b> + <b>OneBot v11</b>，数据层 <b>MongoDB / PostgreSQL</b>，自带 Web 控制台与协议端管理；可选 <b>MAA</b> QQ 远控与 AI 扩展。</p>

<a href="https://next.ossinsight.io/widgets/official/analyze-repo-stars-history?repo_id=425810267" target="_blank" style="display: block" align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://next.ossinsight.io/widgets/official/analyze-repo-stars-history/thumbnail.png?repo_id=425810267&image_size=auto&color_scheme=dark" width="721" height="auto">
    <img alt="Star History of PallasBot/Pallas-Bot" src="https://next.ossinsight.io/widgets/official/analyze-repo-stars-history/thumbnail.png?repo_id=425810267&image_size=auto&color_scheme=light" width="721" height="auto">
  </picture>
</a>

> 喜欢牛牛，就给牛牛点个 [**⭐**](https://github.com/PallasBot/Pallas-Bot/stargazers) 吧！

## 🚀 快速开始

```bash
#获取代码
git clone https://github.com/PallasBot/Pallas-Bot.git

#进入目录
cd Pallas-Bot

# 安装依赖
pip install uv          # 安装 uv
uv sync                 # 安装依赖

# 主配置（首次部署）
cp config/pallas.example.toml config/pallas.toml
# 编辑 [bootstrap]：监听、SUPERUSERS、DB_BACKEND、MONGO_* 或 PG_*

# 开始运行（单进程）
uv run nb run
```

浏览器打开 `http://<主机>:8088/pallas/`，使用启动日志中的口令登录。

<a id="文档"></a>
## 📖 文档

部署、配置、插件、迁移与排障等完整说明见在线文档站；全网在线牛牛与社区概览见社区中心主站。

<table>
<tr>
<td><strong>文档</strong></td>
<td><a href="https://PallasBot.github.io/Pallas-Bot-Docs/"><img src="https://img.shields.io/badge/docs%20on-GitHub.Pages-FE7D37" alt="docs on GitHub Pages"></a></td>
</tr>
<tr>
<td><strong>社区中心主站</strong></td>
<td><a href="https://stats.pallasbot.top/"><img src="https://img.shields.io/badge/社区中心-stats.pallasbot.top-FE7D37" alt="Pallas 社区中心"></a></td>
</tr>
</table>

<a id="开发与贡献指南"></a>
## 💻 开发与贡献指南

欢迎通过 [Issues](https://github.com/PallasBot/Pallas-Bot/issues) / PR 参与改进。参与前请阅读 [贡献指南](CONTRIBUTING.md) 与仓库根目录 [AGENTS.md](AGENTS.md)。

<a id="社区与支持"></a>
## 🤝 社区与支持


<a id="qq-群"></a>
### 💬 QQ 群

- #### 开发者
  - [`牛牛听话!`](https://qm.qq.com/q/yIiAajYwms)
- #### 拉牛牛
  - [`西海福牛养殖基地`](https://qm.qq.com/q/5GjZ2xHeb6)
  - [`牛牛工坊`](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=snSe5PkcmHZrD0OA5Wzl2RAnM-qoAMUc&authKey=T%2FQlcyy31oE7YyMDMd7Yys7utl5a9jP84VYgnknra8Knsq3BhEy5TrwiWK7rG8j6&noverify=0&group_code=1043301356)
- #### 闲聊
  - [`西海福牛养殖学院`](https://qm.qq.com/q/8P)
  - [`丽丽玛玛玛?`](https://qm.qq.com/q/Qgc6ir7Jk)

<a id="打赏"></a>
### 💝 打赏

请作者喝杯咖啡吧（请备注牛牛项目，感谢你的支持 ✿✿ヽ(°▽°)ノ✿）：

<a href="https://afdian.com/a/misteo">
  <img width="200" src="https://pic1.afdiancdn.com/static/img/welcome/button-sponsorme.png">
</a>

<a id="致谢"></a>
## 🙏 致谢

- [**MaaAssistantArknights**](https://github.com/MaaAssistantArknights/MaaAssistantArknights.git)：明日方舟长草助手 MAA ；本项目的远控能力基于其[远程控制协议](https://docs.maa.plus/zh-cn/protocol/remote-control-schema.html)实现
- [**NoneBot2**](https://github.com/nonebot/nonebot2)：跨平台 Python 异步聊天机器人框架
- [**jieba_next**](https://github.com/mxcoras/jieba-next)：Use Rust to Speed up jieba 高效、现代的中文分词库
- [**beanie**](https://github.com/BeanieODM/beanie)：Asynchronous Python ODM for MongoDB
- [**NapCat**](https://github.com/NapNeko/NapCatQQ)：现代化的基于 NTQQ 的 Bot 协议端实现
- [**zhenxun_bot**](https://github.com/zhenxun-org/zhenxun_bot.git)：非常可爱的绪山真寻Bot
- [**Amiya-bot**](https://github.com/AmiyaBot/Amiya-Bot.git)：基于 AmiyaBot 框架的 QQ 聊天机器人
- [**CustomMarkdownImage**](https://github.com/Monody-S/CustomMarkdownImage.git)：基于pillow的可自定义markdown渲染器

<a href="https://next.ossinsight.io/widgets/official/analyze-repo-pushes-and-commits-per-month?repo_id=425810267" target="_blank" style="display: block" align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://next.ossinsight.io/widgets/official/analyze-repo-pushes-and-commits-per-month/thumbnail.png?repo_id=425810267&image_size=auto&color_scheme=dark" width="721" height="auto">
    <img alt="Pushes and Commits of PallasBot/Pallas-Bot" src="https://next.ossinsight.io/widgets/official/analyze-repo-pushes-and-commits-per-month/thumbnail.png?repo_id=425810267&image_size=auto&color_scheme=light" width="721" height="auto">
  </picture>
</a>

<a href="https://next.ossinsight.io/widgets/official/compose-recent-active-contributors?repo_id=425810267&limit=30" target="_blank" style="display: block" align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://next.ossinsight.io/widgets/official/compose-recent-active-contributors/thumbnail.png?repo_id=425810267&limit=30&image_size=auto&color_scheme=dark" width="655" height="auto">
    <img alt="Active Contributors of PallasBot/Pallas-Bot - Last 28 days" src="https://next.ossinsight.io/widgets/official/compose-recent-active-contributors/thumbnail.png?repo_id=425810267&limit=30&image_size=auto&color_scheme=light" width="655" height="auto">
  </picture>
</a>

## 👥 贡献者

感谢各位大佬！

[![Contributors](https://contributors-img.web.app/image?repo=PallasBot/Pallas-Bot)](https://github.com/PallasBot/Pallas-Bot/graphs/contributors)

<a id="许可证"></a>
## 📄 许可证

本项目采用 `GNU Affero General Public License v3.0`（AGPL-3.0）许可证，详见 [LICENSE](LICENSE)。
