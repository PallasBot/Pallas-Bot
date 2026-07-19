#!/usr/bin/env bash
# 构建 Pallas-Bot-WebUI 并打包 dist.zip（zip 根为 public/，解压到 data/pallas_webui 后即为 public/index.html）。
set -euo pipefail

WEBUI_DIR="${1:?用法: build_webui_dist.sh <webui-src-dir> [out.zip]}"
OUT_ZIP="${2:-dist.zip}"

if [[ ! -f "${WEBUI_DIR}/package.json" ]]; then
  echo "未找到 ${WEBUI_DIR}/package.json" >&2
  exit 1
fi

export CONSOLE_VERSION="${CONSOLE_VERSION:-dev}"
export GIT_COMMIT="${GIT_COMMIT:-$(git -C "${WEBUI_DIR}" rev-parse HEAD 2>/dev/null || echo unknown)}"
export BUILD_TIME="${BUILD_TIME:-$(date -u +"%Y-%m-%dT%H:%M:%SZ")}"

(
  cd "${WEBUI_DIR}"
  npm run build:ci
)

if [[ ! -f "${WEBUI_DIR}/dist/index.html" ]]; then
  echo "构建失败：缺少 ${WEBUI_DIR}/dist/index.html" >&2
  exit 1
fi

OUT_ABS="$(cd "$(dirname "${OUT_ZIP}")" && pwd)/$(basename "${OUT_ZIP}")"
STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT

mkdir -p "${STAGE}/public"
cp -a "${WEBUI_DIR}/dist/." "${STAGE}/public/"
(
  cd "${STAGE}"
  zip -r "${OUT_ABS}" public
)

echo "已写入 ${OUT_ABS}（含 public/index.html）"
