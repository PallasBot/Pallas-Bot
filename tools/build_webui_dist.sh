#!/usr/bin/env bash
# 构建 Pallas-Bot-WebUI（默认 React）并打包 dist.zip。
# zip 根为 public-react/：解压到 data/pb_webui → data/pb_webui/public-react/index.html。
# 若需 Vue：WEBUI_FRONTEND=vue ./tools/build_webui_dist.sh <webui-src-dir> [out.zip]
set -euo pipefail

WEBUI_DIR="${1:?用法: build_webui_dist.sh <webui-src-dir> [out.zip]}"
OUT_ZIP="${2:-dist.zip}"
FRONTEND="${WEBUI_FRONTEND:-react}"

if [[ ! -f "${WEBUI_DIR}/package.json" ]]; then
  echo "未找到 ${WEBUI_DIR}/package.json" >&2
  exit 1
fi

export CONSOLE_VERSION="${CONSOLE_VERSION:-dev}"
export GIT_COMMIT="${GIT_COMMIT:-$(git -C "${WEBUI_DIR}" rev-parse HEAD 2>/dev/null || echo unknown)}"
export BUILD_TIME="${BUILD_TIME:-$(date -u +"%Y-%m-%dT%H:%M:%SZ")}"

if [[ "${FRONTEND}" == "vue" ]]; then
  BUILD_DIR="${WEBUI_DIR}"
  ZIP_ROOT="public"
  BUILD_CMD=(npm run build:ci)
else
  BUILD_DIR="${WEBUI_DIR}/react"
  ZIP_ROOT="public-react"
  if [[ ! -f "${BUILD_DIR}/package.json" ]]; then
    echo "未找到 ${BUILD_DIR}/package.json（React 前端）" >&2
    exit 1
  fi
  BUILD_CMD=(npm run build:ci)
fi

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

echo "已写入 ${OUT_ABS}（含 ${ZIP_ROOT}/index.html，frontend=${FRONTEND}）"
