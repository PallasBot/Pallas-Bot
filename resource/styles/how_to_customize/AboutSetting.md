setting中各参数含义如下：

```python
name:str = ""
"""名称"""
intr:str = ""
"""简介"""

fontSize:int = 25
"""普通文本大小"""

title1FontSize:int = 70
"""一级标题文本大小"""
title2FontSize:int = 55
"""二级标题文本大小"""
title3FontSize:int = 40
"""三级标题文本大小"""

expressionFontSizeRate:float = 0.8
"""表达式类（包括行中代码）字体缩放倍率"""

codeBlockFontSize:int = 15
"""行中代码块文本大小"""

rd:int = 30
"""右边距"""
ld:int = 30
"""左边距"""
ud:int = 30
"""上边距"""
dd:int = 30
"""下边距"""

xSizeMax:int = 1000
"""X轴单行元素最大长度"""

font:str = "smSans.ttf"
"""正文字体"""
titleFont:str = "smSans.ttf"
"""标题字体"""
expressionFont:str = "smSans.ttf"
"""表达式字体"""
codeFont:str = "smSans.ttf"
"""代码字体"""

codeBlockLRDistance:int = 20
"""代码块左右边距"""
codeBlockUDDistance:int = 20
"""代码块上下边距"""

formLineDistance:int = 20
"""表格行间距"""
lineDistance:int = 10
"""行间距"""
citeDistance:int = 30
"""引用间距"""

pageLineColor:mdColor = (50,255,255,150)
"""分页竖线颜色"""
pageLineStyle:mdPageLineStyle = "full_line"
"""
分页竖线样式
    - full_line 实线
    - dotted_line 虚线
"""

unorderedListDotColor:mdColor = (204,229,255)
"""无序列表前置点颜色"""
orderedListDotColor:mdColor = (204,229,255)
"""有序列表前置点颜色"""
orderedListNumberColor:mdColor = (76,0,153)
"""有序列表序号颜色"""

citeUnderpainting:mdColor = (0,60,120,180)
"""引用底色"""
citeSplitLineColor:mdColor = (0,102,204,238)
"""引用分割线颜色"""

codeBlockUnderpainting:mdColor = (0,0,102,180)
"""代码块底色"""
codeBlockTitleColor:mdColor = (204,229,255)
"""代码块标题颜色"""

formLineColor:mdColor = (85,255,255)
"""表格分割线颜色"""
formTextColor:mdColor = (255,255,255)
"""表格文本颜色"""
formUnderpainting:mdColor = (0,0,0,0)
"""表格底色"""
formTitleUnderpainting:mdColor = (0,0,0,0)
"""表格标题底色"""

textColor:mdColor = (255,255,255)
"""文本基础颜色"""
textGradientEndColor:mdColor = (30,255,255)
"""由普通字体到一级标题时颜色变化的最终色"""
linkColor:mdColor = (255,187,255)
"""链接颜色"""

expressionUnderpainting:mdColor = (0,0,102,180)
"""表达式底色"""

insertCodeUnderpating:mdColor = (0,0,102,180)
"""行中代码底色"""

idlineColor:mdColor = (120,255,255)
"""行间分割线颜色"""

expressionTextColor:mdColor = (153,204,255)
"""表达式文本颜色"""
insertCodeTextColor:mdColor = (153,255,153)
"""行中代码文本颜色"""
codeBlockTextColor:mdColor = (153,255,153)
"""代码块文本颜色"""

remarkColor:mdColor = (51,255,246)
"""标题备注颜色"""
remarkFontSize:int = 15
"""标题备注字体大小"""
remarkCoordinate:tuple[int,int] = (30,2)
"""标题备注坐标（x为正表示距离左边距离，为负为右边。y为正表示距离上方距离，负数为下方）"""
```