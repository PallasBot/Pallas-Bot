from pydantic import BaseModel, Field

LengthPref = str
Tone = str
ArchetypeName = str


class ResolvedPersona(BaseModel):
    """解析后的接话风格参数，供复读选句与主动发言使用。"""

    source: str = "auto"
    preset_label: str = "自动"
    archetype: ArchetypeName = ""
    tone: Tone = "neutral"
    reply_bias: float = Field(default=1.0, ge=0.5, le=2.0)
    speak_bias: float = Field(default=1.0, ge=0.5, le=2.0)
    length_pref: LengthPref = "any"
    activity_reply_bias: float = Field(
        default=0.5,
        ge=0.25,
        le=1.0,
        description="同群独占活动进行中时，接话阈值额外倍率（越小越少插话）",
    )
    chaos_bias: float = Field(default=0.0, ge=0.0, le=1.0)
    warmth: float = Field(default=0.0, ge=-1.0, le=1.0)
    assertiveness: float = Field(default=0.0, ge=-1.0, le=1.0)
    harsh_msg_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    polite_msg_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    bluntness: float = Field(default=0.0, ge=-1.0, le=1.0)
    msgs_per_hour_active: float = Field(default=0.0, ge=0.0)
    activity_level: str = "normal"
    cross_group_bias_mul: float = Field(default=1.0, ge=0.5, le=1.5)
