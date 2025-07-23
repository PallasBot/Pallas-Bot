import asyncio
import time
from typing import Any

from beanie import Document
from pydantic import BaseModel

from src.common.db import BotConfigModule, GroupConfigModule, SingProgress, UserConfigModule

KEY_JOINER = "."


class Config:
    _in_memory_cache: dict | None = None
    _module_class: Document | None = None
    _primary_key: str | None = None
    _lock: asyncio.Lock | None = None

    async def _find(self, key: str) -> Any:
        config_document = await self._module_class.find_one(self._db_filter)
        return getattr(config_document, key) if config_document else None

    async def _find_in_memory(self, key: str) -> Any:
        async with self._lock:
            if self._document_key not in self._in_memory_cache:
                self._in_memory_cache[self._document_key] = {}
            cache = self._in_memory_cache[self._document_key]
            return cache.get(key)

    async def _update(self, key: str, value: Any) -> None:
        await self._module_class.find_one(self._db_filter).upsert(
            {"$set": {key: value}}, on_insert=self._module_class(**{self._primary_key: self._document_key, key: value})
        )

    async def _update_in_memory(self, key: str, value: Any) -> None:
        async with self._lock:
            if self._document_key not in self._in_memory_cache:
                self._in_memory_cache[self._document_key] = {}
            cache = self._in_memory_cache[self._document_key]
            cache[key] = value

    @classmethod
    async def _update_all(cls, key: str, value: Any) -> None:
        for cache_key in cls._in_memory_cache:
            if cache_key.startswith(key):
                async with cls._lock:
                    cls._in_memory_cache[cache_key] = value

    def __init__(self, module_class: Document, primary_key: str, key_id: int) -> None:
        self._document_key = key_id
        self._db_filter = {primary_key: key_id}
        self.__class__._module_class = module_class
        self.__class__._primary_key = primary_key
        if self.__class__._in_memory_cache is None:
            self.__class__._in_memory_cache = {}
        if self.__class__._lock is None:
            self.__class__._lock = asyncio.Lock()


class BotConfig(Config):
    def __init__(self, bot_id: int, group_id: int = 0, cooldown: int = 5) -> None:
        super().__init__(module_class=BotConfigModule, primary_key="account", key_id=bot_id)

        self.bot_id = bot_id
        self.group_id = group_id
        self.cooldown = cooldown

    async def security(self) -> bool:
        """
        账号是否安全（不处于风控等异常状态）
        """
        security = await self._find("security")
        return True if security else False

    async def auto_accept(self) -> bool:
        """
        是否自动接受加群、加好友请求
        """
        accept = await self._find("auto_accept")
        return True if accept else False

    async def is_admin_of_bot(self, user_id: int) -> bool:
        """
        是否是管理员
        """
        admins = await self._find("admins")
        return user_id in admins if admins else False

    async def is_cooldown(self, action_type: str) -> bool:
        """
        是否冷却完成
        """
        cd = await self._find_in_memory(f"cooldown{KEY_JOINER}{action_type}{KEY_JOINER}{self.group_id}")
        return cd + self.cooldown < time.time() if cd else True

    async def refresh_cooldown(self, action_type: str) -> None:
        """
        刷新冷却时间
        """
        await self._update_in_memory(f"cooldown{KEY_JOINER}{action_type}{KEY_JOINER}{self.group_id}", time.time())

    async def reset_cooldown(self, action_type: str) -> None:
        """
        重置冷却时间
        """
        await self._update_in_memory(f"cooldown{KEY_JOINER}{action_type}{KEY_JOINER}{self.group_id}", 0)

    _drink_handlers = []
    _sober_up_handlers = []

    @classmethod
    def handle_drink(cls, func):
        """
        注册喝酒回调函数
        """
        cls._drink_handlers.append(func)
        return func

    @classmethod
    def handle_sober_up(cls, func):
        """
        注册醒酒回调函数
        """
        cls._sober_up_handlers.append(func)
        return func

    async def drink(self) -> None:
        """
        喝酒功能，增加牛牛的混沌程度（bushi
        """
        value = await self.drunkenness()
        value += 1
        await self._update_in_memory(f"drunk{KEY_JOINER}{self.group_id}", value)
        for on_drink in self._drink_handlers:
            on_drink(self.bot_id, self.group_id, value)

    async def sober_up(self) -> bool:
        """
        醒酒，降低醉酒程度，返回是否完全醒酒
        """
        value = await self.drunkenness()
        value -= 1
        await self._update_in_memory(f"drunk{KEY_JOINER}{self.group_id}", value)
        if value > 0:
            return False
        for on_sober_up in self._sober_up_handlers:
            await on_sober_up(self.bot_id, self.group_id, value)
        return True

    async def drunkenness(self) -> int:
        """
        获取醉酒程度
        """
        value = await self._find_in_memory(f"drunk{KEY_JOINER}{self.group_id}")
        return value or 0

    @classmethod
    async def fully_sober_up(cls) -> None:
        """
        完全醒酒
        """
        await cls._update_all("drunk", 0)

    async def is_sleep(self) -> bool:
        """
        牛牛睡了么？
        """
        value = await self._find_in_memory(f"sleep{KEY_JOINER}{self.group_id}")
        return value > time.time() if value else False

    async def sleep(self, seconds: int) -> None:
        """
        牛牛睡觉
        """
        await self._update_in_memory(f"sleep{KEY_JOINER}{self.group_id}", time.time() + seconds)

    async def taken_name(self) -> int | None:
        """
        返回在该群夺舍的账号
        """
        user_ids = await self._find("taken_name")
        user_id = user_ids.get(self.group_id) if user_ids else None
        return user_id

    async def update_taken_name(self, user_id: int) -> None:
        """
        更新夺舍的账号
        """
        user_ids = await self._find("taken_name")
        if user_ids is None:
            user_ids = {}
        user_ids[self.group_id] = user_id
        await self._update("taken_name", user_ids)


class GroupConfig(Config):
    def __init__(self, group_id: int, cooldown: int = 5) -> None:
        super().__init__(module_class=GroupConfigModule, primary_key="group_id", key_id=group_id)

        self.group_id = group_id
        self.cooldown = cooldown

    async def roulette_mode(self) -> int:
        """
        获取轮盘模式

        :return: 0 踢人 1 禁言
        """
        mode = await self._find("roulette_mode")
        return mode if mode is not None else 1

    async def set_roulette_mode(self, mode: int) -> None:
        """
        设置轮盘模式

        :param mode: 0 踢人 1 禁言
        """
        await self._update("roulette_mode", mode)

    async def ban(self) -> None:
        """
        拉黑该群
        """
        await self._update("banned", True)

    async def is_banned(self) -> bool:
        """
        群是否被拉黑
        """
        banned = await self._find("banned")
        return True if banned else False

    async def is_cooldown(self, action_type: str) -> bool:
        """
        是否冷却完成
        """
        cd = await self._find_in_memory(f"cooldown{KEY_JOINER}{action_type}")
        return cd + self.cooldown < time.time() if cd else True

    async def refresh_cooldown(self, action_type: str) -> None:
        """
        刷新冷却时间
        """
        await self._update_in_memory(f"cooldown{KEY_JOINER}{action_type}", time.time())

    async def reset_cooldown(self, action_type: str) -> None:
        """
        重置冷却时间
        """
        await self._update_in_memory(f"cooldown{KEY_JOINER}{action_type}", 0)

    async def sing_progress(self) -> SingProgress | None:
        """
        获取歌曲进度
        """
        return await self._find("sing_progress")

    async def update_sing_progress(self, progress: SingProgress) -> None:
        """
        更新歌曲进度
        """
        await self._update("sing_progress", progress)

    async def get_fresh_group_config_module(self: int):
        """
        刷新配置
        """
        client = GroupConfigModule.get_motor_collection().database.client
        async with await client.start_session() as session:
            config_module = await GroupConfigModule.find_one(GroupConfigModule.group_id == self, session=session)
            return config_module


class UserConfig(Config):
    def __init__(self, user_id: int) -> None:
        super().__init__(module_class=UserConfigModule, primary_key="user_id", key_id=user_id)

        self.user_id = user_id

    async def ban(self) -> None:
        """
        拉黑这个人
        """
        await self._update("banned", True)

    async def is_banned(self) -> bool:
        """
        是否被拉黑
        """
        banned = await self._find("banned")
        return True if banned else False


class TaskManager:
    _tasks: dict[str, dict] = {}
    _lock: asyncio.Lock = asyncio.Lock()
    _TTL: int = 600

    @classmethod
    async def refresh(cls):
        async with cls._lock:
            current_time = time.time()
            cls._tasks = {
                task_id: task_status
                for task_id, task_status in cls._tasks.items()
                if task_status.get("start_time", 0) + cls._TTL >= current_time
            }

    @classmethod
    async def add_task(cls, task_id: str, task_status: dict):
        await cls.refresh()
        async with cls._lock:
            cls._tasks[task_id] = task_status

    @classmethod
    async def get_task(cls, task_id: str) -> dict | None:
        await cls.refresh()
        async with cls._lock:
            return cls._tasks.get(task_id)

    @classmethod
    async def remove_task(cls, task_id: str):
        await cls.refresh()
        async with cls._lock:
            if task_id in cls._tasks:
                del cls._tasks[task_id]
