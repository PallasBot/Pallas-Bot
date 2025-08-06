> 该markdown用于指导填写`elements.json`中的数据（带*的为非必填参数）

# 参数`enable`
> 用于表示是否启用高级背景设置（注：若不启用，则后续设置都不会生效，只生效setting中的改动）

# 参数`page` *
> （非必填）GIF图片数。当填写后，所有图片都需要在后面加上“_数字”，例如“图片1_1.png”，“图片1_2.png”

# 参数`duratio` *
> （非必填）GIF图片间隔，单位秒，默认为0.5

# 参数`playbackSequence` *
> （非必填）GIF图片播放顺序，是一个以空格隔开的字符串，例“1 2 1 2 3 4 5”，默认为“1 2 …… 图片数”，注意数字量必须和图片数一致，否则将持续使用播放的最后一张

可能的值
* `true`启用
* `false`关闭

# 参数`background`
> 用于表示**底层**的绘制数据与模式

## 参数`mode`
> 表示绘制模式

可能的值：
* `0`表示单图填充
* `1`表示九图填充

## 参数`data`
> 填写方式如下：

---

当为`单图填充`时，data内的参数如下：
### 参数`mode`
> 单图填充模式

可能的值：
* `0`表示拉伸填充
* `1`表示填铺式填充.
* `2`表示智能填铺式填充
* `3`表示先根据y轴拉伸填充后，再在x轴上填铺式填充
* `4`表示先根据x轴拉伸填充后，再在y轴上填铺式填充
* `5`表示先根据y轴拉伸填充后，再在x轴上智能填铺式填充
* `6`表示先根据x轴拉伸填充后，再在y轴上智能填铺式填充

### 参数`lock` *
> （非必填）填充图片是否锁定（既无需增加“_编号”，不随gif渲染页数变化而变化）可填的值：`true` `false`（默认：`false`）

### 参数`img`
> 表示填充用的图片文件名（存储在`./imgs`路径下）

---

当为`九图填充`时，data内的参数如下：
### 参数`left-up`
> 左上角填充用的图片文件名（存储在`./imgs`路径下）

### 参数`left`
> 正左边填充用的图片文件名（存储在`./imgs`路径下）

### 参数`left-down`
> 左下角填充用的图片文件名（存储在`./imgs`路径下）

### 参数`up`
> 正上方填充用的图片文件名（存储在`./imgs`路径下）

### 参数`down`
> 正下方填充用的图片文件名（存储在`./imgs`路径下）

### 参数`right-up`
> 右上角填充用的图片文件名（存储在`./imgs`路径下）

### 参数`right`
> 正右边填充用的图片文件名（存储在`./imgs`路径下）

### 参数`right-down`
> 右下角填充用的图片文件名（存储在`./imgs`路径下）

### 参数`middle`
> 正中间填充用的图片文件名（存储在`./imgs`路径下）

### 参数`lu-lock` *
> （非必填）左上角填充图片是否锁定（既无需增加“_编号”，不随gif渲染页数变化而变化）可填的值：`true` `false`（默认：`false`）

### 参数`l-lock` *
> （非必填）正左边填充图片是否锁定（既无需增加“_编号”，不随gif渲染页数变化而变化）可填的值：`true` `false`（默认：`false`）

### 参数`ld-lock` *
> （非必填）左下角填充图片是否锁定（既无需增加“_编号”，不随gif渲染页数变化而变化）可填的值：`true` `false`（默认：`false`）

### 参数`u-lock` *
> （非必填）正上方填充图片是否锁定（既无需增加“_编号”，不随gif渲染页数变化而变化）可填的值：`true` `false`（默认：`false`）

### 参数`d-lock` *
> （非必填）正下方填充图片是否锁定（既无需增加“_编号”，不随gif渲染页数变化而变化）可填的值：`true` `false`（默认：`false`）

### 参数`ru-lock` *
> （非必填）右上角填充图片是否锁定（既无需增加“_编号”，不随gif渲染页数变化而变化）可填的值：`true` `false`（默认：`false`）

### 参数`r-lock` *
> （非必填）正右边填充图片是否锁定（既无需增加“_编号”，不随gif渲染页数变化而变化）可填的值：`true` `false`（默认：`false`）

### 参数`rd-lock` *
> （非必填）右下角填充图片是否锁定（既无需增加“_编号”，不随gif渲染页数变化而变化）可填的值：`true` `false`（默认：`false`）

### 参数`m-lock` *
> （非必填）正中间填充图片是否锁定（既无需增加“_编号”，不随gif渲染页数变化而变化）可填的值：`true` `false`（默认：`false`）

### 参数`lr-mode`
> 正左边与正右边的填充方式

可能的值：
* `0`表示拉伸填充
* `1`表示先根据x轴拉伸填充后，再在y轴上填铺式填充
* `2`表示先根据x轴拉伸填充后，再在y轴上智能填铺式填充

### 参数`ud-mode`
> 正上方与正下方的填充方式

可能的值：
* `0`表示拉伸填充
* `1`表示先根据y轴拉伸填充后，再在x轴上填铺式填充
* `2`表示先根据y轴拉伸填充后，再在x轴上智能填铺式填充

### 参数`middle-mode`
> 正中间图填充模式

可能的值：
* `0`表示拉伸填充
* `1`表示填铺式填充
* `2`表示智能填铺式填充
* `3`表示先根据y轴拉伸填充后，再在x轴上填铺式填充
* `4`表示先根据x轴拉伸填充后，再在y轴上填铺式填充
* `5`表示先根据y轴拉伸填充后，再在x轴上智能填铺式填充
* `6`表示先根据x轴拉伸填充后，再在y轴上智能填铺式填充

# 参数`decorates`
> 用于表示**装饰**的绘制数据与模式

## 参数`top`
> 表示**表层**的装饰绘制数据与模式（在文本上方）

## 参数`bottom`
> 表示**底层**的装饰绘制数据与模式（在文本下方，背景上方）

## `top`与`bottom`的参数（同一格式）

### 参数`left-up`
> 左上角填充所用的所有装饰物对象

### 参数`left`
> 正左边填充所用的所有装饰物对象

### 参数`left-down`
> 左下角填充所用的所有装饰物对象

### 参数`up`
> 正上方填充所用的所有装饰物对象

### 参数`down`
> 正下方填充所用的所有装饰物对象

### 参数`right-up`
> 右上角填充所用的所有装饰物对象

### 参数`right`
> 正右边填充所用的所有装饰物对象

### 参数`right-down`
> 右下角填充所用的所有装饰物对象

### 参数`middle`
> 正中间填充所用的所有装饰物对象

### 装饰物对象格式
每个装饰物都有两种填写方式

 * 方式1
```json
{
    "img":"test.png",
    "mode":0
}
```
mode填写`0`,img处填写图片文件名（存储在`./imgs`路径下）

这种方式填写的图片不会经过任何缩放，直接放置在对应角落

 * 方式2
```json
{
    "img":"test.png",
    "mode":1,
    "xlimit": 0.5,
    "ylimit": 0.5,
    "min":1,
    "max":99
}
```
mode填写`1`，img处填写图片文件名（存储在`./imgs`路径下），xlimit处填写一个(0,1)的值，ylimit处填写一个(0,1)的值,min处填写非0正数（包括小数）,max处填写非0正数（包括小数）

表示图片等比放大，直到到达了绘制的背景的x轴大小的`xlimit`倍或者y轴大小的`ylimit`倍，但最少是原图的`min`倍大小，最大是原图的`max`倍大小

可选参数

1. `include`
> 可以为`false`或者`true`，表示是否不超过边框（九图填充模式下无效，因为没有边框），默认为`false`，可以手动填写为`true`

2. `lock`
> 填充图片是否锁定（既无需增加“_编号”，不随gif渲染页数变化而变化）可填的值：`true` `false`（默认：`false`）

# 一些合法示例（这里只展示底板）

```json
{
    "enable":true,
    "background":{
        "mode": 0,
        "data": {
            "mode": 0,
            "img":"1.png"
        }
    },
    "decorates":{
        "top":{
            "left-up": [],
            "left": [],
            "left-down": [],
            "up": [],
            "down": [],
            "right-up": [],
            "right": [],
            "right-down": [],
            "middle": []
        },
        "bottom":{
            "left-up": [],
            "left": [],
            "left-down": [],
            "up": [],
            "down": [],
            "right-up": [],
            "right": [],
            "right-down": [],
            "middle": []
        }
    }
}
```
![示例1](./examples/1.png)

```json
{
    "enable":true,
    "background":{
        "mode": 1,
        "data": {
            "left-up": "1.png",
            "left": "5.png",
            "left-down": "3.png",
            "up": "7.png",
            "down": "8.png",
            "right-up": "2.png",
            "right": "6.png",
            "right-down": "4.png",

            "lr-mode": 0,
            "ud-mode": 0,

            "middle": "9.png",
            "middle-mode": 0
        }
    },
    "decorates":{
        "top":{
            "left-up": [],
            "left": [],
            "left-down": [],
            "up": [],
            "down": [],
            "right-up": [],
            "right": [],
            "right-down": [],
            "middle": []
        },
        "bottom":{
            "left-up": [],
            "left": [],
            "left-down": [],
            "up": [],
            "down": [],
            "right-up": [],
            "right": [],
            "right-down": [],
            "middle": []
        }
    }
}
```
![示例2](./examples/2.png)

```json
{
    "enable":true,
    "background":{
        "mode": 1,
        "data": {
            "left-up": "1.png",
            "left": "5.png",
            "left-down": "3.png",
            "up": "7.png",
            "down": "8.png",
            "right-up": "2.png",
            "right": "6.png",
            "right-down": "4.png",

            "lr-mode": 0,
            "ud-mode": 0,

            "middle": "9.png",
            "middle-mode": 0
        }
    },
    "decorates":{
        "top":{
            "left-up": [],
            "left": [],
            "left-down": [],
            "up": [],
            "down": [],
            "right-up": [],
            "right": [],
            "right-down": [],
            "middle": []
        },
        "bottom":{
            "left-up": [],
            "left": [],
            "left-down": [],
            "up": [],
            "down": [],
            "right-up": [],
            "right": [],
            "right-down": [],
            "middle": []
        }
    }
}
```
![示例2](./examples/2.png)

```json
{
    "enable":true,
    "background":{
        "mode": 0,
        "data": {
            "mode": 1,
            "img":"1.png"
        }
    },
    "decorates":{
        "top":{
            "left-up": [],
            "left": [],
            "left-down": [],
            "up": [],
            "down": [],
            "right-up": [],
            "right": [],
            "right-down": [],
            "middle": []
        },
        "bottom":{
            "left-up": [],
            "left": [],
            "left-down": [
                {
                    "img":"sugar.png",
                    "mode":0
                }
            ],
            "up": [],
            "down": [],
            "right-up": [],
            "right": [],
            "right-down": [],
            "middle": []
        }
    }
}
```
![示例3](./examples/3.png)

```json
{
    "enable":true,
    "background":{
        "mode": 0,
        "data": {
            "mode": 2,
            "img":"1.png"
        }
    },
    "decorates":{
        "top":{
            "left-up": [],
            "left": [],
            "left-down": [],
            "up": [],
            "down": [],
            "right-up": [],
            "right": [],
            "right-down": [],
            "middle": []
        },
        "bottom":{
            "left-up": [],
            "left": [],
            "left-down": [],
            "up": [],
            "down": [],
            "right-up": [
                {
                    "img":"sugar.png",
                    "mode":1,
                    "xlimit":0.25,
                    "ylimit":0.25,
                    "min":1,
                    "max":99
                }
            ],
            "right": [],
            "right-down": [],
            "middle": []
        }
    }
}
```
![示例4](./examples/4.png)