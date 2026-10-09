#!/usr/bin/env python3
"""Check release version declarations without importing plugin code."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z", re.ASCII)


def metadata_version(path: Path) -> str:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bindings = [
        node
        for node in module.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id == "__plugin_meta__"
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
    ]
    if len(bindings) != 1:
        raise ValueError("__init__.py must have one top-level __plugin_meta__ assignment")
    binding = bindings[0]
    if not isinstance(binding, ast.Assign) or len(binding.targets) != 1 or not isinstance(binding.targets[0], ast.Name):
        raise ValueError("__plugin_meta__ must be assigned directly")
    metadata = binding.value
    if (
        not isinstance(metadata, ast.Call)
        or not isinstance(metadata.func, ast.Name)
        or metadata.func.id != "PluginMetadata"
    ):
        raise ValueError("__plugin_meta__ must be a PluginMetadata call")
    extras = [keyword.value for keyword in metadata.keywords if keyword.arg == "extra"]
    if len(extras) != 1 or not isinstance(extras[0], ast.Dict):
        raise ValueError("PluginMetadata extra must be a literal dictionary")
    versions = [
        value
        for key, value in zip(extras[0].keys, extras[0].values)
        if isinstance(key, ast.Constant) and key.value == "version"
    ]
    if len(versions) == 1 and isinstance(versions[0], ast.Constant) and isinstance(versions[0].value, str):
        return versions[0].value
    raise ValueError("__init__.py must declare a literal PluginMetadata(extra={... 'version': 'X.Y.Z'})")


def changelog_version(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"## \[([^\]]+)\](?: - .*)?", line)
        if match and match.group(1) != "Unreleased":
            return match.group(1)
    raise ValueError("CHANGELOG.md must start with a versioned heading such as ## [0.1.0] - YYYY-MM-DD")


def check(root: Path, tag: str) -> None:
    entry = json.loads((root / "community-index.entry.json").read_text(encoding="utf-8"))
    if not isinstance(entry, dict):
        raise ValueError("community-index.entry.json must be an object")
    versions = {
        "PluginMetadata": metadata_version(root / "__init__.py"),
        "community-index.entry.json": entry.get("version"),
        "CHANGELOG.md": changelog_version(root / "CHANGELOG.md"),
        "tag": tag[1:] if tag.startswith("v") else "",
    }
    invalid = {
        name: value for name, value in versions.items() if not isinstance(value, str) or not VERSION_RE.fullmatch(value)
    }
    if invalid:
        raise ValueError(f"formal X.Y.Z versions required: {invalid}")
    if len(set(versions.values())) != 1:
        raise ValueError(f"release versions differ: {versions}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="", help="release tag, e.g. v0.1.0 (defaults to GITHUB_REF_NAME)")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    tag = args.tag or os.environ.get("GITHUB_REF_NAME", "")
    try:
        check(args.root, tag)
    except (OSError, ValueError, json.JSONDecodeError, SyntaxError) as error:
        print(f"Release check failed: {error}", file=sys.stderr)
        return 1
    print(f"Release versions match {tag}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
