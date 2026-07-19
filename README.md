<div align="center">
  <img alt="Pallas-Bot" src="docs/plugins/assets/brand-avatar.png" width="220" height="220" />
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

![learning-repeater](https://img.shields.io/badge/Core-%E5%AD%A6%E4%B9%A0%E5%9E%8B%E5%A4%8D%E8%AF%BB-8A2BE2)
![plugin-system](https://img.shields.io/badge/Feature-%E6%8F%92%E4%BB%B6%E5%8C%96-00A3FF)
[![maa-remote](https://img.shields.io/badge/Feature-MAA%20%E8%BF%9C%E6%8E%A7-FE7D37)](https://PallasBot.github.io/Pallas-Bot-Docs/plugins/maa)
[![ai-chat-sing-tts](https://img.shields.io/badge/AI-Chat%26Sing%26TTS-6A5ACD)](https://github.com/PallasBot/Pallas-Bot-AI.git)
![database](https://img.shields.io/badge/Database-PostgreSQL%20%28default%29-4EA94B)

[![tencent-qq](https://img.shields.io/badge/%E7%BE%A4-开发者群-red?style=flat&logo=tencent-qq)](https://qm.qq.com/q/yIiAajYwms)
[![tencent-qq](https://img.shields.io/badge/%E7%BE%A4-拉牛牛-c73e7e?style=flat&logo=tencent-qq)](#qq-群)
![community-deployments](https://img.shields.io/endpoint?url=https%3A%2F%2Fstats.pallasbot.top%2Fv1%2Fbadges%2Fdeployments-online)
![community-bots](https://img.shields.io/endpoint?url=https%3A%2F%2Fstats.pallasbot.top%2Fv1%2Fbadges%2Fbots-online)

</div>

<p align="center"><b>牛牛就是复读机</b>——群友说什么牛牛就说什么。</p>

<a href="https://next.ossinsight.io/widgets/official/analyze-repo-stars-history?repo_id=425810267" target="_blank" style="display: block" align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://next.ossinsight.io/widgets/official/analyze-repo-stars-history/thumbnail.png?repo_id=425810267&image_size=auto&color_scheme=dark" width="721" height="auto">
    <img alt="Star History of PallasBot/Pallas-Bot" src="https://next.ossinsight.io/widgets/official/analyze-repo-stars-history/thumbnail.png?repo_id=425810267&image_size=auto&color_scheme=light" width="721" height="auto">
  </picture>
</a>

> 喜欢牛牛，就给牛牛点个 [**⭐**](https://github.com/PallasBot/Pallas-Bot/stargazers) 吧！

## 🚀 快速开始

```bash
# 获取代码
git clone https://github.com/PallasBot/Pallas-Bot.git
cd Pallas-Bot

# 安装依赖（推荐 uv）
pip install uv
uv sync

# 主配置（首次部署）
cp config/pallas.example.toml config/pallas.toml
# 编辑 [bootstrap]：监听、superusers、[bootstrap.postgres]

# 开始运行（单进程）
uv run pallas
```

浏览器打开 `http://<主机>:8088/pallas/`，使用启动日志中的口令登录。  
更完整的上手说明见文档站 [快速开始](https://PallasBot.github.io/Pallas-Bot-Docs/guide/quickstart)。

<a id="文档"></a>
## 📖 文档

部署、配置、插件、迁移与排障见在线文档站；全网在线牛牛与社区概览见社区中心。

<table>
<tr>
<td><strong>文档站</strong></td>
<td><a href="https://PallasBot.github.io/Pallas-Bot-Docs/"><img src="https://img.shields.io/badge/docs-GitHub%20Pages-FE7D37" alt="docs on GitHub Pages"></a></td>
</tr>
<tr>
<td><strong>快速开始</strong></td>
<td><a href="https://PallasBot.github.io/Pallas-Bot-Docs/guide/quickstart"><img src="https://img.shields.io/badge/guide-quickstart-8A2BE2" alt="quickstart"></a></td>
</tr>
<tr>
<td><strong>社区中心</strong></td>
<td><a href="https://stats.pallasbot.top/"><img src="https://img.shields.io/badge/社区中心-stats.pallasbot.top-FE7D37" alt="Pallas 社区中心"></a></td>
</tr>
</table>

<a id="开发与贡献指南"></a>
## 💻 开发与贡献指南

欢迎通过 [Issues](https://github.com/PallasBot/Pallas-Bot/issues) / PR 参与改进。参与前请阅读 [贡献指南](CONTRIBUTING.md) 与仓库根目录 [AGENTS.md](AGENTS.md)。

<table>
<tr>
<td><strong>公开进展 / 里程碑</strong></td>
<td><a href="https://pallasbot.notion.site/388943646d10813d9ff4dcb70d7c28e8?source=copy_link"><img src="https://img.shields.io/badge/Notion-%E7%94%A8%E6%88%B7%E5%85%AC%E5%BC%80%E8%BF%9B%E5%B1%95-000000?logo=notion" alt="用户公开进展"></a></td>
</tr>
<tr>
<td><strong>贡献指南</strong></td>
<td><a href="CONTRIBUTING.md"><img src="https://img.shields.io/badge/CONTRIBUTING-readme-00A3FF" alt="CONTRIBUTING"></a></td>
</tr>
<tr>
<td><strong>Agent 约定</strong></td>
<td><a href="AGENTS.md"><img src="https://img.shields.io/badge/AGENTS-md-4EA94B" alt="AGENTS.md"></a></td>
</tr>
</table>


<a id="社区与支持"></a>
## 🤝 社区与支持

<a id="qq-群"></a>
### 💬 QQ 群

<table>
<tr>
<td><strong>开发者</strong></td>
<td><a href="https://qm.qq.com/q/yIiAajYwms"><img src="https://img.shields.io/badge/群-牛牛听话!-red?logo=tencent-qq" alt="开发者群"></a></td>
</tr>
<tr>
<td><strong>拉牛牛</strong></td>
<td>
<a href="https://qm.qq.com/q/5GjZ2xHeb6"><img src="https://img.shields.io/badge/群-西海福牛养殖基地-c73e7e?logo=tencent-qq" alt="西海福牛养殖基地"></a>
<a href="http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=snSe5PkcmHZrD0OA5Wzl2RAnM-qoAMUc&authKey=T%2FQlcyy31oE7YyMDMd7Yys7utl5a9jP84VYgnknra8Knsq3BhEy5TrwiWK7rG8j6&noverify=0&group_code=1043301356"><img src="https://img.shields.io/badge/群-牛牛工坊-c73e7e?logo=tencent-qq" alt="牛牛工坊"></a>
</td>
</tr>
<tr>
<td><strong>闲聊</strong></td>
<td>
<a href="https://qm.qq.com/q/8P"><img src="https://img.shields.io/badge/群-西海福牛养殖学院-00A3FF?logo=tencent-qq" alt="西海福牛养殖学院"></a>
<a href="https://qm.qq.com/q/Qgc6ir7Jk"><img src="https://img.shields.io/badge/群-丽丽玛玛玛%3F-00A3FF?logo=tencent-qq" alt="丽丽玛玛玛"></a>
</td>
</tr>
<tr>
<td><strong>社区中心</strong></td>
<td><a href="https://stats.pallasbot.top/"><img src="https://img.shields.io/badge/社区中心-stats.pallasbot.top-FE7D37" alt="社区中心"></a></td>
</tr>
<tr>
<td><strong>在线部署 / 牛牛</strong></td>
<td>
<img src="https://img.shields.io/endpoint?url=https%3A%2F%2Fstats.pallasbot.top%2Fv1%2Fbadges%2Fdeployments-online" alt="deployments online">
<img src="https://img.shields.io/endpoint?url=https%3A%2F%2Fstats.pallasbot.top%2Fv1%2Fbadges%2Fbots-online" alt="bots online">
</td>
</tr>
</table>

<a id="打赏"></a>
### 💝 打赏

请作者喝杯咖啡吧（请备注牛牛项目，感谢你的支持 ✿✿ヽ(°▽°)ノ✿）：

<a href="https://afdian.com/a/misteo">
  <img width="200" src="https://pic1.afdiancdn.com/static/img/welcome/button-sponsorme.png" alt="爱发电">
</a>

<a id="致谢"></a>
## 🙏 致谢

- [**MaiBot**](https://github.com/Mai-with-u/MaiBot)：学习与陪伴向聊天机器人项目
- [**gsuid_core**](https://github.com/Genshin-bots/gsuid_core)：多 Bot 插件核心框架
- [**ArknightsGameData**](https://github.com/Kengxxiao/ArknightsGameData)：明日方舟游戏数据；决斗干员表与知识库由远端同步其 `zh_CN/gamedata`
- [**ArknightsGameResource**](https://github.com/yuanyan3060/ArknightsGameResource)：干员头像等资源；决斗 / 知识库头像由此拉取
- [**MaaAssistantArknights**](https://github.com/MaaAssistantArknights/MaaAssistantArknights.git)：明日方舟长草助手 MAA ；本项目的远控能力基于其[远程控制协议](https://docs.maa.plus/zh-cn/protocol/remote-control-schema.html)实现
- [**NoneBot2**](https://github.com/nonebot/nonebot2)：跨平台 Python 异步聊天机器人框架
- [**jieba_next**](https://github.com/mxcoras/jieba-next)：Use Rust to Speed up jieba 高效、现代的中文分词库
- [**beanie**](https://github.com/BeanieODM/beanie)：Asynchronous Python ODM for MongoDB
- [**NapCat**](https://github.com/NapNeko/NapCatQQ)：现代化的基于 NTQQ 的 Bot 协议端实现
- [**zhenxun_bot**](https://github.com/zhenxun-org/zhenxun_bot.git)：QQ 群聊机器人项目
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
