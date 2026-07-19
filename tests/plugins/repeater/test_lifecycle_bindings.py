from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_bind_repeater_learn_lifecycle_idempotent():
    import packages.repeater.learn_queue as mod

    mod._LIFECYCLE_BOUND = False
    mock_driver = MagicMock()
    with patch.object(mod, "get_driver", return_value=mock_driver):
        mod.bind_repeater_learn_lifecycle()
        mod.bind_repeater_learn_lifecycle()
    assert mod._LIFECYCLE_BOUND is True
    assert mock_driver.on_startup.call_count == 1
    assert mock_driver.on_shutdown.call_count == 1


def test_bind_corpus_prefetch_lifecycle_idempotent():
    import pallas.product.corpus.prefetch as mod

    mod._LIFECYCLE_BOUND = False
    mock_driver = MagicMock()
    with patch.object(mod, "get_driver", return_value=mock_driver):
        mod.bind_corpus_prefetch_lifecycle()
        mod.bind_corpus_prefetch_lifecycle()
    assert mod._LIFECYCLE_BOUND is True
    assert mock_driver.on_startup.call_count == 1
    assert mock_driver.on_shutdown.call_count == 1
