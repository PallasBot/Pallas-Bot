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
from .repository import (
    BlackListRepository,
    ConfigRepository,
    ContextRepository,
    ImageCacheRepository,
    MessageRepository,
)


def get_db_backend() -> str:
    """读取当前配置的数据库后端名称，默认为 mongodb。"""
    return os.getenv("DB_BACKEND", "mongodb").lower()


CONTEXT_REPO_REGISTRY: dict[str, Callable[[], ContextRepository]] = {}
MESSAGE_REPO_REGISTRY: dict[str, Callable[[], MessageRepository]] = {}
BLACKLIST_REPO_REGISTRY: dict[str, Callable[[], BlackListRepository]] = {}
BOT_CONFIG_REPO_REGISTRY: dict[str, Callable[[], ConfigRepository]] = {}
GROUP_CONFIG_REPO_REGISTRY: dict[str, Callable[[], ConfigRepository]] = {}
USER_CONFIG_REPO_REGISTRY: dict[str, Callable[[], ConfigRepository]] = {}
IMAGE_CACHE_REPO_REGISTRY: dict[str, Callable[[], ImageCacheRepository]] = {}

# 数据库初始化函数注册表：后端名称 → 异步初始化函数
INIT_DB_REGISTRY: dict[str, Callable] = {}


def register_backend(
    backend: str,
    context_factory: Callable[[], ContextRepository],
    message_factory: Callable[[], MessageRepository],
    blacklist_factory: Callable[[], BlackListRepository],
    init_func: Callable,
    *,
    bot_config_factory: Callable[[], ConfigRepository] | None = None,
    group_config_factory: Callable[[], ConfigRepository] | None = None,
    user_config_factory: Callable[[], ConfigRepository] | None = None,
    image_cache_factory: Callable[[], ImageCacheRepository] | None = None,
) -> None:
    """
    注册一个数据库后端。

    核心三项 repo (context/message/blacklist) 为必填，其余为可选；未提供的
    后端在运行时调用对应工厂将抛错。
    """
    CONTEXT_REPO_REGISTRY[backend] = context_factory
    MESSAGE_REPO_REGISTRY[backend] = message_factory
    BLACKLIST_REPO_REGISTRY[backend] = blacklist_factory
    INIT_DB_REGISTRY[backend] = init_func
    if bot_config_factory is not None:
        BOT_CONFIG_REPO_REGISTRY[backend] = bot_config_factory
    if group_config_factory is not None:
        GROUP_CONFIG_REPO_REGISTRY[backend] = group_config_factory
    if user_config_factory is not None:
        USER_CONFIG_REPO_REGISTRY[backend] = user_config_factory
    if image_cache_factory is not None:
        IMAGE_CACHE_REPO_REGISTRY[backend] = image_cache_factory


def make_mongo_context() -> ContextRepository:
    from .repository_impl import MongoContextRepository

    return MongoContextRepository()


def make_mongo_message() -> MessageRepository:
    from .repository_impl import MongoMessageRepository

    return MongoMessageRepository()


def make_mongo_blacklist() -> BlackListRepository:
    from .repository_impl import MongoBlackListRepository

    return MongoBlackListRepository()


def make_mongo_bot_config() -> ConfigRepository:
    from .repository_impl import MongoConfigRepository

    return MongoConfigRepository(BotConfigModule, "account")


def make_mongo_group_config() -> ConfigRepository:
    from .repository_impl import MongoConfigRepository

    return MongoConfigRepository(GroupConfigModule, "group_id")


def make_mongo_user_config() -> ConfigRepository:
    from .repository_impl import MongoConfigRepository

    return MongoConfigRepository(UserConfigModule, "user_id")


def make_mongo_image_cache() -> ImageCacheRepository:
    from .repository_impl import MongoImageCacheRepository

    return MongoImageCacheRepository()


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


def make_pg_bot_config() -> ConfigRepository:
    from .repository_pg import PgConfigRepository

    return PgConfigRepository("bot_config", "account")


def make_pg_group_config() -> ConfigRepository:
    from .repository_pg import PgConfigRepository

    return PgConfigRepository("group_config", "group_id")


def make_pg_user_config() -> ConfigRepository:
    from .repository_pg import PgConfigRepository

    return PgConfigRepository("user_config", "user_id")


def make_pg_image_cache() -> ImageCacheRepository:
    from .repository_pg import PgImageCacheRepository

    return PgImageCacheRepository()


async def init_postgresql_db(host: str, port: int, user: str, password: str) -> None:
    """
    初始化 PostgreSQL 连接（预留骨架，尚未实现）。

    当前 PG 后端仅包含接口骨架（repository_pg.Pg*Repository），数据库建库、
    建表、ORM 映射等实际实现留给后续 PR。一旦实现完整，再填充此函数。
    """
    raise NotImplementedError(
        "PostgreSQL 后端尚未实现。Repository 抽象层已就绪，但 PG 侧实现仅为骨架；"
        "若要启用，请先完成 src/common/db/repository_pg.py 并补齐 pg optional-dependency。"
    )


register_backend(
    "mongodb",
    make_mongo_context,
    make_mongo_message,
    make_mongo_blacklist,
    init_mongodb_db,
    bot_config_factory=make_mongo_bot_config,
    group_config_factory=make_mongo_group_config,
    user_config_factory=make_mongo_user_config,
    image_cache_factory=make_mongo_image_cache,
)

register_backend(
    "postgresql",
    make_pg_context,
    make_pg_message,
    make_pg_blacklist,
    init_postgresql_db,
    bot_config_factory=make_pg_bot_config,
    group_config_factory=make_pg_group_config,
    user_config_factory=make_pg_user_config,
    image_cache_factory=make_pg_image_cache,
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


def make_bot_config_repository() -> ConfigRepository:
    """根据当前配置的后端，返回 BotConfig Repository 实例。"""
    backend = get_db_backend()
    if backend not in BOT_CONFIG_REPO_REGISTRY:
        raise ValueError(f"后端 {backend} 未注册 BotConfig Repository，已注册：{list(BOT_CONFIG_REPO_REGISTRY)}")
    return BOT_CONFIG_REPO_REGISTRY[backend]()


def make_group_config_repository() -> ConfigRepository:
    """根据当前配置的后端，返回 GroupConfig Repository 实例。"""
    backend = get_db_backend()
    if backend not in GROUP_CONFIG_REPO_REGISTRY:
        raise ValueError(f"后端 {backend} 未注册 GroupConfig Repository，已注册：{list(GROUP_CONFIG_REPO_REGISTRY)}")
    return GROUP_CONFIG_REPO_REGISTRY[backend]()


def make_user_config_repository() -> ConfigRepository:
    """根据当前配置的后端，返回 UserConfig Repository 实例。"""
    backend = get_db_backend()
    if backend not in USER_CONFIG_REPO_REGISTRY:
        raise ValueError(f"后端 {backend} 未注册 UserConfig Repository，已注册：{list(USER_CONFIG_REPO_REGISTRY)}")
    return USER_CONFIG_REPO_REGISTRY[backend]()


def make_image_cache_repository() -> ImageCacheRepository:
    """根据当前配置的后端，返回 ImageCache Repository 实例。"""
    backend = get_db_backend()
    if backend not in IMAGE_CACHE_REPO_REGISTRY:
        raise ValueError(f"后端 {backend} 未注册 ImageCache Repository，已注册：{list(IMAGE_CACHE_REPO_REGISTRY)}")
    return IMAGE_CACHE_REPO_REGISTRY[backend]()


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
