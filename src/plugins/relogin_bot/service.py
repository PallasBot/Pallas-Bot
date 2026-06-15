"""牛牛重新上号 / 创建牛牛：无 NoneBot 依赖的核心流程。"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from nonebot import get_driver

from src.foundation.config import user_is_bot_admin
from src.foundation.db import make_bot_config_repository
from src.platform.shard.coord.relogin_payload import ReloginHandleResult, ReplyItem

_CANCEL_WORDS = {"取消", "cancel", "退出", "quit"}


@dataclass
class ReloginSession:
    kind: Literal["relogin", "create"]
    step: str
    data: dict[str, Any] = field(default_factory=dict)


_sessions: dict[str, ReloginSession] = {}


def session_key(bot_id: str, user_id: str) -> str:
    return f"{bot_id}:{user_id}"


def clear_session(bot_id: str, user_id: str) -> None:
    _sessions.pop(session_key(bot_id, user_id), None)


def user_is_superuser_id(user_id: str) -> bool:
    driver = get_driver()
    sup = getattr(driver.config, "superusers", None) or set()
    uid = str(user_id).strip()
    return uid in {str(x) for x in sup}


def extract_qq(arg: str) -> str:
    text = (arg or "").strip()
    return text if text.isdigit() else ""


async def bot_id_exists_in_db(bot_id: int) -> bool:
    try:
        repo = make_bot_config_repository()
        return await repo.get(bot_id) is not None
    except Exception:
        return False


async def wait_qrcode(account_data_dir: Path, since: datetime, timeout_sec: int = 60) -> Path | None:
    qr_path = account_data_dir / "cache" / "qrcode.png"
    deadline = asyncio.get_running_loop().time() + timeout_sec
    while asyncio.get_running_loop().time() < deadline:
        if qr_path.is_file():
            try:
                mtime = datetime.fromtimestamp(qr_path.stat().st_mtime, tz=since.tzinfo)
                if mtime >= since:
                    return qr_path
            except OSError:
                pass
        await asyncio.sleep(1.2)
    return None


def append_text(result: ReloginHandleResult, text: str) -> None:
    result.replies.append(ReplyItem(kind="text", content=text))


def append_qrcode(result: ReloginHandleResult, qr_path: Path) -> None:
    try:
        data = base64.b64encode(qr_path.read_bytes()).decode("ascii")
    except OSError as err:
        append_text(result, f"二维码读取失败：{err}")
        return
    result.replies.append(ReplyItem(kind="image_base64", content=data))


async def run_relogin_restart(qq: str, result: ReloginHandleResult) -> None:
    from src.plugins.pallas_protocol import manager as protocol_manager

    account = protocol_manager.get_account(qq) or {}
    account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
    if not account_data_dir:
        append_text(result, "账号目录缺失，无法执行重新上号。")
        return

    append_text(result, "正在启动协议端...")
    started_at = datetime.now().astimezone()
    try:
        await protocol_manager.restart_account(qq)
    except Exception as err:
        append_text(result, f"启动失败：{err}")
        return

    qr_path = await wait_qrcode(account_data_dir, started_at)
    if qr_path is None:
        append_text(result, "已完成启动，但在 60 秒内未检测到新的二维码文件，请寻找号主上报情况")
        return

    append_text(result, "启动完成，请使用下面二维码登录：")
    append_qrcode(result, qr_path)


async def handle_relogin_message(
    *,
    bot_id: str,
    user_id: str,
    text: str,
) -> ReloginHandleResult:
    result = ReloginHandleResult()
    key = session_key(bot_id, user_id)
    session = _sessions.get(key)
    plain = (text or "").strip()
    su = user_is_superuser_id(user_id)

    if session is None and plain.startswith("牛牛重新上号"):
        arg = plain.removeprefix("牛牛重新上号").strip()
        qq = extract_qq(arg)
        if qq:
            session = ReloginSession(kind="relogin", step="validate_qq", data={"qq": qq})
            _sessions[key] = session
        else:
            append_text(result, "请回复要重新上号的QQ号：")
            _sessions[key] = ReloginSession(kind="relogin", step="await_qq")
            result.session_active = True
            return result

    if session is None and plain.startswith("创建牛牛"):
        arg = plain.removeprefix("创建牛牛").strip()
        if arg:
            parts = arg.split()
            if len(parts) < 3:  # noqa: PLR2004
                append_text(result, "参数不足，需要：牛牛昵称 牛牛账号 号主账号（至少一个）")
                return result
            display_name, qq, *owner_qqs = parts
            if not qq.isdigit() or len(qq) < 5:  # noqa: PLR2004
                append_text(result, "牛牛账号格式不正确")
                return result
            invalid = [oq for oq in owner_qqs if not oq.isdigit()]
            if invalid:
                append_text(result, f"号主账号格式不正确：{'、'.join(invalid)}")
                return result
            session = ReloginSession(
                kind="create",
                step="execute",
                data={
                    "display_name": display_name,
                    "qq": qq,
                    "owner_qqs": owner_qqs,
                    "interactive": False,
                },
            )
            _sessions[key] = session
        else:
            append_text(result, "请输入牛牛昵称：")
            _sessions[key] = ReloginSession(kind="create", step="await_name", data={"interactive": True})
            result.session_active = True
            return result

    if session is None:
        return result

    if session.kind == "relogin":
        await handle_relogin_session(session, user_id, plain, su, result, key)
    else:
        await handle_create_session(session, plain, result, key)

    if not result.session_active:
        clear_session(bot_id, user_id)
    return result


async def handle_relogin_session(
    session: ReloginSession,
    user_id: str,
    plain: str,
    su: bool,
    result: ReloginHandleResult,
    key: str,
) -> None:
    if session.step == "await_qq":
        if plain in _CANCEL_WORDS:
            append_text(result, "已取消重新上号。")
            return
        qq = extract_qq(plain)
        if not qq:
            result.reject_hint = "QQ号格式不正确，请重新输入："
            result.session_active = True
            return
        session.step = "validate_qq"
        session.data["qq"] = qq

    if session.step == "validate_qq":
        from src.plugins.pallas_protocol import manager as protocol_manager

        qq = str(session.data.get("qq", ""))
        is_target_admin = await user_is_bot_admin(int(qq), int(user_id))
        if not (is_target_admin or su):
            append_text(result, f"你不是 {qq} 的管理员，无法执行重新上号。")
            return

        if protocol_manager.has_account(qq):
            session.step = "execute"
        elif not await bot_id_exists_in_db(int(qq)):
            append_text(result, f"数据库中不存在账号为：{qq} 的牛牛")
            return
        else:
            session.step = "await_nickname"
            append_text(result, "该账号协议端不存在，请输入牛牛昵称以自动创建：")
            result.session_active = True
            _sessions[key] = session
            return

    if session.step == "await_nickname":
        qq = str(session.data.get("qq", ""))
        if plain in _CANCEL_WORDS:
            append_text(result, "已取消重新上号。")
            return
        nickname = plain.strip()
        if not nickname:
            result.reject_hint = "昵称不能为空，请重新输入："
            result.session_active = True
            return
        try:
            from src.plugins.pallas_protocol import manager as protocol_manager

            protocol_manager.create_account({"qq": qq, "display_name": nickname, "enabled": True})
            append_text(result, f"已创建 {nickname} 并继续上号流程。")
        except Exception as err:
            append_text(result, f"自动创建协议端失败：{err}")
            return
        session.step = "execute"

    if session.step == "execute":
        qq = str(session.data.get("qq", ""))
        await run_relogin_restart(qq, result)


async def handle_create_session(
    session: ReloginSession,
    plain: str,
    result: ReloginHandleResult,
    key: str,
) -> None:
    interactive = bool(session.data.get("interactive"))

    if session.step == "await_name":
        if plain in _CANCEL_WORDS:
            append_text(result, "已取消创建牛牛。")
            return
        if not plain.strip():
            result.reject_hint = "昵称不能为空，请重新输入："
            result.session_active = True
            return
        session.data["display_name"] = plain.strip()
        session.step = "await_qq"
        if interactive:
            append_text(result, "请输入牛牛QQ号：")
            result.session_active = True
            _sessions[key] = session
        return

    if session.step == "await_qq":
        if plain in _CANCEL_WORDS:
            append_text(result, "已取消创建牛牛。")
            return
        qq = plain.strip()
        if not qq.isdigit() or len(qq) < 5:  # noqa: PLR2004
            result.reject_hint = "QQ号格式不正确，请重新输入："
            result.session_active = True
            return
        session.data["qq"] = qq
        session.step = "await_owners"
        if interactive:
            append_text(result, "请输入号主QQ号（如有多个用空格分隔）：")
            result.session_active = True
            _sessions[key] = session
        return

    if session.step == "await_owners":
        if plain in _CANCEL_WORDS:
            append_text(result, "已取消创建牛牛。")
            return
        owner_qqs = plain.strip().split()
        if not owner_qqs:
            result.reject_hint = "号主账号不能为空，请重新输入："
            result.session_active = True
            return
        invalid = [oq for oq in owner_qqs if not oq.isdigit()]
        if invalid:
            result.reject_hint = f"号主账号格式不正确：{'、'.join(invalid)}，请重新输入："
            result.session_active = True
            return
        session.data["owner_qqs"] = owner_qqs
        session.step = "execute"

    if session.step != "execute":
        return

    from src.plugins.pallas_protocol import manager as protocol_manager

    display_name = str(session.data.get("display_name", "")).strip()
    qq = str(session.data.get("qq", "")).strip()
    owner_qqs = list(session.data.get("owner_qqs") or [])

    try:
        protocol_manager.create_account({"qq": qq, "display_name": display_name, "enabled": True})
    except Exception as err:
        append_text(result, f"创建账号失败：{err}")
        return

    account = protocol_manager.get_account(qq) or {}
    account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
    if not account_data_dir:
        append_text(result, "账号已创建，但账号目录缺失，无法启动。")
        return

    append_text(result, "正在启动协议端...")
    started_at = datetime.now().astimezone()
    try:
        await protocol_manager.start_account(qq)
    except Exception as err:
        append_text(result, f"账号已创建，但启动失败：{err}")
        return

    owner_ids = [int(oq) for oq in owner_qqs]
    try:
        repo = make_bot_config_repository()
        await repo.upsert_field(int(qq), "admins", owner_ids)
        from src.foundation.config.bot_admins_cache import invalidate_bot_admins_cache

        await invalidate_bot_admins_cache(int(qq))
    except Exception as err:
        append_text(result, f"账号已创建并启动，但写入号主失败：{err}")
        return

    qr_path = await wait_qrcode(account_data_dir, started_at)
    if qr_path is not None:
        append_text(result, "请使用下面二维码完成登录：")
        append_qrcode(result, qr_path)

    owners_str = "、".join(owner_qqs)
    timeout_hint = "\n但在 60 秒内未检测到新的二维码文件，请到协议端控制台查看或联系管理员。" if qr_path is None else ""
    append_text(result, f"{display_name}：{qq} 已创建并启动。\n号主：{owners_str}{timeout_hint}")
