import os
from collections.abc import Callable
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
from .repository import BlackListRepository, ContextRepository, MessageRepository


def get_db_backend() -> str:
    """读取当前配置的数据库后端名称，默认为 mongodb。"""
    return os.getenv("DB_BACKEND", "mongodb").lower()


CONTEXT_REPO_REGISTRY: dict[str, Callable[[], ContextRepository]] = {}
MESSAGE_REPO_REGISTRY: dict[str, Callable[[], MessageRepository]] = {}
BLACKLIST_REPO_REGISTRY: dict[str, Callable[[], BlackListRepository]] = {}

# 数据库初始化函数注册表：后端名称 → 异步初始化函数
INIT_DB_REGISTRY: dict[str, Callable] = {}


def register_backend(
    backend: str,
    context_factory: Callable[[], ContextRepository],
    message_factory: Callable[[], MessageRepository],
    blacklist_factory: Callable[[], BlackListRepository],
    init_func: Callable,
) -> None:
    """
    注册一个数据库后端。
    """
    CONTEXT_REPO_REGISTRY[backend] = context_factory
    MESSAGE_REPO_REGISTRY[backend] = message_factory
    BLACKLIST_REPO_REGISTRY[backend] = blacklist_factory
    INIT_DB_REGISTRY[backend] = init_func


def make_mongo_context() -> ContextRepository:
    from .repository_impl import MongoContextRepository

    return MongoContextRepository()


def make_mongo_message() -> MessageRepository:
    from .repository_impl import MongoMessageRepository

    return MongoMessageRepository()


def make_mongo_blacklist() -> BlackListRepository:
    from .repository_impl import MongoBlackListRepository

    return MongoBlackListRepository()


async def init_mongodb_db(host: str, port: int, user: str, password: str) -> None:
    """初始化 MongoDB 连接。"""
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


def make_pg_context() -> ContextRepository:
    from .repository_pg import PgContextRepository

    return PgContextRepository()


def make_pg_message() -> MessageRepository:
    from .repository_pg import PgMessageRepository

    return PgMessageRepository()


def make_pg_blacklist() -> BlackListRepository:
    from .repository_pg import PgBlackListRepository

    return PgBlackListRepository()


async def init_postgresql_db(host: str, port: int, user: str, password: str) -> None:
    """初始化 PostgreSQL 连接，若目标数据库不存在则自动创建。"""
    import re

    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.sql.elements import quoted_name

        from .repository_pg import init_pg
    except ImportError as e:
        raise ImportError("PostgreSQL 后端需要额外依赖，请执行：uv run --extra pg") from e

    db = os.getenv("PG_DB", "PallasBot")

    # 校验数据库名，仅允许字母、数字、下划线和连字符，防止 SQL 注入
    if not re.match(r"^[A-Za-z0-9_\-]+$", db):
        raise ValueError(f"非法的数据库名称: {db!r}，仅允许字母、数字、下划线和连字符")

    # 使用 SQLAlchemy 连接默认库，检查并按需创建目标数据库
    if user and password:
        admin_dsn = f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/postgres"
    else:
        admin_dsn = f"postgresql+asyncpg://{host}:{port}/postgres"

    # AUTOCOMMIT 模式：CREATE DATABASE 不能在事务块内执行
    admin_engine = create_async_engine(admin_dsn, echo=False, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as admin_conn:
            exists = await admin_conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :db"),
                {"db": db},
            )
            if not exists:
                # CREATE DATABASE 不支持参数化查询
                # 使用 SQLAlchemy quoted_name 对标识符进行安全引用
                db_identifier = quoted_name(db, quote=True)
                await admin_conn.execute(text("CREATE DATABASE " + db_identifier))
    finally:
        await admin_engine.dispose()

    if user and password:
        dsn = f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{db}"
    else:
        dsn = f"postgresql+asyncpg://{host}:{port}/{db}"

    engine = create_async_engine(dsn, echo=False)
    await init_pg(engine)


register_backend(
    "mongodb",
    make_mongo_context,
    make_mongo_message,
    make_mongo_blacklist,
    init_mongodb_db,
)

register_backend(
    "postgresql",
    make_pg_context,
    make_pg_message,
    make_pg_blacklist,
    init_postgresql_db,
)


# 工厂函数


def make_context_repository() -> ContextRepository:
    """根据当前配置的后端，返回对应的 ContextRepository 实例。"""
    backend = get_db_backend()
    if backend not in CONTEXT_REPO_REGISTRY:
        raise ValueError(f"不支持的数据库后端: {backend}，已注册的后端: {list(CONTEXT_REPO_REGISTRY)}")
    return CONTEXT_REPO_REGISTRY[backend]()


def make_message_repository() -> MessageRepository:
    """根据当前配置的后端，返回对应的 MessageRepository 实例。"""
    backend = get_db_backend()
    if backend not in MESSAGE_REPO_REGISTRY:
        raise ValueError(f"不支持的数据库后端: {backend}，已注册的后端: {list(MESSAGE_REPO_REGISTRY)}")
    return MESSAGE_REPO_REGISTRY[backend]()


def make_blacklist_repository() -> BlackListRepository:
    """根据当前配置的后端，返回对应的 BlackListRepository 实例。"""
    backend = get_db_backend()
    if backend not in BLACKLIST_REPO_REGISTRY:
        raise ValueError(f"不支持的数据库后端: {backend}，已注册的后端: {list(BLACKLIST_REPO_REGISTRY)}")
    return BLACKLIST_REPO_REGISTRY[backend]()


async def init_db(host: str, port: int, user: str, password: str, backend: str | None = None) -> None:
    """
    初始化数据库连接。

    根据 backend 参数选择后端，未传入时从环境变量 DB_BACKEND 读取，
    默认使用 mongodb。新增后端只需调用 register_backend() 注册，无需修改此函数。
    """
    if backend is None:
        backend = get_db_backend()

    if backend not in INIT_DB_REGISTRY:
        raise ValueError(f"不支持的数据库后端: {backend}，已注册的后端: {list(INIT_DB_REGISTRY)}")

    await INIT_DB_REGISTRY[backend](host, port, user, password)
