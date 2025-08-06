# 自定义style创建指南

将`Template`整个目录复制一份到styles里，然后按`AboutSetting.md`和`AboutElements.md`修改两个json文件以及放置内容到`fonts`和`imgs`即可

风格结构如下：
```
 - setting.yml
该文件用于控制渲染的元素的渲染规则

 - elements.yml
该文件用于编写背景，装饰等的渲染方式

 - style.py（可选）
若使用函数对背景进行绘制，则需包含style.py

 - cover.png（可选）
图标预览（推荐1:1）

 - imgs（文件夹，可选）
用于存放该风格的各种图片资源

 - fonts（文件夹，可选）
用于存放该风格的各种字体资源
```