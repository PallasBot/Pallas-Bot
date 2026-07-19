"""relogin 分片 HTTP 路径常量。"""

RELOGIN_HUB_PATH = "/shard/relogin/message"

# Hub 侧最长路径：process wait 90 + qr/refresh 60 + connect 90 + docker 重启开销。
# Worker httpx 超时必须严格大于该上界，否则会被打成「转发 hub 失败」。
RELOGIN_FORWARD_TIMEOUT_SEC = 360.0
RELOGIN_FORWARD_CONNECT_TIMEOUT_SEC = 10.0
