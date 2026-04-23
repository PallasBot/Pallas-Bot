from pathlib import Path

# 统一以仓库根目录为锚点，避免依赖运行时工作目录。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
