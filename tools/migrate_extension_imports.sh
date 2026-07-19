#!/usr/bin/env bash
# migrate_extension_imports.sh — 将 pip 扩展仓库的 src.* import 迁移至 pallas.api.* / pallas.*
#
# 用法: bash tools/migrate_extension_imports.sh <扩展仓库路径>
# 示例: bash tools/migrate_extension_imports.sh ../Pallas-Plugin-Duel
#
# 原则: 优先走 pallas.api.*；api 未覆盖的走 pallas.product.* / pallas.core.* / pallas.console.*

set -euo pipefail

TARGET="${1:?请指定扩展仓库路径}"
if [ ! -d "$TARGET" ]; then
    echo "错误: 目录 $TARGET 不存在"
    exit 1
fi

echo ">>> 迁移 $TARGET ..."

# ── 辅助函数: 对目标目录内所有 .py 文件执行 sed ──
run_sed() {
    find "$TARGET" -name '*.py' -exec sed -i "$@" {} +
}

# ═══════════════════════════════════════════════════════════════
# 注意: 必须从最长前缀开始替换，避免 src.features.cmd_perm 被
# src.features 的规则错误匹配
# ═══════════════════════════════════════════════════════════════

# ── 第 1 组: 带子模块的精确映射 (最长前缀优先) ──

# features → api
run_sed -e 's/from src\.features\.cmd_perm\.metadata_defaults/from pallas.api.metadata/g'
run_sed -e 's/from src\.features\.cmd_perm\.metadata_text/from pallas.api.metadata/g'
run_sed -e 's/from src\.features\.cmd_perm/from pallas.api.perm/g'
run_sed -e 's/from src\.features\.command_limits/from pallas.api.limits/g'
run_sed -e 's/from src\.features\.plugin_sdk/from pallas.api.commands/g'
run_sed -e 's/from src\.features\.plugin_storage\.declare/from pallas.api.storage/g'
run_sed -e 's/from src\.features\.plugin_storage\.startup/from pallas.api.storage/g'
run_sed -e 's/from src\.features\.plugin_storage\.deploy_store/from pallas.api.storage/g'
run_sed -e 's/from src\.features\.plugin_storage/from pallas.api.storage/g'

# features → product
run_sed -e 's/from src\.features\.llm\.config/from pallas.api.platform/g'
run_sed -e 's/from src\.features\.llm\.tools\.declare/from pallas.api.platform/g'
run_sed -e 's/from src\.features\.message_scrub\.log_preview/from pallas.api.safety/g'
run_sed -e 's/from src\.features\.message_scrub/from pallas.api.safety/g'
run_sed -e 's/from src\.features\.corpus\.enroll/from pallas.product.corpus.enroll/g'
run_sed -e 's/from src\.features\.corpus/from pallas.product.corpus/g'
run_sed -e 's/from src\.features\.community_stats\.scheduler/from pallas.product.community_stats.scheduler/g'
run_sed -e 's/from src\.features\.community_stats/from pallas.product.community_stats/g'
run_sed -e 's/from src\.features\.control_plane\.bootstrap_client/from pallas.product.control_plane.bootstrap_client/g'
run_sed -e 's/from src\.features\.control_plane/from pallas.product.control_plane/g'
run_sed -e 's/from src\.features\.dream_ban_ack_state/from pallas.api.platform/g'

# features → core (plugin_coord stays in core)
run_sed -e 's/from src\.features\.plugin_coord\.duel/from pallas.core.plugin_coord.duel/g'
run_sed -e 's/from src\.features\.plugin_coord\.dream/from pallas.core.plugin_coord.dream/g'
run_sed -e 's/from src\.features\.plugin_coord\.maa/from pallas.core.plugin_coord.maa/g'
run_sed -e 's/from src\.features\.plugin_coord/from pallas.core.plugin_coord/g'

# foundation → api
run_sed -e 's/from src\.foundation\.paths/from pallas.api.paths/g'
run_sed -e 's/from src\.foundation\.command_prefix/from pallas.api.config/g'
run_sed -e 's/from src\.foundation\.config\.repo_settings/from pallas.api.config/g'
run_sed -e 's/from src\.foundation\.config\.bot_admins_cache/from pallas.api.config/g'
run_sed -e 's/from src\.foundation\.config\.dotenv/from pallas.api.config/g'
run_sed -e 's/from src\.foundation\.config/from pallas.api.config/g'

# foundation → core (db stays internal)
run_sed -e 's/from src\.foundation\.db\.modules/from pallas.core.foundation.db.modules/g'
run_sed -e 's/from src\.foundation\.db\.repository_pg/from pallas.core.foundation.db.repository_pg/g'
run_sed -e 's/from src\.foundation\.db/from pallas.core.foundation.db/g'

# platform → api
run_sed -e 's/from src\.platform\.ai_callback\.media_task_hooks/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.ai_callback\.task_types/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.bot_runtime\.roles/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.bot_runtime\.send_unavailable/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.ingress\.dream_host_gate/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.ingress\.policy_registry/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.multi_bot\.dedup/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.multi_bot\.group/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.multi_bot\.at_targets/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.multi_bot\.fleet/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.multi_bot\.connected_roster/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.multi_bot\.session_seen/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.multi_bot\.group_fleet_probe/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.multi_bot\.bot_filter/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.multi_bot\.group_online_cache/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.multi_bot/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.shard\.presence/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.shard\.coord\.bot_action/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.shard\.coord\.bot_count/from pallas.api.platform/g'
run_sed -e 's/from src\.platform\.plugin_runtime\.resolve/from pallas.api.platform/g'

# platform → media api
run_sed -e 's/from src\.platform\.media\.draw_reference/from pallas.api.media/g'
run_sed -e 's/from src\.platform\.media\.reference_resolve/from pallas.api.media/g'
run_sed -e 's/from src\.platform\.media/from pallas.api.media/g'

# platform → core (deep shard coord stays in core)
run_sed -e 's/from src\.platform\.shard\.coord\.duel_group/from pallas.core.platform.shard.coord.duel_group/g'
run_sed -e 's/from src\.platform\.shard\.coord\.duel_qte_redis/from pallas.core.platform.shard.coord.duel_qte_redis/g'
run_sed -e 's/from src\.platform\.shard\.coord\.duel_qte/from pallas.core.platform.shard.coord.duel_qte/g'
run_sed -e 's/from src\.platform\.shard\.coord\.cage_duel/from pallas.core.platform.shard.coord.cage_duel/g'
run_sed -e 's/from src\.platform\.shard\.coord\.spy_activity/from pallas.core.platform.shard.coord.spy_activity/g'
run_sed -e 's/from src\.platform\.shard\.coord\.dream_drift/from pallas.core.platform.shard.coord.dream_drift/g'
run_sed -e 's/from src\.platform\.shard\.coord\.maa_pending_registry/from pallas.core.platform.shard.coord.maa_pending_registry/g'
run_sed -e 's/from src\.platform\.shard\.coord\.maa_route_registry/from pallas.core.platform.shard.coord.maa_route_registry/g'
run_sed -e 's/from src\.platform\.shard\.coord\.maa_seen_registry/from pallas.core.platform.shard.coord.maa_seen_registry/g'
run_sed -e 's/from src\.platform\.shard\.coord\.maa_hub_routes/from pallas.core.platform.shard.coord.maa_hub_routes/g'
run_sed -e 's/from src\.platform\.shard\.coord\.relogin_payload/from pallas.core.platform.shard.coord.relogin_payload/g'
run_sed -e 's/from src\.platform\.shard\.coord\.relogin_worker_forward/from pallas.core.platform.shard.coord.relogin_worker_forward/g'
run_sed -e 's/from src\.platform\.shard\.coord\.relogin_hub_routes/from pallas.core.platform.shard.coord.relogin_hub_routes/g'
run_sed -e 's/from src\.platform\.shard\.coord/from pallas.core.platform.shard.coord/g'
run_sed -e 's/from src\.platform\.shard\.registry\.config/from pallas.core.platform.shard.registry.config/g'
run_sed -e 's/from src\.platform\.shard\.registry\.store/from pallas.core.platform.shard.registry.store/g'
run_sed -e 's/from src\.platform\.shard\.registry/from pallas.core.platform.shard.registry/g'
run_sed -e 's/from src\.platform\.shard import context/from pallas.core.platform.shard import context/g'
run_sed -e 's/from src\.platform\.shard/from pallas.core.platform.shard/g'
run_sed -e 's/from src\.platform\.bot_runtime/from pallas.core.platform.bot_runtime/g'
run_sed -e 's/from src\.platform\.ingress/from pallas.core.platform.ingress/g'
run_sed -e 's/from src\.platform\.plugin_runtime/from pallas.core.platform.plugin_runtime/g'
run_sed -e 's/from src\.platform\.ai_callback/from pallas.core.platform.ai_callback/g'

# shared → api
run_sed -e 's/from src\.shared\.service_probe/from pallas.api.probe/g'
run_sed -e 's/from src\.shared\.utils\.http_msg/from pallas.api.messages/g'
run_sed -e 's/from src\.shared\.utils\.github_release/from pallas.api.utils/g'
run_sed -e 's/from src\.shared\.utils\.stream_download/from pallas.api.utils/g'
run_sed -e 's/from src\.shared\.utils\.array2cqcode/from pallas.api.utils/g'
run_sed -e 's/from src\.shared\.utils\.arknights_duel_resource/from pallas.core.shared.utils.arknights_duel_resource/g'
run_sed -e 's/from src\.shared\.utils/from pallas.api.utils/g'
run_sed -e 's/from src\.shared\.reply_command_rule/from pallas.api.commands/g'
run_sed -e 's/from src\.shared\.dream_ban_ack_state/from pallas.api.platform/g'
run_sed -e 's/from src\.shared/from pallas.core.shared/g'

# domain → core
run_sed -e 's/from src\.domain\.arknights\.skill_text/from pallas.core.domain.arknights.skill_text/g'
run_sed -e 's/from src\.domain\.arknights\.duel_sync/from pallas.core.domain.arknights.duel_sync/g'
run_sed -e 's/from src\.domain\.arknights/from pallas.core.domain.arknights/g'
run_sed -e 's/from src\.domain/from pallas.core.domain/g'

# console → api (where available) or console (keep)
run_sed -e 's/from src\.console\.webui\.field_help/from pallas.api.config/g'
run_sed -e 's/from src\.console\.webui\.plugin_api/from pallas.api.config/g'
run_sed -e 's/from src\.console\.webui\.plugin_config/from pallas.api.config/g'
run_sed -e 's/from src\.console\.webui\.console_login/from pallas.console.webui.console_login/g'
run_sed -e 's/from src\.console\.webui\.login_page/from pallas.console.webui.login_page/g'
run_sed -e 's/from src\.console\.webui/from pallas.api.config/g'
run_sed -e 's/from src\.console\.web/from pallas.console.web/g'
run_sed -e 's/from src\.console/from pallas.console/g'

# ── 第 2 组: import 语句 (非 from) ──
run_sed -e 's/import src\.features\.cmd_perm/import pallas.api.perm/g'
run_sed -e 's/import src\.features\.command_limits/import pallas.api.limits/g'
run_sed -e 's/import src\.features\.plugin_sdk/import pallas.api.commands/g'
run_sed -e 's/import src\.features\.plugin_storage/import pallas.api.storage/g'
run_sed -e 's/import src\.foundation\.paths/import pallas.api.paths/g'
run_sed -e 's/import src\.foundation\.config/import pallas.api.config/g'
run_sed -e 's/import src\.foundation/import pallas.core.foundation/g'
run_sed -e 's/import src\.platform/import pallas.core.platform/g'
run_sed -e 's/import src\.shared/import pallas.core.shared/g'
run_sed -e 's/import src\.domain/import pallas.core.domain/g'
run_sed -e 's/import src\.console/import pallas.console/g'

# ── 第 3 组: 残余 src.features / src.plugins 顶级 catch-all ──
run_sed -e 's/from src\.features\./from pallas.product./g'
run_sed -e 's/from src\.plugins\./from packages./g'
run_sed -e 's/from src\.foundation\./from pallas.core.foundation./g'
run_sed -e 's/from src\.platform\./from pallas.core.platform./g'
run_sed -e 's/from src\.shared\./from pallas.core.shared./g'
run_sed -e 's/from src\.domain\./from pallas.core.domain./g'
run_sed -e 's/from src\.console\./from pallas.console./g'

# ── 第 4 组: 字符串中的 src. 引用 ──
run_sed -e 's/"src\.plugins\./"packages./g'
run_sed -e "s/'src\.plugins\./'packages./g"
run_sed -e 's/"src\/plugins\//"packages\//g'
run_sed -e "s/'src\/plugins\//'packages\//g"

echo ">>> $TARGET 迁移完成。请检查残余:"
grep -rn "from src\." "$TARGET" --include="*.py" | grep -v '.git/' | grep -v egg-info || echo "   (无残余 src. 导入)"
echo ""
