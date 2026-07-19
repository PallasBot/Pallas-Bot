"""共享工具：HTTP 客户端、流下载、GitHub 版本检查、CQ 码转换等。"""

from pallas.core.shared.utils import HTTPXClient, is_bot_admin
from pallas.core.shared.utils.array2cqcode import try_convert_to_cqcode
from pallas.core.shared.utils.github_release import (
    fetch_github_releases,
    github_auth_headers,
    github_release_api_url,
    github_release_asset_url,
)
from pallas.core.shared.utils.mail import (
    MailConfig,
    build_mail_config,
    clear_smtp_config_cache,
    get_smtp_config,
    reload_smtp_config,
    send_mail,
)
from pallas.core.shared.utils.private_send import (
    group_temp_private_group_id,
    reply_private_message,
    send_private_msg_compat,
)
from pallas.core.shared.utils.stream_download import (
    StreamDownloadProgress,
    format_download_byte_size,
    sync_stream_download_to_file,
)

__all__ = [
    "HTTPXClient",
    "MailConfig",
    "StreamDownloadProgress",
    "build_mail_config",
    "clear_smtp_config_cache",
    "fetch_github_releases",
    "format_download_byte_size",
    "get_smtp_config",
    "group_temp_private_group_id",
    "github_auth_headers",
    "github_release_api_url",
    "github_release_asset_url",
    "is_bot_admin",
    "reload_smtp_config",
    "reply_private_message",
    "send_mail",
    "send_private_msg_compat",
    "sync_stream_download_to_file",
    "try_convert_to_cqcode",
]
