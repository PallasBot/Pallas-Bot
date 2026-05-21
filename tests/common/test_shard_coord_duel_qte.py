from __future__ import annotations

import asyncio
import time

from src.common.shard.coord import duel_qte as mod


def test_single_qte_cross_shard_result(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_coord_dir", lambda: tmp_path)

    session_id = mod.publish_single_qte_request(
        group_id=10086,
        responder="200",
        required_key="格挡",
        window_sec=8,
        qte_kind="keyword",
        decoy_keys=None,
        deadline=time.time() + 5.0,
    )
    path = mod._session_path(session_id)
    mod._write_single_result(path, success=True)

    async def run() -> None:
        fut = asyncio.get_running_loop().create_future()
        await mod.wait_single_qte_coord_result(session_id, fut, deadline=time.time() + 2.0)
        assert fut.done()
        assert fut.result() is True

    asyncio.run(run())


def test_race_qte_first_winner(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_coord_dir", lambda: tmp_path)

    mod.publish_race_qte_request(
        group_id=10086,
        challenger_id="100",
        defender_id="200",
        required_key="闪避",
        window_sec=8,
        qte_kind="keyword",
        decoy_keys=None,
        deadline=time.time() + 5.0,
    )
    sid = mod.race_qte_session_id(10086)
    path = mod._session_path(sid)
    assert mod._try_write_race_winner(path, winner_uid="100") is True
    assert mod._try_write_race_winner(path, winner_uid="200") is False
    data = mod._read_session(path)
    assert data is not None
    assert data.get("winner_uid") == "100"
