# 决斗事件包（event_packs）

插件总览（指令、配置、惩罚、权限）：[`docs/plugins/duel/README.md`](../../../../docs/plugins/duel/README.md)。

本目录存放决斗**剧目表**（泰拉/罗德岛风味文案）：引擎按池随机抽事件，解析 `describe` 文案与 `effects` 数值。默认包在 `default/` 下四个 JSON 文件。

## 目录与热重载

| 文件 | 池名 | 何时抽取 |
|------|------|----------|
| `default/public.json` | `public` | 公共幕（歌咏场、使者乱入等） |
| `default/exchange.json` | `exchange` | 兵刃交锋幕（双方对击） |
| `default/challenger.json` | `challenger` | 攻方英雄交锋幕 |
| `default/defender.json` | `defender` | 守方英雄交锋幕 |

- 每个文件必须是 **JSON 数组**，元素为事件对象。
- 修改后由群管/群主在本群发送 **`决斗事件重载`**（默认权限，见命令权限配置），或重启 Bot。
- 可复制 `default/` 为新子目录并改代码中的 `_event_pack_dir()` 以换包（进阶，一般改 `default` 即可）。

## 示范文件（`examples/`）

| 文件 | 内容 |
|------|------|
| `examples/example_public.json` | 公共幕：叠场 + 干员乱入 QTE 全字段注释 |
| `examples/example_exchange.json` | 兵刃：双段 `damage` / `use_damage` + 单段伤害 |
| `examples/example_hero.json` | 英雄交锋：`actor` 目标 + 关键词 QTE |

- **`examples/` 不会被引擎读取**，可放心保留 `_字段名` 式中文说明。
- 正式入库时：复制事件对象到 `default/*.json`，**删除所有以 `_` 开头的键**（引擎会忽略未知键，但不宜把说明键留在生产环境）。

## 单条事件结构

```json
{
  "id": "唯一英文标识",
  "weight": 10,
  "describe": "发到群里的台词，支持占位符",
  "effects": [],
  "damage": 0,
  "damage2": 0,
  "qte": {}
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 日志与排错用，建议 `池前缀_简述`，如 `public_mist`。 |
| `weight` | 否 | 权重，默认 `1`；越大越常抽到。带 `qte` 的事件在引擎中另有权重倍率（见插件配置 `duel_qte_event_weight_mult`）。 |
| `describe` | 是 | 本幕主文案；可含占位符（见下）。 |
| `effects` | 否 | 效果对象数组，见「效果类型」。 |
| `damage` | 否 | 整数或 `[最小, 最大]`，掷出 `<DMG>`；与 `use_damage: true` 配合。 |
| `damage2` | 否 | 同上，对应 `<DMG2>` / `use_damage: "damage2"`。 |
| `qte` | 否 | 关键词 QTE 或干员乱入；见「QTE」。 |

解析失败的事件会被跳过并写日志，不会中断整场决斗。

## 文案占位符

在 `describe` 及 QTE 相关字符串中使用：

| 占位符 | 含义 |
|--------|------|
| `<A>` | 挑战者（@） |
| `<B>` | 守方（@） |
| `<DMG>` / `<DMG2>` | 本事件掷出的伤害值 |
| `<AHP>` `<BHP>` `<ADP>` `<BDP>` `<场>` | 当前双方 HP/DP/场地层（需走战斗格式化） |
| `<O>` | 干员游戏内显示名 |
| `<P>` | 职阶中文 |
| `<S1>`–`<S3>` `<S1D>`–`<S3D>` | 技能名与描述 |
| `<SK>` `<SKD>` `<SKL>` `<SKK>` | 乱入幕随机抽中的技能名、描述、标签、种类（治疗/攻击/中性） |

干员相关占位符仅在需要干员上下文的事件中有效（如 `operator_intrusion` 或文案中含上述标签）。

## 效果类型（`effects`）

`target` 常用值：`actor`（当前行动方）、`challenger`、`defender`、`both`、`other`（对手）。

| `type` | 说明 |
|--------|------|
| `deal_damage` | 损创（先扣 DP 再扣 HP；**场地层数会额外加在伤害上**） |
| `heal_hp` | 治疗（**+场地层数**） |
| `add_dp` | 增加防御层 DP（上限 5） |
| `add_self_buff` | 神恩层 +1（单方上限 4） |
| `add_self_debuff` | 损创层 +1（单方上限 4） |
| `add_field` | 场地 +N（上限 3）；叠场时**双方各 +N DP** |

固定数值用 `"value": 3`。若伤害来自掷骰，在效果中加 `"use_damage": true`（或 `"damage2"` 用第二段伤害）。

示例：

```json
{
  "type": "deal_damage",
  "target": "defender",
  "use_damage": true
}
```

## 关键词 QTE

`qte` 为对象且**不含** `"type": "operator_intrusion"` 时，按关键词拆招处理。

```json
"qte": {
  "target": "actor",
  "keys": ["格挡", "盾反", "看破"],
  "window_sec": 10,
  "prompt": "（可选，拼在提示前）",
  "on_success_effects": [],
  "on_fail_effects": []
}
```

| 字段 | 说明 |
|------|------|
| `target` | 谁来答：`actor` / `challenger` / `defender` |
| `keys` | 合法答案列表；应答须**整句完全一致**（纯文本，无 CQ 码） |
| `window_sec` | 倒计时秒数 |
| `on_success_effects` / `on_fail_effects` | QTE 成功/失败后额外结算的效果数组 |

兵刃池 `exchange.json` 中也可无 `qte`：本段若有人扣 HP，则按 `duel_exchange_qte_chance` 让**本段损创更多的一方**拆招（挑战者/守方均可）；事件内已写 `qte` 时按 JSON 的 `target` 为准。

## 干员乱入 QTE（`operator_intrusion`）

```json
"qte": {
  "type": "operator_intrusion",
  "target": "challenger",
  "window_sec": 14,
  "show_avatar": true,
  "prompt": "（可选）",
  "intrusion_prelude": "登场文案…",
  "after_success_describe": "辨认成功，技能帮打对手…",
  "after_fail_describe": "辨认失败，攻击类技能打认错方…",
  "after_fail_describe_heal": "辨认失败，治疗类仍落下但落在另一方…",
  "on_success_effects_heal": [],
  "on_success_effects_attack": [],
  "on_success_effects_neutral": [],
  "on_fail_effects": []
}
```

- 系统从 `resource/arknights/operators_6star.json` 随机干员（帕拉斯专属事件可写死 `public_pallas_intrusion`）。
- 应答方须在窗口内发送**闯入者游戏内干员名**（与名册一致）。
- **辨认成功**：按技能种类选用 `on_success_effects_*`，效果多指向对手。
- **辨认失败**：仍落下本幕技能；攻击类打应答方（`<A>`/`<B>` 随本幕 `actor`）；治疗类 `heal_hp`/`add_dp` 改落在**另一方**（如 A 认错却治疗 B）；另结算 `on_fail_effects`。治疗文案用 `after_fail_describe_heal`。
- `pallas_prelude` / `pallas_after_success` / `pallas_after_fail` 仅帕拉斯乱入事件使用，语义同 `intrusion_prelude` 等。
- 可选 `profession_bonus` / `sub_profession_bonus`：按职阶/子职阶 ID 追加成功效果（群内不展示子职阶名，见 `public.json` 示例）。

## 撰写建议

1. **权重**：公共幕不宜全部过高；带强 QTE 或帕拉斯的事件宜低权重。
2. **文案**：一句戏剧动作 + 可选括号内数值提示；规则讲解已不在开幕宣读，复杂机制可在括号简短说明。
3. **伤害**：`exchange` 池优先用 `damage` 区间 + `use_damage`，避免 `value` 与掷骰不一致。
4. **校验**：保存为 UTF-8 JSON，用编辑器或 `python -m json.tool 文件.json` 检查语法；改完务必 **`决斗事件重载`** 或重启。
5. **干员表**：六星表由 `scripts/fetch_arknights_duel_data.py` 生成（含 `character_table.nationId` → `nation_id` / `nation_cn`，对照表见脚本内 `NATION_CN`），与乱入 QTE 独立维护。

## 相关配置（WebUI · 牛牛决斗）

惩罚时长、幕间停顿、公共幕概率、QTE 权重、牛自动咏名成功率等见插件 `config.py` / 控制台插件配置页，**不写在 JSON 里**。

- **插件配置热重载**：WebUI 保存「牛牛决斗」插件配置后会写入 `.env` 并调用 `reload_duel_plugin_config()`，**无需重启 Bot** 即可生效。
- **剧目 JSON 热重载**：修改 `default/*.json` 后由群管/群主在群内发送 **`决斗事件重载`**，或重启 Bot。
