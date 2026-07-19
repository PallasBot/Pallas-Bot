from pallas.core.shared.utils.http_msg import (
    http_status_should_skip_backend,
    upstream_error_should_skip_backend,
)


def test_upstream_error_should_skip_backend_quota() -> None:
    body = '{"error":{"message":"预扣费","code":"insufficient_user_quota"}}'
    assert upstream_error_should_skip_backend(body)


def test_http_status_should_skip_backend_403() -> None:
    assert http_status_should_skip_backend(403)
