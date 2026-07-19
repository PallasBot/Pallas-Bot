"""已合并至 scripts/sync_arknights_data.py，本文件保留兼容入口。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sync_arknights_data import main  # noqa: E402

if __name__ == "__main__":
    print("note: use scripts/sync_arknights_data.py (this wrapper forwards argv)", file=sys.stderr)
    raise SystemExit(main())
