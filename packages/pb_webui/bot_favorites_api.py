"""部署级 Bot 账号收藏。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from pallas.core.storage.deploy_store import read_deploy_plugin_blob, write_deploy_plugin_blob

if TYPE_CHECKING:
    from collections.abc import Callable

_PLUGIN_NAME = "pb_webui"
_STORAGE_KEY = "bot_favorites"


class BotFavoritesUpdate(BaseModel):
    accounts: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list)


def normalize_bot_favorite_accounts(accounts: list[Any]) -> list[int]:
    normalized: set[int] = set()
    for raw in accounts:
        if isinstance(raw, bool):
            continue
        try:
            account = int(raw)
        except (TypeError, ValueError):
            continue
        if account > 0:
            normalized.add(account)
    return sorted(normalized)


def load_bot_favorites() -> dict[str, object]:
    raw = read_deploy_plugin_blob(_PLUGIN_NAME).get(_STORAGE_KEY)
    if not isinstance(raw, dict) or raw.get("initialized") is not True:
        return {"initialized": False, "accounts": []}
    accounts = raw.get("accounts")
    return {
        "initialized": True,
        "accounts": normalize_bot_favorite_accounts(accounts if isinstance(accounts, list) else []),
    }


def save_bot_favorites(accounts: list[Any]) -> dict[str, object]:
    state = {"initialized": True, "accounts": normalize_bot_favorite_accounts(accounts)}
    blob = read_deploy_plugin_blob(_PLUGIN_NAME)
    blob[_STORAGE_KEY] = state
    write_deploy_plugin_blob(_PLUGIN_NAME, blob)
    return state


def register_bot_favorites_router(
    router: APIRouter,
    *,
    x: str,
    check_write_token: Callable[..., None],
) -> None:
    @router.get(f"{x}/preferences/bot-favorites", include_in_schema=True)
    async def bot_favorites_get() -> JSONResponse:
        return JSONResponse({"ok": True, "data": load_bot_favorites()})

    @router.put(f"{x}/preferences/bot-favorites", include_in_schema=True)
    async def bot_favorites_put(
        body: BotFavoritesUpdate,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(x_pallas_token=x_pallas_token, token=token)
        return JSONResponse({"ok": True, "data": save_bot_favorites(body.accounts)})
