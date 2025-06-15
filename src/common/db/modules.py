import time
from datetime import datetime, timedelta

import pymongo
from beanie import Document
from pydantic import BaseModel, Field, PrivateAttr
from pymongo import IndexModel


class SingProgress(BaseModel):
    song_id: str
    chunk_index: int
    key: int


class BotConfigModule(Document):
    account: int = Field(...)
    admins: list[int] = Field(default_factory=list)
    auto_accept: bool = Field(default=False)
    security: bool = Field(default=False)
    taken_name: dict[int, int] = Field(default_factory=dict)
    drunk: dict[int, float] = Field(default_factory=dict)
    sleep: dict[int, float] = Field(default_factory=dict)

    class Settings:
        collection = "config"
        use_cache = True
        cache_expiration_time = timedelta(minutes=30)
        cache_capacity = 100


class GroupConfigModule(Document):
    group_id: int = Field(...)
    roulette_mode: int
    banned: bool
    sing_progress: SingProgress

    class Settings:
        collection = "group_config"
        use_cache = True
        cache_expiration_time = timedelta(minutes=30)
        cache_capacity = 10000


class UserConfigModule(Document):
    user_id: int = Field(...)
    banned: bool = False

    class Settings:
        collection = "user_config"


class Message(Document):
    group_id: int = Field(...)
    user_id: int = Field(...)
    bot_id: int = Field(...)
    raw_message: str = Field(...)
    is_plain_text: bool = True
    plain_text: str = Field(...)
    keywords: str = Field(...)
    time: int = Field(default_factory=lambda: int(time.time()))

    class Settings:
        collection = "message"
        indexes = [IndexModel([("time", pymongo.DESCENDING)], name="time_index")]


class Ban(BaseModel):
    keywords: str = Field(...)
    group_id: int = Field(...)
    reason: str = Field(...)
    time: int = Field(default_factory=lambda: int(time.time()))


class Answer(BaseModel):
    _topical: int = PrivateAttr(default=0)
    keywords: str = Field(...)
    group_id: int = Field(...)
    count: int = 1
    time: int = Field(default_factory=lambda: int(time.time()))
    messages: list[str] = Field(default_factory=list)


class Context(Document):
    keywords: str = Field(...)
    time: int = Field(default_factory=lambda: int(time.time()))
    count: int = 1
    answers: list[Answer] = Field(default_factory=list)
    ban: list[Ban] = Field(default_factory=list)
    clear_time: int = 0

    class Settings:
        collection = "context"
        indexes = [
            IndexModel([("keywords", pymongo.HASHED)], name="keywords_index"),
            IndexModel([("count", pymongo.DESCENDING)], name="count_index"),
            IndexModel([("time", pymongo.DESCENDING)], name="time_index"),
            IndexModel(
                [("answers.group_id", pymongo.TEXT), ("answers.keywords", pymongo.TEXT)],
                name="answers_index",
                default_language="none",
            ),
        ]


class BlackList(Document):
    group_id: int = Field(...)
    answers: list[str] = Field(default_factory=list)
    answers_reserve: list[str] = Field(default_factory=list)

    class Settings:
        collection = "blacklist"
        indexes = [IndexModel([("group_id", pymongo.HASHED)], name="group_index")]


class BaseImageCache(Document):
    date: int = Field(default_factory=lambda: int(str(datetime.now().date()).replace("-", "")))

    class Settings:
        use_state_management = True
        state_management_replace_objects = True

    async def save(self, *args, **kwargs):
        self.date = int(str(datetime.now().date()).replace("-", ""))
        return await super().save(*args, **kwargs)


class ImageCache(BaseImageCache):
    cq_code: str = Field(...)
    base64_data: str | None = Field(default=None)
    ref_times: int = Field(default=1)

    class Settings:
        collection = "image_cache"
        indexes = [IndexModel([("cq_code", pymongo.HASHED)], name="cq_code_index")]


__all__ = [
    "SingProgress",
    "BotConfigModule",
    "GroupConfigModule",
    "UserConfigModule",
    "Message",
    "Ban",
    "Answer",
    "Context",
    "BlackList",
    "ImageCache",
]
