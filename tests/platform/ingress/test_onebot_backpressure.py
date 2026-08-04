from nonebot.adapters.onebot.v11.adapter import Adapter

from pallas.core.platform.ingress import onebot_backpressure


def test_install_and_uninstall_onebot_backpressure() -> None:
    original = Adapter._handle_ws
    original_http = Adapter._handle_http
    onebot_backpressure.uninstall_onebot_backpressure()
    try:
        onebot_backpressure.install_onebot_backpressure()
        assert Adapter._handle_ws is onebot_backpressure.patched_handle_ws
        assert Adapter._handle_http is onebot_backpressure.patched_handle_http
        onebot_backpressure.uninstall_onebot_backpressure()
        assert Adapter._handle_ws is original
        assert Adapter._handle_http is original_http
    finally:
        onebot_backpressure.uninstall_onebot_backpressure()
