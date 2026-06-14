#!/usr/bin/env bash
# 生成 GitHub Release 变更摘要（按 Conventional Commits 分组，空分组省略）。
set -euo pipefail

PREVIOUS_TAG="${1:-}"
CURRENT_REF="${2:-HEAD}"
REPO="${3:-}"

format_log() {
  local range="$1"
  shift
  git log --no-merges --pretty=format:"* %s ([%h](https://github.com/${REPO}/commit/%H))" "$range" "$@" 2>/dev/null || true
}

emit_section() {
  local title="$1"
  local body="$2"
  if [ -n "${body//[[:space:]]/}" ]; then
    printf '### %s\n\n%s\n\n' "$title" "$body"
  fi
}

if [ -z "$PREVIOUS_TAG" ]; then
  echo "🎉 **首次发布**"
  exit 0
fi

if git rev-parse --verify "${CURRENT_REF}^{commit}" >/dev/null 2>&1; then
  RANGE="${PREVIOUS_TAG}..${CURRENT_REF}"
else
  RANGE="${PREVIOUS_TAG}..HEAD"
fi

if ! git rev-list "${RANGE}" >/dev/null 2>&1; then
  echo "（无相对 ${PREVIOUS_TAG} 的新提交）"
  exit 0
fi

FEATS=$(format_log "$RANGE" --grep='^feat')
FIXES=$(format_log "$RANGE" --grep='^fix')
DOCS=$(format_log "$RANGE" --grep='^docs')
PERF=$(format_log "$RANGE" --grep='^perf')
if [ "${INCLUDE_REFACTOR:-0}" = "1" ]; then
  REFACTOR=$(format_log "$RANGE" --grep='^refactor')
fi
OTHER=$(
  format_log "$RANGE" \
    --invert-grep --grep='^feat' --grep='^fix' --grep='^docs' --grep='^perf' \
    --grep='^chore(release)' --grep='^chore: release'
)
if [ "${INCLUDE_REFACTOR:-0}" = "1" ]; then
  OTHER=$(
    format_log "$RANGE" \
      --invert-grep --grep='^feat' --grep='^fix' --grep='^docs' --grep='^perf' --grep='^refactor' \
      --grep='^chore(release)' --grep='^chore: release'
  )
fi

emit_section "🚀 新功能" "$FEATS"
emit_section "🐛 错误修复" "$FIXES"
emit_section "📚 文档更新" "$DOCS"
emit_section "⚡ 性能优化" "$PERF"
if [ "${INCLUDE_REFACTOR:-0}" = "1" ]; then
  emit_section "♻️ 重构" "${REFACTOR:-}"
fi
emit_section "🔨 其他更改" "$OTHER"

COMPARE_TO="${CURRENT_REF}"
if ! git rev-parse --verify "${COMPARE_TO}^{commit}" >/dev/null 2>&1; then
  COMPARE_TO="HEAD"
fi
printf '**完整变更**: [`%s...%s`](https://github.com/%s/compare/%s...%s)\n' \
  "$PREVIOUS_TAG" "$COMPARE_TO" "$REPO" "$PREVIOUS_TAG" "$COMPARE_TO"
