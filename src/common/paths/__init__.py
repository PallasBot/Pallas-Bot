"""仓库根、data、resource 等路径锚点（与 NoneBot 工作目录无关）。"""

from pathlib import Path

# __file__ = .../src/common/paths/__init__.py → 仓库根为向上 3 级
PROJECT_ROOT = Path(__file__).resolve().parents[3]
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
