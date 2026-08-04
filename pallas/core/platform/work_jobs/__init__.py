"""后台任务的通用数据模型与存储接口。"""

from .models import WorkJob
from .store import MemoryWorkJobStore, WorkJobStore

__all__ = ["MemoryWorkJobStore", "WorkJob", "WorkJobStore"]
