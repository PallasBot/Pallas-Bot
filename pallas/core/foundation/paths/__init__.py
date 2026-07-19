"""仓库根、data、resource 等路径锚点。"""

from pathlib import Path

_PATHS_FILE = Path(__file__).resolve()
PACKAGE_ROOT = _PATHS_FILE.parents[3]  # pallas/ 包根
SRC_ROOT = PACKAGE_ROOT  # 向后兼容别名 (Phase 3 后移除)


def is_pallas_bot_root(path: Path) -> bool:
    root = path.resolve()
    if not (root / "bot_hub.py").is_file():
        return False
    if not (root / "scripts" / "run_sharded_bot.sh").is_file():
        return False
    manifest = root / "pyproject.toml"
    if not manifest.is_file():
        return False
    try:
        text = manifest.read_text(encoding="utf-8")
    except OSError:
        return False
    return 'name = "pallas-bot"' in text or "name = 'pallas-bot'" in text


def resolve_project_root(*, prefer_cwd: bool = True) -> Path:
    """定位 Pallas-Bot 仓库根目录（含 bot_hub.py 与 pallas-bot 的 pyproject.toml）。"""
    sources: list[Path] = []
    if prefer_cwd:
        sources.append(Path.cwd())
    sources.append(_PATHS_FILE)

    seen: set[Path] = set()
    for source in sources:
        current = source.resolve()
        for path in (current, *current.parents):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if is_pallas_bot_root(resolved):
                return resolved

    # 可编辑安装且 cwd 不在仓库内时的兜底（__file__ 相对 layout）
    return _PATHS_FILE.parents[4]


# CLI 优先按 cwd 解析；Bot 进程 import 时 cwd 可能不在仓库，仍可从包路径向上找到根
PROJECT_ROOT = resolve_project_root(prefer_cwd=True)
DATA_ROOT = PROJECT_ROOT / "data"
RESOURCE_ROOT = PROJECT_ROOT / "resource"


def plugin_data_dir(plugin_name: str, create: bool = True) -> Path:
    path = DATA_ROOT / plugin_name
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def resource_dir(*parts: str) -> Path:
    return RESOURCE_ROOT.joinpath(*parts)


def project_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)
