# 消息清洗与审查（message_scrub）

## 这套能力对你意味着什么

牛牛在**复读学习**和**做梦采集 / 漂流**之前，会先过一道「洗消息」：命中规则的内容**不会进学习库、也不会进梦库或往外漂**。你可以把它理解成：**不想让 Bot 记住或转述的话，在这里挡掉**。

**当前版本里，这条链路已经接好、可以直接用。** 只要改 `.env`（或运行环境变量）并重启 Bot（或按需刷新缓存），无需再改代码。已接入范围：

- **牛牛复读**：群消息在去重之后，若被判定拦截，则整条不再参与学习与后续复读逻辑。
- **牛牛做梦**：做梦采集里，除「不可以」等业务规则外，同样会走统一审查；拦截则不入库、不漂流。

不配任何审查项时，行为与过去一致，**不会凭空多拦消息**。

---

## 上手：你可以这样开始

| 你的目标 | 你需要做的大致事情 |
|----------|-------------------|
| 先不用审查 | 什么都不配即可。 |
| 只拦少数固定说法 | 在 `.env` 里配 `PALLAS_INBOUND_FILTER_SUBSTRINGS`（英文逗号分隔，不区分大小写）。 |
| 用一份自己的词表 | 准备一个 UTF-8 的 txt（见下文「词表文件」），配 `PALLAS_SCRUB_LEXICON_PATH` 指向它；也可使用仓库 [`resource/message_scrub/politics.txt`](../../../resource/message_scrub/politics.txt) 例子。 |
| 交给云端判断 | 配置百度 Key，或自建一个符合约定的 HTTP 接口地址（见下文「远程审查」）。 |
| 本地 + 云端都要 | 可同时配词表/子串与百度或自建网关；会先跑本地，再按顺序跑远程。 |

远程审查失败时，默认**放行**（避免 Bot 因网络抽风大面积拒收）；若要「宁可误拦」可把 `PALLAS_INBOUND_FILTER_API_FAIL_OPEN` 设为 `0`。详见后表。

---

## 词表文件（txt）怎么用

适合：有一批固定词，希望**完全在本地、不联网**就拦住。

1. 用编辑器保存为 **UTF-8**，**一行一个词**；以 `#` 开头的行当注释；空行忽略。
2. 把文件放在 Bot 机器上任意可读路径（例如 `data/sensitive_lexicon.txt`）。
3. 在 `.env` 里写一行（路径改成你的实际位置）：

   ```env
   PALLAS_SCRUB_LEXICON_PATH=data/sensitive_lexicon.txt
   ```

   相对路径是相对于**启动 Bot 时的工作目录**；若你不确定工作目录，用**绝对路径**最省心。

4. **只改词表内容并保存**：一般**不用重启**，下次处理消息时会按文件更新时间自动重建词库。
5. **改了路径或改了 `.env` 里其它审查相关变量**：重启 Bot 最稳妥；若你在做二次开发，也可调用 `reload_message_scrub_caches()` 清本地缓存和百度 token 缓存。

从 [Sensitive-lexicon](https://github.com/konsheng/Sensitive-lexicon) 等仓库下载的多份 `.txt`，需要你在本机**先合并成一个**符合上面格式的文件，再把这个文件路径配进 `PALLAS_SCRUB_LEXICON_PATH`（合并方式由你自选脚本）。这类大词表在群聊里容易**误拦正常话**，建议先小范围试，再决定是否全量或搭配百度使用。

---

## 远程审查：百度或自建服务

### 百度

在 `.env` 里填写 **`PALLAS_SCRUB_BAIDU_API_KEY`** 和 **`PALLAS_SCRUB_BAIDU_SECRET_KEY`**（控制台里应用的 API Key / Secret Key）即可。**不用自己维护 `access_token`**，Bot 会自动换取并缓存。

可选：`PALLAS_SCRUB_BAIDU_STRATEGY_ID`（策略中心里的策略）、`PALLAS_SCRUB_BAIDU_BLOCK_SUSPECTED`（是否把「疑似」也当拦截，默认要拦）。

### 自建 HTTP 网关

适合：你们已有统一审核服务，或想用自己语言写逻辑。在 `.env` 里配置 **`PALLAS_SCRUB_API_URL`**（优先）或 **`PALLAS_INBOUND_FILTER_API_URL`**。

对方接口约定：`POST`，JSON 里是 `plain_text`、`raw_message` 两段字符串；返回 JSON 里必须有 **`blocked`** 布尔值，`true` 表示这条消息要拦。若网关需要鉴权，可配 `PALLAS_INBOUND_FILTER_API_KEY`（会以 `Bearer` 形式带上）。

### 多家一起用时的顺序

用 **`PALLAS_SCRUB_REVIEW_PROVIDERS`** 控制先问谁、再问谁（逗号分隔）。**没写这个变量时**：若配了百度，会默认**先百度**；若还配了自建 URL，会**再调自建**。只要**其中任意一家**说拦，这条消息就拦。

举例：

- 只要百度：`PALLAS_SCRUB_REVIEW_PROVIDERS=baidu`
- 自建优先、百度兜底：`PALLAS_SCRUB_REVIEW_PROVIDERS=json_http,baidu`
- 暂时完全不要远程：不要配百度 Key 和自建 URL；或显式 `PALLAS_SCRUB_REVIEW_PROVIDERS=` 且两者都不配。

`json_http`、`generic`、`http` 都表示「上面这个自建 JSON 网关」。

---

## 环境变量速查

| 变量 | 一句话说明 | 默认 |
|------|------------|------|
| `PALLAS_INBOUND_FILTER_SUBSTRINGS` | 逗号分隔，本地子串命中即拦 | 空 |
| `PALLAS_SCRUB_LEXICON_PATH` | 本地词表 txt 路径 | 空 |
| `PALLAS_SCRUB_LEXICON_EXTRA` | 逗号分隔，追加进本地词库 | 空 |
| `PALLAS_SCRUB_REVIEW_PROVIDERS` | 远程审查顺序，见上文 | 未设置则自动 |
| `PALLAS_SCRUB_API_URL` / `PALLAS_INBOUND_FILTER_API_URL` | 自建审查地址，二选一 | 空 |
| `PALLAS_INBOUND_FILTER_API_KEY` | 自建网关 Bearer Token | 空 |
| `PALLAS_INBOUND_FILTER_API_TIMEOUT_SEC` | 远程请求超时（秒） | `2` |
| `PALLAS_INBOUND_FILTER_API_FAIL_OPEN` | 远程失败时放行：`1`/空=放行，`0`=当拦 | `1` |
| `PALLAS_SCRUB_BAIDU_API_KEY` / `PALLAS_SCRUB_BAIDU_SECRET_KEY` | 百度应用密钥 | 空 |
| `PALLAS_SCRUB_BAIDU_CENSOR_URL` | 一般不用改 | 官方默认接口 |
| `PALLAS_SCRUB_BAIDU_STRATEGY_ID` | 百度策略 ID | 空 |
| `PALLAS_SCRUB_BAIDU_BLOCK_SUSPECTED` | 「疑似」是否也拦 | 拦 |

---

## 可选第三方词表（参考）

[konsheng/Sensitive-lexicon](https://github.com/konsheng/Sensitive-lexicon)（MIT）等社区词库，适合作为**合并后 txt** 的素材；**仓库正文不自带大词表文件**。使用时请注意误拦与合规范围，升级词表建议固定版本并做好小群试跑。

对方 `dev` 分支若提供独立 HTTP 服务，需自行对照是否满足上一节的 JSON 约定，或加一层转换。

---

## 源码与二次调用

实现位于 [`src/common/message_scrub/`](../../../src/common/message_scrub/)；配置模型见 [`config.py`](../../../src/common/message_scrub/config.py)。其它插件若要复用同一套判断，可：

```python
from src.common.message_scrub import (
    is_message_scrub_blocked_async,
    is_message_scrub_blocked_sync,
    reload_message_scrub_caches,
)
from src.common.message_scrub import MessageScrubConfig, get_message_scrub_config
```

---

## 关联说明

- 复读：[`docs/plugins/repeater/README.md`](../../plugins/repeater/README.md)
- 做梦：[`docs/plugins/dream/README.md`](../../plugins/dream/README.md)
