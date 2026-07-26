# 牛牛复读 `repeater`

学习群里的说话方式，接话、跟复读和贴表情。需要群内「自然接话」、不想每次都 `@` 时用本插件；明确叫牛来聊见 [智能对话](../llm_chat/README.md)。

**类型**：本体 core（默认加载）

## 安装

默认加载，无需单独安装。

## 用法

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| 群内正常聊天 | 自动 | 学习后接话、跟复读或贴表情 |
| `@牛牛` 回复「不可以」 | 群内 | 禁止被回复的那条内容 |
| `不可以发这个` | 群内 | 禁止自己最近一条被引用内容 |
| 撤回牛牛消息 | 自动 | 可将内容加入禁用 |

精确口令与「何人可用」以群内 **牛牛帮助** 为准。

## 命令权限（代码默认）

| 命令 ID | 默认等级 |
| --- | --- |
| `repeater.ban` | 群管或号主 |
| `repeater.ban_latest` | 群管或号主 |

实际生效等级以控制台「命令权限」为准。面向用户的 usage 不要写死角色名。

## 配置

控制台对应插件页。常用项见 [`packages/repeater/config.py`](../../../packages/repeater/config.py)。

| 键 | 说明 |
| --- | --- |
| `answer_threshold` | 接话积极程度 |
| `repeat_threshold` | 跟复读频率 |
| `speak_threshold` | 主动插话积极程度 |
| `fanout_enabled` | 多只牛是否一起接话 |

保存后写入 `data/pallas_config/webui.json`。

## 排障

| 现象 | 处理 |
| --- | --- |
| 从不说话 / 话太多 | 调整阈值，并确认没有禁用过多内容 |
| 多牛同群只有一只接话 | 检查多牛接话与协同配置 |
| 不复读 | 检查跟复读频率和当前群聊模式 |

## 源码

[`packages/repeater/`](../../../packages/repeater/)

- `__init__.py`：元数据、禁用命令与帮助结构
- `config.py`：接话 / 复读 / 主动发言配置
- `handlers/`：学习、接话、禁用与决策

若开启 `LLM_REPEATER_MODE`，LLM 可作为选句 / 轻润色参与；默认仍以语料底盘为主。接话决策与 `llm_chat` 共用 conversation kernel。牛格与群风格见 [persona](../persona/README.md)。

## 相关链接

- [命令权限](../../common/cmd_perm/README.md)
- [接话行为 persona](../persona/README.md)
- [`@牛牛` 与复读](../../guide/llm-and-repeater.md)
