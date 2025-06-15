from pydantic import BaseModel


class Config(BaseModel, extra="ignore"):
    # answer 相关阈值，值越大，牛牛废话越少；越小，牛牛废话越多
    answer_threshold: int = 3
    # answer 阈值权重
    answer_threshold_weights: list[int] = [7, 23, 70]
    # 上下文联想，记录多少个关键词（每个群）
    topics_size: int = 16
    # 上下文命中后，额外的权重系数
    topics_importance: int = 10000
    # N 个群有相同的回复，就跨群作为全局回复
    cross_group_threshold: int = 2
    # 复读的阈值，群里连续多少次有相同的发言，就复读
    repeat_threshold: int = 3
    # 主动发言的阈值，越小废话越多
    speak_threshold: int = 5
    # 说过的话，接下来多少次不再说
    duplicate_reply: int = 10
    # 按逗号分割回复语的概率
    split_probability: float = 0.5
    # 喝醉之后，超过多长的文本全部转换成语音发送
    drunk_tts_threshold: int = 6
    # 连续主动说话的概率
    speak_continuously_probability: float = 0.5
    # 主动说话加上随机戳一戳群友的概率
    speak_poke_probability: float = 0.6
    # 连续主动说话最多几句话
    speak_continuously_max_len: int = 2
    # 每隔多久进行一次持久化 ( 秒 )
    save_time_threshold: int = 3600
    # 单个群超过多少条聊天记录就进行一次持久化，与时间是或的关系
    save_count_threshold: int = 1000
    # 保存时，给内存中保留的大小
    save_reserved_size: int = 100
