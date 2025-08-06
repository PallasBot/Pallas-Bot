<div align="center">

<img alt="LOGO" src="https://user-images.githubusercontent.com/18511905/195892994-c1a231ec-147a-4f98-ba75-137d89578247.png" width=360 height=270/>

# Pallas-Bot

<br>

我是来自米诺斯的祭司帕拉斯，会在罗德岛休息一段时间......

虽然这么说，我渴望以美酒和戏剧被招待，更渴望走向战场。

</div>
<br>

🚀 Pallas-Bot 2.0 发布啦！🥳

## Pallas-Bot 2.0 有什么改进？

1. 将 AI 功能分离至 [AI 服务端](https://github.com/PallasBot/Pallas-Bot-AI)
2. 代码全面重构，牛牛更易维护
3. 数据库操作全异步改造，牛牛运行更高效
4. 项目文件规范化，牛牛部署更简单
5. 优化 Docker 构建，支持 Arm64 架构
6. 支持语音文件自动下载，启动时自动检查并配置语音资源
7. 修复了一些老 bug

## 牛牛有什么功能？

牛牛的功能就是废话和复读。牛牛几乎所有的发言都是从群聊记录中学习而来的，并非作者硬编码写入的。群友们平时怎么聊，牛牛就会怎么回，可以认为是高级版的复读机

## 那为什么牛牛说了一些群里从来没说过的话？

牛牛有跨群功能，若超过 N 个群都有类似的发言，就会作为全局发言，在任何群都生效

## 你说牛牛没有功能，为什么有时候查询信息、或者一些其它指令，牛牛会回复？

从别的机器人（可能是其他群）那里学来的

~~你这机器人功能不错呀，现在牛牛也会了！~~

## 有时候没人说话，牛牛自己突然蹦出来几句话

哈，是主动发言功能！内容同样从群聊里学来的！

## 怎么教牛牛说话呢？

正常聊天即可，牛牛会自动学。

如果想强行教的话，可以这样：

```text
—— 牛牛你好
—— 你好呀
—— 牛牛你好
—— 你好呀
—— 牛牛你好
—— 你好呀
```

如此重复 3 次以上，下一次再发送 “牛牛你好”，牛牛即会回复 “你好呀”

## 牛牛说了一些不合适的话，要怎么删除？

群管理员 **回复** 牛牛说的那句话 “不可以” 或直接 **撤回** 消息即可，同样的若超过 N 个群都禁止了这句话，就会作为全局禁止，在任何群都不发

## 牛牛的一些其他小功能

- `牛牛帮助`：在获得牛牛功能的信息的同时控制功能开关
- `牛牛喝酒`：增加牛牛说话概率，有概率喝醉（）
- `牛牛轮盘` & `牛牛开枪`：需要给牛牛管理员才能使用，试试你就知道是啥功能了.jpg
- 随机修改自己的群名片为近期发言的人，夺舍！期望时间 8 小时一次

以下功能仅当部署了 [AI 服务端](https://github.com/PallasBot/Pallas-Bot-AI) 且开启对应功能时可用：

- `牛牛唱歌 <网易云歌曲 ID>`：AI 牛牛翻唱！（人声提取 + 音色转换）
- 酒后聊天：`牛牛喝酒` 后，切换至 ChatRWKV 模型，由 AI 回复（只回复 at 及 `牛牛` 开头的内容）
- 文本转语音（TTS）：酒后聊天的内容会被转换为牛牛的语音发送

## 题外话

牛牛的说什么完全依赖于大家聊什么，希望大家不要故意教牛牛一些不好的东西。发现牛牛学了一些不合适的话及时帮忙删除。

大家一起教出更棒更聪明的牛牛！✿✿ヽ(°▽°)ノ✿

## 如何拥有一只自己的牛牛？

### 直接拉作者部署的牛牛进群

~~官方牛~~

请加 [牛牛2.0总群](#QQ群)，在群公告的表格里挑一只你喜欢的牵走~  

为了防止牛牛账号被风控，拉了牛牛后请不要禁言牛牛或直接踢，请参考群公告联系号主手动退群，否则该群将被自动拉黑。

### 自行部署

请参考 [部署教程](docs/Deployment.md)

## 致谢

### 开源库

[nonebot2](https://github.com/nonebot/nonebot2): 跨平台 Python 异步聊天机器人框架  
[jieba_fast](https://github.com/deepcs233/jieba_fast): 高效的中文分词库  
[beanie](https://github.com/BeanieODM/beanie): Asynchronous Python ODM for MongoDB  
[NapCat](https://github.com/NapNeko/NapCatQQ): 现代化的基于 NTQQ 的 Bot 协议端实现  

~~[go-cqhttp](https://github.com/Mrs4s/go-cqhttp): cqhttp的golang实现，轻量、原生跨平台.~~  
~~[nonebot-plugin-gocqhttp](https://github.com/mnixry/nonebot-plugin-gocqhttp): 一款在NoneBot2中直接运行go-cqhttp的插件, 无需额外下载安装~~  
~~[so-vits-svc](https://github.com/innnky/so-vits-svc): 基于vits与softvc的歌声音色转换模型~~  
~~[PaddleSpeech](https://github.com/PaddlePaddle/PaddleSpeech): Easy-to-use Speech Toolkit including Self-Supervised Learning model, SOTA/Streaming ASR with punctuation, Streaming TTS with text frontend, Speaker Verification System, End-to-End Speech Translation and Keyword Spotting. Won NAACL2022 Best Demo Award.~~  

### 贡献者

感谢各位大佬！

[![Contributors](https://contributors-img.web.app/image?repo=PallasBot/Pallas-Bot)](https://github.com/PallasBot/Pallas-Bot/graphs/contributors)

## QQ群

~~牛牛调教一群: 831322617 被腾讯封了 orz~~  
~~牛牛调教一群: 765213099 又被封了（恼~~  
~~牛牛调教四群: 717508273 。。。~~  
~~牛牛调教五群：228620837~~  
牛牛~~调教~~闲聊六群（已转为闲聊群）：865638357  
牛牛2.0总群（拉牛牛）：789311420  
牛牛2.0闲聊群（仅闲聊）：566968684  
开发者群（开发者）: 716692626  

## 打赏

请作者喝杯咖啡吧~ （请备注牛牛项目，感谢你的资瓷 ✿✿ヽ(°▽°)ノ✿）

<a href="https://afdian.com/a/misteo">
  <img width="200" src="https://pic1.afdiancdn.com/static/img/welcome/button-sponsorme.png">
</a>
