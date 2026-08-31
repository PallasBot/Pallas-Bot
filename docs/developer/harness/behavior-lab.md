# 行为实验室（Behavior Lab）

面向「提示即验收」的反馈回路：用脱敏 fixture 驱动 OneBot 入站，在进程内复现消息运行时行为，捕获出站动作与结构化事件，并输出稳定 JSON 结果与修复提示。当前实现复用并扩展了 `tools/llm_event_harness.py`，不修改 `pallas/` / `packages/` 生产语义。

**Owner**: llm（`tools/llm_event_harness.py` 与 `tests/tools/test_llm_event_harness*.py`）
**验证状态**: unit（`uv run pytest tests/tools/test_llm_event_harness.py tests/tools/test_llm_event_harness_contract.py -q`）；本页对应能力为逐步新增，未接入 CI 全量门禁前以专项测试覆盖。

## 稳定结果契约

运行每个 fixture 输出一条稳定 JSON。字段：

| 字段 | 说明 |
| --- | --- |
| `case` / `variant` | fixture 名与变体标签 |
| `status` | `delivered` / `gate_skipped` / `direct_handled` / `timeout` / `failed` |
| `journey` | `command` / `matcher` / `llm` |
| `route` | 实际处理路由（`direct` / `matcher` / `llm_chat`） |
| `request_id` | 关联 ID（若生产链路提供） |
| `stages` | 事件阶段（脱敏后） |
| `outbound_actions` / `api_calls` | 出站动作（脱敏后） |
| `assertions` | 由 fixture `expect` 求值的结果：`expected` / `checks` / `passed` |
| `error` / `error_class` | 失败信息与错误类 |
| `repair_hint` | 一条面向排障的修复方向提示 |
| `redaction_summary` | 记录脱敏范围与掩码 |

**脱敏边界**：默认输出掩码 `[REDACTED]` 覆盖回复正文、出站 `message` 与 stage 中的消息/提示词正文；`redaction_summary.redacted_stage_keys` 列出被掩码的键。需要原始正文调试时使用工具内部接口而非默认输出。

## Fixture 形态

`tools/fixtures/*.jsonl`，每行一个 JSON 对象：

```json
{
  "journey": "command",
  "name": "command.success",
  "event": { "self_id": "10001", "post_type": "message", "message_type": "group", "user_id": 30003, "group_id": 20002, "message_id": 1, "message": [{"type": "text", "data": {"text": "#pallas"}}], "sender": {"role": "member"} },
  "expect": { "route": "direct", "status": "delivered", "outbound": 1 }
}
```

- `journey` 决定如何解释结果：`command` → 直连命令路由，`matcher` → 兼容 matcher 路径，`llm` → LLM 对话路由。
- `expect` 是提示即验收的断言源，支持 `route` / `status` / `outbound`（最小出站条数）。缺失时为中性。

## 运行命令

```bash
# 全量跑命令旅程，结果脱敏 JSON 输出并可选落盘
uv run python tools/llm_event_harness.py \
  --fixtures tools/fixtures/harness_command.jsonl \
  --journey command --out /tmp/out.jsonl
```

## 首批旅程与覆盖

| 旅程 | fixtures | 覆盖成功 / 拒绝降级 / 失败重试 |
| --- | --- | --- |
| command | `tools/fixtures/harness_command.jsonl` | 是 |
| matcher | `tools/fixtures/harness_matcher.jsonl` | 是 |
| llm | `tools/fixtures/harness_llm.jsonl` | 是（复用既有 LLM 事件链） |

每类旅程用脱敏正文占位（成功/拒绝/重试），断言与修复提示即反馈回路的最小闭环。后续阶段可平滑扩展异步/分片旅程，不改变既有 LLM 旅程契约。

## 边界

- 只新增工具/测试/fixtures/文档与入口映射；生产代码字节级中性。
- 移除 fixture/调用即可回滚；不引入新的持久状态。
- 高风险生产动作与真实发送边界保留人工审批，不在工具内绕过。
