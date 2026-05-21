"""分片进程落盘日志与 ERROR jsonl 归档。"""

from src.common.shard.logs.errors import (
    append_shard_log_error,
    append_shard_log_error_from_sink,
    cleanup_shard_error_archives_sync,
    collect_cluster_log_errors_from_jsonl,
)
from src.common.shard.logs.process import install_shard_process_logging
from src.common.shard.logs.view import (
    ShardLogTailer,
    cleanup_stale_shard_log_files,
    collect_cluster_log_errors,
    list_shard_log_sources,
    merge_cluster_log_lines,
    shard_logs_dir,
)

__all__ = [
    "ShardLogTailer",
    "append_shard_log_error",
    "append_shard_log_error_from_sink",
    "cleanup_shard_error_archives_sync",
    "cleanup_stale_shard_log_files",
    "collect_cluster_log_errors",
    "collect_cluster_log_errors_from_jsonl",
    "install_shard_process_logging",
    "list_shard_log_sources",
    "merge_cluster_log_lines",
    "shard_logs_dir",
]
