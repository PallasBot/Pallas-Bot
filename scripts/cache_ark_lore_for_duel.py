"""已合并至 scripts/sync_arknights_data.py --maintainer-lore。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    print("note: use scripts/sync_arknights_data.py --maintainer-lore", file=sys.stderr)
    sys.argv = [sys.argv[0], "--maintainer-lore", "--skip-operators", "--no-avatars", *sys.argv[1:]]
    from scripts.sync_arknights_data import main

    raise SystemExit(main())
