#!/usr/bin/env bash
# 构建 pallas-core wheel（从 Pallas-Bot 主仓）
# 用法: ./scripts/build_core.sh          # 只构建
#       ./scripts/build_core.sh --publish # 构建并发布到 PyPI
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$ROOT/build/pallas-core"
PALLAS_DIR="$ROOT/pallas"

echo "=== 准备 pallas-core 构建目录 ==="
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/pallas"

# 复制 pallas 内核包
cp -r "$PALLAS_DIR"/* "$BUILD_DIR/pallas/"

# 生成 pyproject.toml
VERSION=$(python3 -c "import sys; sys.path.insert(0, '$PALLAS_DIR'); from pallas import __version__; print(__version__)")
cat > "$BUILD_DIR/pyproject.toml" << PYEOF
[project]
name = "pallas-core"
version = "$VERSION"
description = "Pallas Bot 内核框架 —— 基于 NoneBot2 的社区机器人 SDK"
readme = "README.md"
requires-python = ">=3.12,<4.0"
license = "AGPL-3.0-or-later"
authors = [{ name = "MistEO" }]
maintainers = [
    { name = "mxcoras", email = "mxcoras@outlook.com" },
    { name = "TogetsuDo", email = "togetsudo@outlook.com" },
]
keywords = ["nonebot", "nonebot2", "pallas", "bot", "qq"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.12",
    "Topic :: Communications :: Chat",
]
dependencies = [
    "nonebot2[fastapi]>=2.4.4",
    "nonebot-adapter-onebot>=2.4.6",
    "nonebot-plugin-alconna>=0.60.3",
    "nonebot-plugin-apscheduler>=0.5.0",
    "nonebot-plugin-localstore>=0.7",
    "httpx[socks]>=0.28.1",
    "pydantic>=2.0",
    "tenacity>=9.1.2",
]

[project.urls]
Homepage = "https://github.com/PallasBot/Pallas-Bot"
Documentation = "https://github.com/PallasBot/Pallas-Bot-Docs"
Repository = "https://github.com/PallasBot/Pallas-Bot"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["pallas"]
PYEOF

# 复制 README
cp "$ROOT/README.md" "$BUILD_DIR/README.md"

echo "=== 构建 pallas-core-$VERSION ==="
cd "$BUILD_DIR"
uv build --wheel

WHEEL=$(ls dist/*.whl)
echo ""
echo "=== 构建完成 ==="
echo "Wheel: $BUILD_DIR/$WHEEL"

if [[ "${1:-}" == "--publish" ]]; then
    echo ""
    echo "=== 发布到 PyPI ==="
    uv publish --publish-url https://upload.pypi.org/legacy/ dist/*.tar.gz dist/*.whl 2>/dev/null || \
    uv publish dist/*.whl
    echo "=== 发布完成: pallas-core==$VERSION ==="
else
    echo ""
    echo "预览发布: cd $BUILD_DIR && uv publish --dry-run dist/*.whl"
    echo "正式发布: ./scripts/build_core.sh --publish"
fi
