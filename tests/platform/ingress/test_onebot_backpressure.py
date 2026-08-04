from nonebot.adapters.onebot.v11.adapter import Adapter

from pallas.core.platform.ingress import onebot_backpressure


def test_install_and_uninstall_onebot_backpressure() -> None:
    original = Adapter._handle_ws
    onebot_backpressure.uninstall_onebot_backpressure()
    try:
        onebot_backpressure.install_onebot_backpressure()
        assert Adapter._handle_ws is onebot_backpressure.patched_handle_ws
        onebot_backpressure.uninstall_onebot_backpressure()
        assert Adapter._handle_ws is original
    finally:
        onebot_backpressure.uninstall_onebot_backpressure()
