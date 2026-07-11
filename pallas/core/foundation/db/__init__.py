import asyncio
import os
from collections.abc import Callable
from urllib.parse import quote_plus

from .modules import (
    AdminMember,
    Answer,
    Ban,
    BlackList,
    BotConfigModule,
    Context,
    GroupConfigModule,
    ImageCache,
    Message,
    PallasACL,
    SchemaMigration,
    SingProgress,
    UserConfigModule,
)
from .repository import (
    AclRepository,
    AdminRepository,
    BlackListRepository,
    ConfigRepository,
    ContextRepository,
    ContextRepositoryExistenceMixin,
    ImageCacheRepository,
    MessageRepository,
)
from .runtime import (
    get_db_backend,
    is_mongodb_backend,
    is_postgresql_backend,
    normalize_db_backend_name,
)

CONTEXT_REPO_REGISTRY: dict[str, Callable[[], ContextRepository]] = {}
MESSAGE_REPO_REGISTRY: dict[str, Callable[[], MessageRepository]] = {}
BLACKLIST_REPO_REGISTRY: dict[str, Callable[[], BlackListRepository]] = {}
BOT_CONFIG_REPO_REGISTRY: dict[str, Callable[[], ConfigRepository]] = {}
GROUP_CONFIG_REPO_REGISTRY: dict[str, Callable[[], ConfigRepository]] = {}
USER_CONFIG_REPO_REGISTRY: dict[str, Callable[[], ConfigRepository]] = {}
IMAGE_CACHE_REPO_REGISTRY: dict[str, Callable[[], ImageCacheRepository]] = {}
ADMIN_REPO_REGISTRY: dict[str, Callable[[], AdminRepository]] = {}
ACL_REPO_REGISTRY: dict[str, Callable[[], AclRepository]] = {}

# 数据库初始化函数注册表：后端名称 → 异步初始化函数
INIT_DB_REGISTRY: dict[str, Callable] = {}

_backends_registered: set[str] = set()
_runtime_storage_ensure_lock = asyncio.Lock()
_mongodb_initialized = False


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
    admin_factory: Callable[[], AdminRepository] | None = None,
    acl_factory: Callable[[], AclRepository] | None = None,
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
    if admin_factory is not None:
        ADMIN_REPO_REGISTRY[backend] = admin_factory
    if acl_factory is not None:
        ACL_REPO_REGISTRY[backend] = acl_factory
    _backends_registered.add(backend)


def ensure_backend_registered(backend: str | None = None) -> str:
    """按配置懒注册数据库后端。"""
    name = normalize_db_backend_name(backend or get_db_backend())
    if name in _backends_registered:
        return name
    if name == "mongodb":
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
            admin_factory=make_mongo_admin,
            acl_factory=make_mongo_acl,
        )
    elif name == "postgresql":
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
            admin_factory=make_pg_admin,
            acl_factory=make_pg_acl,
        )
    else:
        raise ValueError(f"不支持的数据库后端: {name}，已注册的后端: {sorted(_backends_registered)}")
    return name


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


def make_mongo_admin() -> AdminRepository:
    from .repository_impl import MongoAdminRepository

    return MongoAdminRepository()


def make_mongo_acl() -> AclRepository:
    from .repository_impl import MongoAclRepository

    return MongoAclRepository()


def _cfg(key: str, default: str = "") -> str:
    try:
        import nonebot

        val = getattr(nonebot.get_driver().config, key.lower(), None)
        if val is not None:
            return str(val)
    except Exception:
        pass
    return os.getenv(key.upper(), default)


def _cfg_int(key: str, default: int) -> int:
    raw = _cfg(key, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        return int(default)


def pg_session_server_settings() -> dict[str, str]:
    """PG 会话级默认参数：即使用户未手调数据库，也尽量避免长事务挂死连接。"""
    idle_in_tx_ms = max(1000, _cfg_int("PG_IDLE_IN_TRANSACTION_TIMEOUT_MS", 15000))
    app_name = (_cfg("PG_APPLICATION_NAME", "PallasBot") or "PallasBot").strip() or "PallasBot"
    return {
        "application_name": app_name,
        "idle_in_transaction_session_timeout": str(idle_in_tx_ms),
    }


async def init_mongodb_db() -> None:
    """初始化 MongoDB 连接。"""
    global _mongodb_initialized
    from beanie import init_beanie
    from nonebot.log import logger
    from pymongo import AsyncMongoClient

    host = _cfg("MONGO_HOST", "127.0.0.1")
    port = int(_cfg("MONGO_PORT", "27017"))
    user = _cfg("MONGO_USER", "").strip()
    password = _cfg("MONGO_PASSWORD", "")
    db_name = _cfg("MONGO_DB", "PallasBot")
    auth_source = (_cfg("MONGO_AUTH_SOURCE", "") or db_name).strip() or db_name

    if user and password:
        connection_string = (
            f"mongodb://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/?authSource={quote_plus(auth_source)}"
        )
    else:
        connection_string = f"mongodb://{host}:{port}"
        if user or password:
            logger.warning("数据库：MONGO 用户名与密码须同时配置，将尝试无认证连接")

    logger.info("数据库：连接 MongoDB {}:{} db={}", host, port, db_name)
    mongo_client = AsyncMongoClient(
        connection_string,
        unicode_decode_error_handler="ignore",
        serverSelectionTimeoutMS=8000,
    )
    try:
        await mongo_client.admin.command("ping")
    except Exception as exc:
        err = str(exc)
        if "requires authentication" in err or "code': 13" in err or "Unauthorized" in err:
            raise RuntimeError(
                f"MongoDB {host}:{port} 需要认证：请在 .env 配置 MONGO_USER、MONGO_PASSWORD，"
                f"必要时设置 MONGO_AUTH_SOURCE（当前默认 {auth_source}）；"
                f"或改用 DB_BACKEND=postgresql。原始错误: {err}"
            ) from exc
        raise
    await init_beanie(
        database=mongo_client[db_name],
        document_models=[
            BotConfigModule,
            GroupConfigModule,
            UserConfigModule,
            Message,
            Context,
            BlackList,
            ImageCache,
            SchemaMigration,
            AdminMember,
            PallasACL,
        ],
    )
    _mongodb_initialized = True
    logger.info("数据库：MongoDB {} 已连接", db_name)


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


def make_pg_admin() -> AdminRepository:
    from .repository_pg import PgAdminRepository

    return PgAdminRepository()


def make_pg_acl() -> AclRepository:
    from .repository_pg import PgAclRepository

    return PgAclRepository()


async def init_postgresql_db() -> None:
    """初始化 PostgreSQL 连接"""
    import re

    from nonebot.log import logger
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from .repository_pg import dispose_pg, init_pg

    pg_host_raw = _cfg("PG_HOST", "")
    if pg_host_raw:
        host = pg_host_raw
    else:
        host = _cfg("MONGO_HOST", "127.0.0.1")
        if host != "127.0.0.1":
            logger.warning("数据库：PG_HOST 未设置，回退 MONGO_HOST={}", host)
    port = int(_cfg("PG_PORT", "5432"))
    user = _cfg("PG_USER", "")
    password = _cfg("PG_PASSWORD", "")
    db_name = _cfg("PG_DB", "PallasBot")
    if not re.match(r"^[A-Za-z0-9_\-]+$", db_name):
        raise ValueError(f"非法的 PG_DB: {db_name!r}")
    auth = f"{quote_plus(user)}:{quote_plus(password)}@" if user and password else ""
    base_url = f"postgresql+asyncpg://{auth}{host}:{port}"

    pool_size = int(_cfg("PG_POOL_SIZE", "10"))
    max_overflow = int(_cfg("PG_MAX_OVERFLOW", "20"))
    pool_recycle = int(_cfg("PG_POOL_RECYCLE", "1800"))

    logger.info("数据库：连接 PostgreSQL {}:{} db={}", host, port, db_name)

    admin_engine = create_async_engine(f"{base_url}/postgres", isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            result = await conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :db"), {"db": db_name})
            if result.scalar() is None:
                logger.info("数据库：PostgreSQL {} 不存在，正在创建", db_name)
                # PG 不支持给 identifier 绑占位符，只能拼接；上面 [A-Za-z0-9_-]
                # 的正则已保证 db_name 无注入风险。
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))  # noqa: S608
                logger.info("数据库：PostgreSQL {} 已创建", db_name)
    finally:
        await admin_engine.dispose()

    engine = create_async_engine(
        f"{base_url}/{db_name}",
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
        pool_pre_ping=True,
        connect_args={"server_settings": pg_session_server_settings()},
    )
    await init_pg(engine)
    logger.info(
        "数据库：PostgreSQL {} 已连接 pool={}+{} recycle={}s",
        db_name,
        pool_size,
        max_overflow,
        pool_recycle,
    )
    try:
        from pallas.core.platform.shard.observability import log_pg_pool_warning_if_needed

        log_pg_pool_warning_if_needed()
    except Exception:
        pass

    try:
        import nonebot

        from pallas.core.foundation.db.pool_diagnostics import bind_pg_pool_diagnostics, start_pg_pool_diagnostics_task

        bind_pg_pool_diagnostics()
        start_pg_pool_diagnostics_task()
        driver = nonebot.get_driver()

        @driver.on_shutdown
        async def _dispose_pg():
            await dispose_pg()

    except Exception:
        pass


# 工厂函数


def make_local_context_repository() -> ContextRepository:
    """本地业务库 ContextRepository。"""
    backend = ensure_backend_registered()
    return CONTEXT_REPO_REGISTRY[backend]()


def make_context_repository() -> ContextRepository:
    """根据当前配置的后端返回 ContextRepository；启用语料多源时用 Composite 包装。"""
    from pallas.product.corpus.factory import maybe_wrap_composite

    return maybe_wrap_composite(make_local_context_repository())


def make_message_repository() -> MessageRepository:
    """根据当前配置的后端，返回对应的 MessageRepository 实例。"""
    backend = ensure_backend_registered()
    return MESSAGE_REPO_REGISTRY[backend]()


def make_blacklist_repository() -> BlackListRepository:
    """根据当前配置的后端，返回对应的 BlackListRepository 实例。"""
    backend = ensure_backend_registered()
    return BLACKLIST_REPO_REGISTRY[backend]()


def make_bot_config_repository() -> ConfigRepository:
    """根据当前配置的后端，返回 BotConfig Repository 实例。"""
    backend = ensure_backend_registered()
    return BOT_CONFIG_REPO_REGISTRY[backend]()


async def ensure_bot_config_row(bot_id: int) -> bool:
    """协议连接时为该 QQ 确保 bot_config 行存在。返回是否新建。"""
    repo = make_bot_config_repository()
    _, created = await repo.get_or_create(bot_id, disabled_plugins=[])
    return created


def make_group_config_repository() -> ConfigRepository:
    """根据当前配置的后端，返回 GroupConfig Repository 实例。"""
    backend = ensure_backend_registered()
    return GROUP_CONFIG_REPO_REGISTRY[backend]()


def make_user_config_repository() -> ConfigRepository:
    """根据当前配置的后端，返回 UserConfig Repository 实例。"""
    backend = ensure_backend_registered()
    return USER_CONFIG_REPO_REGISTRY[backend]()


def make_image_cache_repository() -> ImageCacheRepository:
    """根据当前配置的后端，返回 ImageCache Repository 实例。"""
    backend = ensure_backend_registered()
    return IMAGE_CACHE_REPO_REGISTRY[backend]()


def make_admin_repository() -> AdminRepository:
    """根据当前配置的后端，返回 AdminRepository。"""
    backend = ensure_backend_registered()
    if backend not in ADMIN_REPO_REGISTRY:
        raise ValueError(f"后端 {backend!r} 未注册 AdminRepository")
    return ADMIN_REPO_REGISTRY[backend]()


def make_acl_repository() -> AclRepository:
    """根据当前配置的后端，返回 AclRepository。"""
    backend = ensure_backend_registered()
    if backend not in ACL_REPO_REGISTRY:
        raise ValueError(f"后端 {backend!r} 未注册 AclRepository")
    return ACL_REPO_REGISTRY[backend]()


async def init_db(backend: str | None = None) -> None:
    """
    初始化数据库连接。

    根据 backend 参数选择后端，未传入时从环境变量 DB_BACKEND 读取，
    默认使用 mongodb。连接参数均从环境变量读取。
    """
    backend = ensure_backend_registered(backend)
    await INIT_DB_REGISTRY[backend]()


def runtime_storage_ready(backend: str | None = None) -> bool:
    name = normalize_db_backend_name(backend or get_db_backend())
    if name == "postgresql":
        from .repository_pg import is_pg_initialized

        return is_pg_initialized()
    if name == "mongodb":
        return _mongodb_initialized
    return False


async def ensure_runtime_storage_ready(backend: str | None = None) -> bool:
    name = normalize_db_backend_name(backend or get_db_backend())
    if runtime_storage_ready(name):
        return False
    async with _runtime_storage_ensure_lock:
        if runtime_storage_ready(name):
            return False
        await init_db(name)
        return True
