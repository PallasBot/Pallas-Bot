"""社区插件作者工具：目录校验与索引条目生成。"""

from __future__ import annotations

import ast
import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pallas.console.webui.community_plugin_assets import infer_community_plugin_icon, parse_git_host_repo
from pallas.console.webui.community_plugin_index import normalize_index_entry, parse_index_document
from pallas.console.webui.community_plugin_install import PLUGIN_ID_RE

if TYPE_CHECKING:
    from pathlib import Path

ICON_ASSET_PATHS = (
    "assets/icon.png",
    "assets/icon.webp",
    "assets/icon.svg",
    "assets/avatar.png",
    "assets/avatar.jpg",
)

# ---- import 规则（L1 社区插件） ----
FORBIDDEN_PREFIXES_L1 = (
    "pallas.core.",
    "pallas.console.",
    "pallas.product.",
    "src.",
)

ALLOWED_API_PREFIX = "pallas.api."


def _module_names_from_import(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module:
        return [node.module]
    return []


def _check_file_imports(path: Path) -> list[str]:
    """检查单文件 import 是否符合 L1 规则。返回错误消息列表。"""
    errors: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{path.name}: 语法错误 {exc}"]
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for mod in _module_names_from_import(node):
            if mod.startswith(FORBIDDEN_PREFIXES_L1):
                errors.append(f"禁止 import `{mod}`（社区插件仅允许 `pallas.api.*`）")
                continue
            if mod.startswith("pallas.") and not mod.startswith(ALLOWED_API_PREFIX):
                errors.append(f"仅允许 `pallas.api.*`，发现 `{mod}`")
    return errors


def _validate_plugin_imports(plugin_dir: Path) -> list[str]:
    """扫描插件目录所有 .py 文件的 import 是否符合 L1 规则。"""
    errors: list[str] = []
    for py_file in sorted(plugin_dir.rglob("*.py")):
        if not py_file.is_file():
            continue
        file_errors = _check_file_imports(py_file)
        errors.extend(f"{py_file.name}: {err}" for err in file_errors)
    return errors


def read_plugin_metadata_from_init(init_path: Path) -> dict[str, str]:
    """从 __init__.py 提取 PLUGIN_ID 与 PluginMetadata 常见字段（best-effort）。"""
    text = init_path.read_text(encoding="utf-8")
    out: dict[str, str] = {}

    pid_match = re.search(r'^\s*PLUGIN_ID\s*=\s*["\']([^"\']+)["\']', text, flags=re.MULTILINE)
    if pid_match:
        out["plugin_id"] = pid_match.group(1).strip()

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = ""
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name != "PluginMetadata":
            continue
        for keyword in node.keywords:
            if keyword.arg in {"name", "description", "homepage"} and isinstance(keyword.value, ast.Constant):
                if isinstance(keyword.value.value, str):
                    out[keyword.arg] = keyword.value.value.strip()
        break
    return out


def _const_str(value: ast.AST) -> str | None:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value.strip()
    return None


def _const_int(value: ast.AST) -> int | None:
    if isinstance(value, ast.Constant) and isinstance(value.value, int):
        return int(value.value)
    return None


def _extract_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _extract_literal_rows(node: ast.AST) -> list[dict[str, Any]]:
    if isinstance(node, (ast.List, ast.Tuple)):
        return [row for item in node.elts if (row := _extract_literal_dict(item)) is not None]
    if isinstance(node, ast.Call):
        rows: list[dict[str, Any]] = []
        for arg in node.args:
            row = _extract_literal_dict(arg)
            if row is not None:
                rows.append(row)
        return rows
    return []


def _extract_literal_dict(node: ast.AST) -> dict[str, Any] | None:
    if not isinstance(node, ast.Dict):
        return None
    out: dict[str, Any] = {}
    for key_node, value_node in zip(node.keys, node.values, strict=False):
        key = _const_str(key_node) if key_node is not None else None
        if not key:
            continue
        str_value = _const_str(value_node)
        if str_value is not None:
            out[key] = str_value
            continue
        int_value = _const_int(value_node)
        if int_value is not None:
            out[key] = int_value
            continue
    return out


def _extract_decl_row(node: ast.AST) -> dict[str, Any] | None:
    if not isinstance(node, ast.Call):
        return _extract_literal_dict(node)
    call_name = _extract_call_name(node.func)
    if call_name == "command_perm_row":
        if len(node.args) >= 3:
            return {
                "id": _const_str(node.args[0]) or "",
                "label": _const_str(node.args[1]) or "",
                "default": _const_str(node.args[2]) or "",
            }
    if call_name == "command_limit_row":
        if len(node.args) >= 2:
            return {
                "id": _const_str(node.args[0]) or "",
                "cd_sec": _const_int(node.args[1]) if _const_int(node.args[1]) is not None else -1,
            }
    return _extract_literal_dict(node)


def _extract_decl_rows(node: ast.AST) -> list[dict[str, Any]]:
    if isinstance(node, (ast.List, ast.Tuple)):
        return [row for item in node.elts if (row := _extract_decl_row(item)) is not None]
    if isinstance(node, ast.Call):
        rows: list[dict[str, Any]] = []
        for arg in node.args:
            row = _extract_decl_row(arg)
            if row is not None:
                rows.append(row)
        return rows
    return []


def _is_usage_builder_call(node: ast.AST) -> bool:
    """识别 join_usage(...) / usage_line(...) 这类 usage 组装调用。"""
    if not isinstance(node, ast.Call):
        return False
    return _extract_call_name(node.func) in {"join_usage", "usage_line"}


def parse_plugin_metadata_contract(init_path: Path) -> dict[str, Any]:
    text = init_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(init_path))
    except SyntaxError:
        return {}

    contract: dict[str, Any] = {
        "name": "",
        "description": "",
        "usage": "",
        "command_permissions": [],
        "command_limits": [],
        "menu_data": [],
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _extract_call_name(node.func) != "PluginMetadata":
            continue
        for keyword in node.keywords:
            if keyword.arg in {"name", "description", "usage"}:
                value = _const_str(keyword.value)
                # usage 推荐用 join_usage()/usage_line() 组装，非字面量也视为已填写。
                if value is None and keyword.arg == "usage" and _is_usage_builder_call(keyword.value):
                    value = "<join_usage>"
                contract[keyword.arg] = value or ""
                continue
            if keyword.arg != "extra" or not isinstance(keyword.value, ast.Dict):
                continue
            for extra_key_node, extra_value_node in zip(keyword.value.keys, keyword.value.values, strict=False):
                extra_key = _const_str(extra_key_node) if extra_key_node is not None else None
                if extra_key == "command_permissions":
                    contract["command_permissions"] = _extract_decl_rows(extra_value_node)
                elif extra_key == "command_limits":
                    contract["command_limits"] = _extract_decl_rows(extra_value_node)
                elif extra_key == "menu_data":
                    contract["menu_data"] = _extract_literal_rows(extra_value_node)
        break
    return contract


def validate_community_plugin_dir(plugin_dir: Path) -> tuple[list[str], list[str]]:
    """返回 (errors, warnings)。"""
    errors: list[str] = []
    warnings: list[str] = []
    if not plugin_dir.is_dir():
        errors.append(f"目录不存在：{plugin_dir}")
        return errors, warnings

    init_path = plugin_dir / "__init__.py"
    if not init_path.is_file():
        errors.append("缺少 __init__.py")
        return errors, warnings

    text = init_path.read_text(encoding="utf-8")
    if "__plugin_meta__" not in text and "PluginMetadata" not in text:
        warnings.append("未找到 __plugin_meta__ / PluginMetadata，NoneBot 可能无法识别插件元数据")

    plugin_id = plugin_dir.name
    meta = read_plugin_metadata_from_init(init_path)
    if meta.get("plugin_id"):
        plugin_id = meta["plugin_id"]
    if not PLUGIN_ID_RE.fullmatch(plugin_id):
        errors.append(
            f"插件 ID「{plugin_id}」不符合规范（小写字母开头，仅字母数字下划线，最长 64）",
        )
    elif plugin_dir.name != plugin_id:
        warnings.append(
            f"目录名「{plugin_dir.name}」与 PLUGIN_ID「{plugin_id}」不一致，"
            f"安装到 local/plugins/ 时目录须为 {plugin_id}/",
        )

    if not any((plugin_dir / rel).is_file() for rel in ICON_ASSET_PATHS):
        warnings.append(
            "未找到 assets/icon.png 等图标文件；索引可省略 icon，Bot 会尝试推断 GitHub/Gitee raw URL",
        )

    readme_names = ("README.md", "readme.md", "Readme.md")
    if not any((plugin_dir / name).is_file() for name in readme_names):
        warnings.append("建议提供 README.md，便于商店详情页展示")

    changelog_names = ("CHANGELOG.md", "changelog.md", "CHANGELOG.MD")
    if not any((plugin_dir / name).is_file() for name in changelog_names):
        warnings.append(
            "建议提供 CHANGELOG.md（Keep a Changelog 格式），商店「更新日志」分栏会优先展示；"
            "缺失时仅能按 git 提交历史兜底",
        )

    # L1 import 检查（社区插件仅允许 pallas.api.*）
    import_errors = _validate_plugin_imports(plugin_dir)
    errors.extend(f"L1 import 违规: {err}" for err in import_errors)

    return errors, warnings


def validate_community_plugin_dir_profile(
    plugin_dir: Path,
    *,
    profile: str = "L1",
) -> tuple[list[str], list[str], dict[str, Any]]:
    level = (profile or "L1").upper()
    errors, warnings = validate_community_plugin_dir(plugin_dir)
    profile_data: dict[str, Any] = {
        "level": level,
        "missing": [],
        "command_ids": {
            "permissions": [],
            "menu": [],
            "limits": [],
        },
    }
    init_path = plugin_dir / "__init__.py"
    if not init_path.is_file():
        return errors, warnings, profile_data

    contract = parse_plugin_metadata_contract(init_path)
    usage = str(contract.get("usage") or "").strip()
    description = str(contract.get("description") or "").strip()
    command_permissions = list(contract.get("command_permissions") or [])
    command_limits = list(contract.get("command_limits") or [])
    menu_data = list(contract.get("menu_data") or [])

    permission_ids = sorted({
        str(row.get("id") or "").strip() for row in command_permissions if str(row.get("id") or "").strip()
    })
    menu_ids = sorted({
        str(row.get("command_permission") or "").strip()
        for row in menu_data
        if str(row.get("command_permission") or "").strip()
    })
    limit_ids = sorted({str(row.get("id") or "").strip() for row in command_limits if str(row.get("id") or "").strip()})
    profile_data["command_ids"] = {
        "permissions": permission_ids,
        "menu": menu_ids,
        "limits": limit_ids,
    }

    if not description:
        errors.append(f"{level} 缺少 description")
        profile_data["missing"].append("description")
    if not usage:
        errors.append(f"{level} 缺少 usage")
        profile_data["missing"].append("usage")
    if not command_permissions:
        errors.append(f"{level} 缺少 command_permissions")
        profile_data["missing"].append("command_permissions")
    if not menu_data:
        errors.append(f"{level} 缺少 menu_data")
        profile_data["missing"].append("menu_data")

    if command_permissions and menu_ids:
        missing_in_permissions = sorted(set(menu_ids) - set(permission_ids))
        if missing_in_permissions:
            errors.append(
                f"{level} menu_data 引用了未声明权限的命令 ID: {', '.join(missing_in_permissions)}",
            )

    if level == "L2":
        if not command_limits:
            errors.append("L2 缺少 command_limits")
            profile_data["missing"].append("command_limits")
        else:
            missing_in_permissions = sorted(set(limit_ids) - set(permission_ids))
            if missing_in_permissions:
                errors.append(
                    f"L2 command_limits 存在未声明权限的命令 ID: {', '.join(missing_in_permissions)}",
                )

    return errors, warnings, profile_data


def suggest_plugin_id_from_repo(repository_url: str) -> str | None:
    parsed = parse_git_host_repo(repository_url)
    if parsed is None:
        return None
    _, _, repo = parsed
    candidate = re.sub(r"[^a-z0-9_]", "_", repo.lower())
    candidate = re.sub(r"_+", "_", candidate).strip("_")
    if candidate and PLUGIN_ID_RE.fullmatch(candidate):
        return candidate
    if candidate:
        trimmed = candidate[:64]
        if PLUGIN_ID_RE.fullmatch(trimmed):
            return trimmed
    return None


def build_index_entry(
    *,
    plugin_id: str,
    name: str,
    description: str,
    repository: str,
    ref: str = "main",
    author: str = "",
    tags: list[str] | None = None,
    min_pallas_version: str = "4.0.0",
    icon: str | None = None,
    homepage: str | None = None,
) -> dict[str, Any]:
    pid = plugin_id.strip()
    repo = repository.strip()
    entry: dict[str, Any] = {
        "id": pid,
        "name": (name or pid).strip() or pid,
        "description": (description or "").strip(),
        "repository": repo,
        "ref": (ref or "main").strip() or "main",
        "author": (author or "").strip(),
        "tags": [str(t).strip() for t in (tags or []) if str(t).strip()],
        "min_pallas_version": (min_pallas_version or "").strip() or "4.0.0",
    }
    resolved_icon = (icon or "").strip() or infer_community_plugin_icon(repo, entry["ref"])
    if resolved_icon:
        entry["icon"] = resolved_icon
    if homepage and str(homepage).strip():
        entry["homepage"] = str(homepage).strip()
    return entry


def build_index_entry_from_dir(
    plugin_dir: Path,
    *,
    repository: str,
    ref: str = "main",
    author: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    init_path = plugin_dir / "__init__.py"
    meta = read_plugin_metadata_from_init(init_path) if init_path.is_file() else {}
    plugin_id = meta.get("plugin_id") or plugin_dir.name
    return build_index_entry(
        plugin_id=plugin_id,
        name=meta.get("name") or plugin_id,
        description=meta.get("description") or "",
        repository=repository,
        ref=ref,
        author=author,
        tags=tags,
        homepage=meta.get("homepage"),
    )


def format_index_entry_json(entry: dict[str, Any], *, indent: int = 2) -> str:
    return json.dumps(entry, ensure_ascii=False, indent=indent) + "\n"


def validate_index_file(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    meta, plugins = parse_index_document(raw)
    issues: list[str] = []
    for entry in plugins:
        pid = entry["plugin_id"]
        repo = entry.get("repository_url") or ""
        if not entry.get("icon") and parse_git_host_repo(str(repo)):
            issues.append(
                f"{pid}: 未设置 icon，将自动推断 {ICON_ASSET_PATHS[0]}（请确保仓库中存在该文件）",
            )
        normalized = normalize_index_entry(
            {
                "id": pid,
                "repository": repo,
                **{k: v for k, v in entry.items() if k not in {"plugin_id", "repository_url"}},
            },
        )
        if normalized is None:
            issues.append(f"{pid}: 条目无效")
    return meta, plugins, issues


def today_index_updated_at() -> str:
    return datetime.now(UTC).date().isoformat()
