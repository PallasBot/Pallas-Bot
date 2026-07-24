#!/usr/bin/env bash
# 构建 Pallas-Bot-WebUI（React，仓库根）并打包 dist.zip。
# zip 根为 public-react/：解压到 data/pb_webui → data/pb_webui/public-react/index.html。
# 兼容旧布局：若存在 <webui>/react/package.json，则仍在 react/ 子目录构建。
set -euo pipefail

WEBUI_DIR="${1:?用法: build_webui_dist.sh <webui-src-dir> [out.zip]}"
OUT_ZIP="${2:-dist.zip}"

if [[ ! -f "${WEBUI_DIR}/package.json" ]]; then
  echo "未找到 ${WEBUI_DIR}/package.json" >&2
  exit 1
fi

export GIT_COMMIT="${GIT_COMMIT:-$(git -C "${WEBUI_DIR}" rev-parse HEAD 2>/dev/null || echo unknown)}"
export BUILD_TIME="${BUILD_TIME:-$(date -u +"%Y-%m-%dT%H:%M:%SZ")}"

if [[ -f "${WEBUI_DIR}/react/package.json" && ! -f "${WEBUI_DIR}/src/main.tsx" ]]; then
  BUILD_DIR="${WEBUI_DIR}/react"
else
  BUILD_DIR="${WEBUI_DIR}"
fi
ZIP_ROOT="public-react"
BUILD_CMD=(npm run build:ci)

(
  cd "${BUILD_DIR}"
  if [[ ! -d node_modules ]]; then
    npm ci
  fi
  "${BUILD_CMD[@]}"
)

if [[ ! -f "${BUILD_DIR}/dist/index.html" ]]; then
  echo "构建失败：缺少 ${BUILD_DIR}/dist/index.html" >&2
  exit 1
fi

OUT_ABS="$(cd "$(dirname "${OUT_ZIP}")" && pwd)/$(basename "${OUT_ZIP}")"
STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT

mkdir -p "${STAGE}/${ZIP_ROOT}"
cp -a "${BUILD_DIR}/dist/." "${STAGE}/${ZIP_ROOT}/"
(
  cd "${STAGE}"
  zip -r "${OUT_ABS}" "${ZIP_ROOT}"
)

echo "已写入 ${OUT_ABS}（含 ${ZIP_ROOT}/index.html）"
