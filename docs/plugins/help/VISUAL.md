# 帮助图视觉体系 · 明晰 Clarity

帮助菜单由 [pillowmd](https://github.com/Monody-S/CustomMarkdownImage) 将 Markdown 渲染为长图。本页描述 **Pallas-Bot 默认样式** 的设计令牌与维护方式。

## 设计原则

1. **纸面优先**：暖白底 + 细描边，减少科幻框线、高饱和装饰。
2. **层级靠字号与留白**：标题梯度收敛，正文 24px，避免过多色块争抢注意力。
3. **表格可读**：表头浅灰褐、表体近白、分割线低对比；长文仍依赖 `markdown_generator` 截断与换行。
4. **品牌一点**：酒红 `#B8435A` 用于标题渐变终点、引用竖线、列表圆点；链接用克制蓝灰。

## 色板（RGB）

| 令牌 | 值 | 用途 |
|------|-----|------|
| `canvas` | 250, 247, 243 | 画布外缘（生成脚本 `background.png`） |
| `surface` | 255, 252, 249 | 内容区 / 九宫格中间 |
| `border` | 210, 202, 194 | 边框、表格线、分页线 |
| `text` | 42, 38, 48 | 正文 |
| `text-title` | 184, 67, 90 | 一级标题渐变终点 |
| `text-muted` | 110, 104, 118 | 备注、次要信息 |
| `table-header` | 237, 230, 224 | 表头底 |
| `table-body` | 255, 252, 249 | 表体底 |
| `quote-bg` | 245, 241, 236 | 引用块底 |
| `link` | 91, 106, 184 | 链接、行内强调 |

实现映射见 `resource/styles/default/setting.yml`。

## 排版

| 项 | 值 |
|----|-----|
| 正文字号 | 24 |
| 一级 / 二级 / 三级标题 | 58 / 42 / 32 |
| 左右边距 | 132 |
| 上下边距 | 120 |
| 版心最大宽度 `xSizeMax` | 2400 |
| 行距 `lineDistance` | 12 |
| 表格行距 `formLineDistance` | 20 |

## 资源结构

```
resource/styles/default/
  setting.yml      # 颜色、字体、边距；backgroudFunc 指向 style.py
  style.py         # 全不透明圆角纸面（外缘 canvas、内区 surface）
  elements.yml     # enable: false（勿与 style.py 背景叠用九宫格）
  imgs/            # 可选；当前默认样式不依赖九宫格/立绘
```

背景在 `style.py` 的 `draw_clarity_canvas` 中绘制：**整张图无透明像素**，圆角外侧为暖色 `canvas`，避免在 QQ 等客户端里透明角显示成黑色。

可选：改色板后若仍使用九宫格素材，可运行 `uv run python scripts/generate_pallas_help_style.py`（需自行把 `elements.yml` 的 `enable` 改回 `true`）。

修改样式后需清理帮助图缓存：`data/help/<群号|private>/` 下对应 png，或改 `setting.yml` / `style.py` 触发现有 mtime 失效逻辑。

## 立绘

默认**不使用**立绘。若需侧边图，仅在 `config.py` 将 `side_paint_enabled=true`（与旧版 `elements` 右下角 `character.png` 无关）。

## 与 Markdown 结构的配合

- 一级：总览表 + 引用块导航/示例/开关说明（示例不用表格，以便命令 **加粗**）
- 二级：功能表五列，列宽在生成阶段截断
- 三级：键值表 + 「怎么用」段落

换行宽度常量见 `markdown_generator.py` 顶部 `_HELP_*_WRAP`。

启用/停用：首页表状态列为 **● 已启用** / **○ 已停用**（几何符号，help 字体可显示；勿用 🟢🔴）；占位符 `__HELP_ROW_STATUS__` 按行填入。

帮助文案里的命令用 **加粗** 标出（引用块、段落等表格外正文）；**表格单元格内勿写 `**`**，pillowmd 按纯文本绘制，会露出星号且不会变粗。库默认加粗为左右叠绘易糊，帮助图在 `pillowmd_bold.py` 改为 **描边加粗**（`stroke_width=0.5`，可调 `HELP_BOLD_STROKE_WIDTH`）。不用反引号行内代码（避免缩小字号、浅灰字）。若插件 `usage` 等仍含 `` ` ``，由 `insertCodeTextColor` 与 `expressionFontSizeRate` 保证可读。
