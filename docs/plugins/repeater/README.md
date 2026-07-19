<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="牛牛复读">
</p>

<h1 align="center">牛牛复读 repeater</h1>

<p align="center">学习群里的说话方式，接话、复读和贴表情。</p>

<p align="center">
  <img alt="本体 core" src="https://img.shields.io/badge/%E6%9C%AC%E4%BD%93%20core-4B5563">
  <img alt="默认加载" src="https://img.shields.io/badge/%E9%BB%98%E8%AE%A4%E5%8A%A0%E8%BD%BD-4EA94B">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

默认加载，无需单独安装。

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `群内正常聊天` | 自动 | 学习后接话、跟复读或贴表情。 |
| `@牛牛` 回复 `不可以` | 群内 | 禁止被回复的那条内容。 |
| `不可以发这个` | 群内 | 禁止自己最近一条被引用内容。 |
| `撤回牛牛消息` | 自动 | 可将内容加入禁用。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `repeater.ban` | 群管或号主 |
| `repeater.ban_latest` | 群管或号主 |

## 配置项

> 可在控制台对应插件页中修改。

常用配置见 [`packages/repeater/config.py`](../../packages/repeater/config.py)。

| 键 | 说明 |
| --- | --- |
| `answer_threshold` | 接话积极程度 |
| `repeat_threshold` | 跟复读阈值 |
| `speak_threshold` | 主动插话积极程度 |
| `fanout_enabled` | 多只牛是否一起接话 |

## 排障

| 现象 | 处理 |
| --- | --- |
| 从不说话 / 话太多 | 调整阈值，并确认没有被禁用太多内容。 |
| 多牛同群只有一只接话 | 检查多牛接话配置和协同设置。 |
| 不复读 | 检查跟复读阈值和当前群聊模式。 |

## 实现

源码位置：[`packages/repeater/`](../../packages/repeater/)

关键文件：

- [`__init__.py`](../../packages/repeater/__init__.py)：注册元数据、禁用命令和帮助结构。
- [`config.py`](../../packages/repeater/config.py)：定义接话、复读和主动发言相关配置。
- [`handlers/`](../../packages/repeater/handlers)：处理学习、接话、禁用和行为决策。

实现要点：

- 复读不只是“看到什么学什么”，还会根据语料、阈值和上下文决定是否接话。
- 同一句话连续出现时，会走跟复读路径；平时则可能接近似语境的话。
- `不可以` 系列命令会直接影响后续学习和回复范围。
- 若开启 `LLM_REPEATER_MODE`，LLM 可以作为接话补位或轻润色层参与，但默认仍是语料底盘优先。
- 接话决策与观测已收敛到共享 conversation kernel（`pallas/product/llm/kernel/`），与 `llm_chat` 共用 scene/action/trace 契约。
- 这和 `@牛牛` 随时闲聊不同：`repeater` 负责平时群内自然接话，`llm_chat` 负责明确叫牛牛来聊。

## 相关链接

- [命令权限说明](../common/cmd_perm/README.md)
- [接话行为说明](../persona/README.md)
- [`@牛牛`、复读接话与 LLM 的关系](../../guide/llm-and-repeater.md)
