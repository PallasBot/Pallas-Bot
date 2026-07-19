#!/usr/bin/env bash
# 在已 checkout 的 WebUI 仓库目录内解析发版 ref，并写入 GITHUB_OUTPUT（console_version / resolved_ref）。
set -euo pipefail

WEBUI_DIR="${1:?用法: resolve_webui_ref.sh <webui-src-dir>}"
PIN_TAG="${PIN_TAG:-}"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  OUT="${GITHUB_OUTPUT}"
else
  OUT="$(mktemp)"
  trap 'rm -f "${OUT}"' EXIT
fi

(
  cd "${WEBUI_DIR}"
  git fetch origin --tags --force 2>/dev/null || true

  if [[ -n "${PIN_TAG}" ]]; then
    git checkout "${PIN_TAG}"
    echo "console_version=${PIN_TAG}" >> "${OUT}"
    echo "resolved_ref=${PIN_TAG}" >> "${OUT}"
    exit 0
  fi

  TAG="$(git tag -l 'v*' --merged HEAD --sort=-version:refname | head -n1 || true)"
  if [[ -z "${TAG}" ]]; then
    TAG="$(git tag -l 'v*' --sort=-version:refname | head -n1 || true)"
  fi
  if [[ -n "${TAG}" ]]; then
    git checkout "${TAG}"
    echo "console_version=${TAG}" >> "${OUT}"
    echo "resolved_ref=${TAG}" >> "${OUT}"
  else
    VER="$(node -p "require('./package.json').version")"
    echo "console_version=${VER}" >> "${OUT}"
    echo "resolved_ref=main" >> "${OUT}"
    echo "::warning::WebUI 无 v* tag，使用当前分支与 package.json 版本 ${VER}" >&2
  fi
)

if [[ -z "${GITHUB_OUTPUT:-}" ]]; then
  cat "${OUT}"
fi
