import random
from pathlib import Path

voice_set = {
    "任命助理",
    "交谈1",
    "交谈2",
    "交谈3",
    "晋升后交谈1",
    "晋升后交谈2",
    "信赖提升后交谈1",
    "信赖提升后交谈2",
    "信赖提升后交谈3",
    "闲置",
    "干员报到",
    "精英化晋升1",
    "精英化晋升2",
    "编入队伍",
    "任命队长",
    "戳一下",
    "信赖触摸",
    "问候",
}


voices_source = "resource/voices"


def get_voice_filepath(operator, voice_name) -> Path | None:
    if voice_name not in voice_set:
        return None
    f = Path(f"{voices_source}/{operator}/{voice_name}.wav")
    return f if f.exists() else None


def get_random_voice(operator, ranges) -> Path | None:
    key = random.choice([r for r in ranges if r in voice_set])
    return get_voice_filepath(operator, key)
