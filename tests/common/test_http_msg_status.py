from pallas.core.shared.utils.http_msg import (
    http_status_should_skip_backend,
    http_status_should_try_next_param,
)


def test_http_status_should_try_next_param_400() -> None:
    assert http_status_should_try_next_param(400)
    assert http_status_should_try_next_param(422)
    assert not http_status_should_try_next_param(403)
    assert not http_status_should_skip_backend(400)


def test_http_status_should_skip_backend_5xx() -> None:
    assert http_status_should_skip_backend(502)
