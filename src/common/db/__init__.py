import os
from urllib.parse import quote_plus

from beanie import init_beanie
from pymongo import AsyncMongoClient

from .modules import (
    Answer,
    Ban,
    BlackList,
    BotConfigModule,
    Context,
    GroupConfigModule,
    ImageCache,
    Message,
    SingProgress,
    UserConfigModule,
)


async def init_db(host: str, port: int, user: str, password: str, backend: str | None = None):
    """
    初始化数据库连接

    根据 backend 参数选择数据库后端，默认从环境变量 DB_BACKEND 读取，
    未设置时使用 mongodb。
    """
    if backend is None:
        backend = os.getenv("DB_BACKEND", "mongodb").lower()

    if backend == "mongodb":
        await _init_mongodb(host, port, user, password)
    elif backend == "postgresql":
        raise NotImplementedError(
            "PostgreSQL 后端尚未实现，请使用 DB_BACKEND=mongodb。接口已预留于 src/common/db/repository_pg.py"
        )
    else:
        raise ValueError(f"不支持的数据库后端: {backend}，目前仅支持 mongodb")


async def _init_mongodb(host: str, port: int, user: str, password: str):
    """初始化 MongoDB 连接"""
    if user and password:
        connection_string = f"mongodb://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}"
    else:
        connection_string = f"mongodb://{host}:{port}"
    mongo_client = AsyncMongoClient(connection_string, unicode_decode_error_handler="ignore")
    await init_beanie(
        database=mongo_client["PallasBot"],
        document_models=[
            BotConfigModule,
            GroupConfigModule,
            UserConfigModule,
            Message,
            Context,
            BlackList,
            ImageCache,
        ],
    )
