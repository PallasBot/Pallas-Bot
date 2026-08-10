from pallas.api.config import SingProgress


def test_sing_progress_is_available_through_public_config_api() -> None:
    progress = SingProgress(song_id="1474697449", chunk_index=2, key=-1)

    assert progress.song_id == "1474697449"
    assert progress.chunk_index == 2
    assert progress.key == -1
