"""后台任务辅助进程入口。"""

from __future__ import annotations

import asyncio

from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ
from pallas.core.platform.work_jobs.service import run_work_service


def main() -> None:
    apply_repo_settings_to_environ()
    asyncio.run(run_work_service({}))


if __name__ == "__main__":
    main()
