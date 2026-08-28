# 群洞察与语义风格指导器

本文说明群表达画像如何从入站消息产生，如何经过低频增量处理进入 `profiles.json`，以及它如何在 LLM 对话中生效。这里的“语义风格”不是 Repeater 的实时选句器，也不是一次性生成整篇群聊总结，而是按 `bot × group × scene` 持续积累的表达参考。

## 一句话链路

```text
群消息
  -> message 表
  -> 主进程低频 sweep
  -> group.insight work job
  -> message 去重与真人序列取对
  -> LLM 批量标注
  -> examples.jsonl / profiles.json
  -> llm_chat 注入群表达指导与接话策略
```

回复形状是旁边的一条确定性链路：

```text
message 表
  -> group_profiler
  -> group_config.style_profile
  -> reply_shape / reply_max_length
```

两条链路都消费 `message` 表，但输出不同：语义风格需要 LLM 判断“这是不是可迁移的接话”，回复形状只统计消息长度、段数和节奏。

## 1. 消息入库

群消息在统一 matcher 入口尽早旁路记录。`message_recorder` 使用有界队列异步批量写入 PostgreSQL `message` 表，不参与当前消息是否回复的决策。

每条消息至少包含：

- `group_id`、`user_id`、`bot_id`
- `plain_text`、`raw_message`、`sender_name`
- `message_id`、`reply_to_message_id`
- `time` 以及必要的消息状态字段

多 Bot 同时处理同一个群时，同一条消息可能因为不同 `bot_id` 在表中出现多行。PostgreSQL 使用 `(group_id, bot_id, message_id)` 作为幂等锚点；语义处理还会按 `message_id` 再去重，避免多 Bot 记录把取数窗口占满。

Repeater 仍保留 `repeater.message` 的兼容写入路径。`repeater.learn` 是否因压力保护跳过，不会改变群洞察的事实来源：群洞察读的是已经入库的消息。

## 2. 六小时 sweep

群洞察的调度运行在主进程，当前默认值如下：

| 参数 | 当前值 | 含义 |
| --- | ---: | --- |
| `_SWEEP_INTERVAL_SEC` | 6 小时 | 两轮群扫描之间的间隔 |
| `_SWEEP_BATCH_SIZE` | 1024 | 一轮最多入队的群数 |
| `_SEMANTIC_LOOKBACK_DAYS` | 7 天 | 发现近期活跃群的范围 |
| `_SWEEP_STARTUP_POLL_SEC` | 30 秒 | 启动早期等待 Bot 连接的轮询间隔 |

sweep 会先枚举本地 Bot 在最近 7 天处理过的群并集，再为每个群解析语义采集 Bot：

1. 如果群配置了 `repeater.semantic_style_bot_id`，使用配置值。
2. 未配置时，从该群近期有处理记录的本地 Bot 中选 ID 最小者。
3. 没有可用本地 Bot 时，本轮跳过该群。

语义采集 Bot 只是 profile 的归属账号，不要求它在每次历史消息发生时在线。profile 仍然按 `bot_id × group_id × scene` 隔离。

每个任务的幂等 key 包含 6 小时 slot：

```text
group.insight:semantic:{bot_id}:{group_id}:{sweep_slot}
```

因此同一群同一个 sweep slot 不会重复创建同一个任务。

### 为什么不是每 20 分钟

群表达不是实时热路径。消息先持续进入 `message` 表，语义处理在后台按周期增量消费。六小时调度减少空任务、磁盘画像检查和 work job 调度噪声，同时仍能让画像在一天内得到多次更新。

## 3. 候选对重建

work aux 消费 `group.insight` 后，按该 `(bot_id, group_id)` 的持久化语义游标读取新区域。当前取数规则为：

- 最多回溯 `_PAIR_PAGE_LIMIT=96` 页
- 每页最多 32 条消息
- 按 `message_id` 去重
- 排除当前 Bot 和协作 Bot，建立真人消息序列
- 每个 job 最多产生 `_MAX_PAIRS_PER_JOB=24` 个候选对

候选对有两种关系：

### `quoted`

回复消息的 `reply_to_message_id` 指向一条已知真人消息，形成明确的引用关系。

### `adjacent`

取回复之前最近的一条真人消息作为前句。中间夹着 Bot 状态消息、其它机器人消息或系统消息时，仍然可以在真人序列中连接起来。

回复端不再强制要求是真人：

- 真人接真人：可以进入 `direct_pairs`，作为群表达指导。
- 真人接 Bot：可以进入 `self_reflection`，只沉淀 Bot 自己的接话策略，不进入真人措辞样本。

消息正文在送入标注前会折叠空白并截断；CQ 图片、表情和其它媒体码分别替换为 `[图片]`、`[表情]`、`[媒体]`。语义风格只需要知道存在媒体，不需要在这一环节理解图片细节。

## 4. 为什么每批是 8 个

`8` 是 LLM 请求批大小，不是消息窗口，也不是画像更新周期。

当前层级是：

```text
1 个 group.insight job
  最多 24 个候选对
    每 8 个候选对 1 次 LLM 请求
```

正常情况下，一个 job 最多需要 3 次批量提交。选择 8 的考虑是：

- JSON 数组长度有限，模型更容易保持输入顺序和输出项数一致
- 每个候选前后句最多送入 72 字，8 对的 prompt 仍然较紧凑
- 单次输出上限为 `128 × batch_size`，不会随群消息量无限增长
- 批量请求失败时，最多只影响这一组 8 对的 fallback 范围
- 批次太大时，单次格式错误会放大重试成本；批次太小时，HTTP 请求次数增加

因此 8 是当前“请求稳定性与提交次数”的保守折中，不具有业务上的特殊含义。以后可以通过实际 JSON 失败率、fallback 比例和 token 统计调整，但不能把它误解为“每 8 条消息总结一次”。

## 5. 标注、预算与游标

批量标注输出固定长度 JSON 数组，包含：

- `is_reply_pair`：是否确实在回应前句
- `transferable`：脱离临时人名、局部梗和临时事实后是否仍可复用
- 接话动作、语义关系、强度、表达形式
- 可选的 `behavior_strategy`

只有 `is_reply_pair=true` 且 `transferable=true` 的结果才写入语义样本。完整标注完成后，才推进该群的持久化游标。

语义标注预算配置为 `llm_semantic_style_realtime_daily_limit`，默认每天 5000 次。预算计数文件位于：

```text
data/pb_webui/repeater_semantic_style/semantic_style_label_budget.json
```

预算按实际 LLM 请求计数：一次 8 对批量请求算 1 次；批量失败后的每一次单对 retry 也单独占用 1 次。请求发起前在进程锁和跨进程文件锁内原子预占，避免多个 work worker 同时通过检查。

达到预算时，任务软跳过：不报失败、不推进游标，下一轮继续处理。LLM 请求失败或 fallback 失败时同样不推进游标，避免候选被错误标记为已完成。

游标文件位于：

```text
data/pb_webui/repeater_semantic_style/semantic_style_group_cursors.json
```

key 是 `{bot_id}:{group_id}`，当前保存的是已处理到的秒级时间戳。它能防止正常重启后重复扫描整个历史窗口，但不是完整的复合游标。

## 6. 画像落盘与消费

语义样本和聚合画像分别保存在：

```text
data/pb_webui/repeater_semantic_style/examples.jsonl
data/pb_webui/repeater_semantic_style/profiles.json
```

落盘过程使用进程锁和跨进程文件锁，并按 `example_id` 去重。写入样本后会重建 profile；缓存进程启动时加载，之后按周期刷新。

`llm_chat` 需要明确唤醒并通过当前回合决策后，才会读取对应的语义 profile。可消费的内容包括：

- `direct_pairs`：群表达指导中的历史措辞参考
- `observed` 行为策略：`【真人接话参考】`
- `self_reflection` 行为策略：`【接话复盘】`
- 经过约束的 `direct_candidate`

语义样本不是强制回复模板。人设、关系和当前回合决策优先，群级样本只提供局部表达差异。

日常 Repeater 接话仍直接投递 Repeater 语料，不调用语义标注 LLM，也不经过 LLM 选句或润色。

## 7. 回复形状不是语义风格

群回复画像由 `group_profiler` 从 `message` 表计算并写入 `group_config.style_profile`。它统计：

- 真人消息长度的平均值、p50、p90
- 单泡/多泡比例
- 每条消息的段数和段长分布
- 群活跃时间以及回答相关统计

该画像由独立的 dirty 刷新 worker 维护，默认约 20 分钟一轮。它决定 `reply_shape` 和 `reply_max_length` 的长度、段数及节奏取向，不负责判断一句话是否属于可迁移的接话风格。

## 8. 当前是否还会饿死

此前的确定性饿死来自两个问题：低样本群达到阈值后永久停止，以及每轮固定从排序头部取少量群。当前实现已经移除这两个条件，并采用：

- 6 小时周期
- 1024 群批量上限
- 轮转游标
- 每群持久化语义游标
- 预算或 LLM 失败不推进游标

当前活跃群规模低于 1024 时，一轮正常可以覆盖全部群，因此不会再因为群号排在后面而永久得不到任务。

仍然存在三个明确边界：

1. sweep 轮转游标目前只在进程内；活跃群超过 1024 且频繁重启时，尾部群可能延迟。
2. 每个本地 Bot 的群发现查询有 128 个上限；单 Bot 管理大量群时，发现层需要进一步分页或改为直接按群查询。
3. 语义游标只有秒级时间；同一秒消息极密集时，部分消息可能被跳过。要彻底解决需要 `(time, message_id)` 复合游标。

这些属于可观测的延迟或极端漏采边界，不是旧实现那种由固定排序造成的永久饿死。

## 9. 与记忆层的关系

当前多个记忆任务都可能使用 `memory_extract` 这个 task 名，但这只表示路由和计量分类，不表示它们已经共用一次 LLM 请求。当前仍是独立提交、独立结果和独立落库。

最适合尝试复用一次请求的是同一个群事件快照中的：

```text
auto_episode 事件摘要
graph extract 实体与关系
```

未来可以让一次请求返回独立结果头：

```json
{
  "summary": "事件摘要",
  "entities": [],
  "edges": []
}
```

代码仍需分别校验和落库：摘要失败不能抹掉图谱结果，图谱失败也不能让摘要丢失；预算、统计和失败状态按结果头记录。

以下任务暂不与群洞察混批：

- 人物事实：归属到具体 `(bot, group, user)`
- 好感度：单用户即时触发，有独立冷却和预算
- session summary：会压缩或删除旧会话历史，副作用不同
- 群表达语义标注：输入是前句→接话对，输出是迁移性和接话策略

禁止跨 Bot、跨群、私聊与群聊混批。共同使用 Provider、预算工具或 work aux，不等于可以共同使用同一次模型提交。

## 10. 排障入口

| 现象 | 优先检查 |
| --- | --- |
| 群没有被调度 | 主进程日志中的“群洞察扫描”、Bot 是否已连接、近 7 天群发现上限 |
| 任务执行但没有新样本 | `message` 表是否有真人候选、游标文件、LLM 标注失败和 `transferable` 过滤 |
| 样例摘要为空 | WebUI scope 是否选择了实际有 profile 的 Bot，检查 `profiles.json` |
| 回复形态全为 0 | `group_config.style_profile` 更新时间、`group_style_refresh` dirty 刷新及 message 去重取数 |
| 预算快速耗尽 | `semantic_style_label_budget.json`、批量请求失败比例、fallback/retry 日志 |

代码入口：

- `pallas/core/platform/ingress/message_recorder.py`
- `pallas/product/llm/group_insight_processor.py`
- `pallas/product/llm/repeater_semantic_style.py`
- `pallas/product/persona/group_profiler.py`
- `pallas/product/persona/group_style_refresh.py`
- `packages/llm_chat/chat_message.py`
- `pallas/product/llm/assembler/chat_prompt.py`

相关页面：[LLM 上下文注入](llm-context-injection.md)、[LLM 输出路径](llm-output-path.md)、[LLM 与 Repeater](/guide/llm-and-repeater)。
