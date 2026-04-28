import random
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class RescueJudgmentConfig:
    fail_msg: str
    fail_prob: float
    self_punish_prob: float  # 反噬概率
    self_punish_requires_drunk: bool  # True = 仅在喝酒状态下触发反噬
    self_ban_duration: Callable[[], int]  # 反噬禁言时长
    self_punish_msg: str  # 反噬成功时的消息
    self_punish_protected_msg: str  # 权限不足时的消息
    target_ban_duration: Callable[[], int]  # lambda: 0 表示解禁
    target_prefix: str
    target_suffix: str
    no_target_duration: Callable[[], int]  # lambda: 0 表示全体解禁
    no_target_msg: str
    no_target_no_one_msg: str


# 救一下：正常情况只解禁，喝酒后有概率反噬请求者
RESCUE_CFG = RescueJudgmentConfig(
    # 12.5% 概率直接失败，不执行任何操作
    fail_msg="十二英雄神殿中的圣火也依然在熊熊燃烧吧，只是我再也没资格去点燃圣火了...",
    fail_prob=0.125,
    # 仅在喝酒状态下有 30% 概率反噬请求者
    self_punish_prob=0.3,
    self_punish_requires_drunk=True,
    self_ban_duration=lambda: random.randint(5, 30) * 60,
    self_punish_msg="还请您体谅我，让我用这浅陋的方式平复心情。",
    self_punish_protected_msg="勇士们，英雄们，最后再打磨一下自己的武器吧。",
    # duration=0 表示解禁
    target_ban_duration=lambda: 0,
    target_prefix="命运之手指向了为沉默所困之人，",
    target_suffix="，已从沉默中被解放。",
    # no_target_duration=0 表示全体解禁
    no_target_duration=lambda: 0,
    no_target_msg="命运的轮盘再次转动，所有的沉默都被打破。",
    no_target_no_one_msg="此刻并无需要拯救之人，和平仍在延续。",
)

# 补一枪：追加禁言，喝酒后有概率反噬请求者
JUDGMENT_CFG = RescueJudgmentConfig(
    # 12.5% 概率直接失败，不执行任何操作
    fail_msg="这些人只是年少轻狂，请别因一时之怒夺了他们的未来。",
    fail_prob=0.125,
    # 仅在喝酒状态下有 20% 概率反噬请求者
    self_punish_prob=0.2,
    self_punish_requires_drunk=True,
    self_ban_duration=lambda: random.randint(25, 120) * 60,
    self_punish_msg="还请您体谅我，让我用这浅陋的方式平复心情。",
    self_punish_protected_msg="勇士们，英雄们，最后再打磨一下自己的武器吧。",
    # 追加禁言时长
    target_ban_duration=lambda: random.randint(30, 80) * 60,
    target_prefix="哭嚎吧，",
    target_suffix=",为你们不堪一击的信念。",
    # 无@目标时对所有被禁言玩家追加禁言
    no_target_duration=lambda: random.randint(20, 40) * 60,
    no_target_msg="是吗，我们做到了吗......我现在，正体会至高的荣誉和幸福。",
    no_target_no_one_msg="转身吧，勇士们。我们已经获得了完美的胜利，现在是该回去享受庆祝的盛典了。",
)


@dataclass
class ShotConfig:
    ban_duration: Callable[[], int]
    hit_msg: str
    miss_texts: list[str]
    misfire_msg: str
    drunk_hit_msg: str


# 开枪：命中则踢人/禁言，喝酒后随机命中多人
SHOT_CFG = ShotConfig(
    ban_duration=lambda: random.randint(5, 20) * 60,
    hit_msg="米诺斯英雄们的故事......有喜剧，便也会有悲剧。舍弃了荣耀，{at}选择回归平凡......",
    miss_texts=[
        "无需退路。",
        "英雄们啊，为这最强大的信念，请站在我们这边。",
        "颤抖吧，在真正的勇敢面前。",
        "哭嚎吧，为你们不堪一击的信念。",
        "现在可没有后悔的余地了。",
        "你将在此跪拜。",
    ],
    misfire_msg="我的手中的这把武器，找了无数工匠都难以修缮如新。不......不该如此......",
    drunk_hit_msg="米诺斯英雄们的故事......有喜剧，便也会有悲剧。舍弃了荣耀，{at}选择回归平凡...... ( {count} / 6 )",
)
