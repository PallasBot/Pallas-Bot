import re

from nonebot import get_plugin_config, on_command
from nonebot.adapters.onebot.v11 import MessageEvent, PrivateMessageEvent
from nonebot.params import ArgStr
from nonebot.permission import SUPERUSER
from nonebot.typing import T_State
from pydantic import BaseModel
from pyncm_async import apis as ncm

from src.common.utils import HTTPXClient


class NCMLoginConfig(BaseModel, extra="ignore"):
    ai_server_host: str = "127.0.0.1"
    ai_server_port: int = 9099
    ncm_login_endpoint: str = "/api/ncm/login/cellphone/send-sms"
    ncm_verify_endpoint: str = "/api/ncm/login/cellphone/verify-sms"
    ncm_login_status_endpoint: str = "/api/ncm/login/status"
    ncm_logout_endpoint: str = "/api/ncm/logout"


plugin_config = get_plugin_config(NCMLoginConfig)

SERVER_URL = f"http://{plugin_config.ai_server_host}:{plugin_config.ai_server_port}"

ncm_login_cmd = on_command("网易云登录", priority=10, block=True, permission=SUPERUSER)
ncm_logout_cmd = on_command("网易云登出", priority=10, block=True, permission=SUPERUSER)


@ncm_login_cmd.handle()
async def handle_first_receive(event: MessageEvent, state: T_State):
    if not isinstance(event, PrivateMessageEvent):
        return

    # 检查是否已经登录
    if await is_ncm_logged_in():
        await ncm_login_cmd.finish("已登录")
        return

    state["need_phone"] = True
    await ncm_login_cmd.send("请输入手机号：")


@ncm_login_cmd.got("phone")
async def got_phone(event: MessageEvent, state: T_State, phone: str = ArgStr()):
    if not state.get("need_phone"):
        return

    phone = phone.strip()
    if not re.match(r"^1[3-9]\d{9}$", phone):
        await ncm_login_cmd.reject("手机号格式不正确，请重新输入：")

    state["phone"] = phone

    try:
        url = f"{SERVER_URL}{plugin_config.ncm_login_endpoint}"
        response = await HTTPXClient.post(url, json={"phone": phone, "ctcode": 86})

        if response and response.json().get("code", 0) == 200:
            await ncm_login_cmd.send("验证码已发送，请查收短信。")
        else:
            await ncm_login_cmd.send("验证码发送失败，但仍可尝试输入验证码进行登录。")

    except Exception:
        await ncm_login_cmd.send("验证码发送失败，但仍可尝试输入验证码进行登录。")  # 强硬一点塞进去（

    state["need_captcha"] = True


@ncm_login_cmd.got("captcha")
async def got_captcha(event: MessageEvent, state: T_State, captcha: str = ArgStr()):
    if not state.get("need_captcha"):
        return

    captcha = captcha.strip()
    if not re.match(r"^\d{4,8}$", captcha):
        await ncm_login_cmd.reject("验证码格式不正确，请重新输入：")

    phone = state["phone"]

    try:
        url = f"{SERVER_URL}{plugin_config.ncm_verify_endpoint}"
        response = await HTTPXClient.post(
            url,
            json={"phone": phone, "captcha": captcha, "ctcode": 86},
        )

        if response and response.json().get("success"):
            await ncm_login_cmd.send("登录成功！")
        else:
            await ncm_login_cmd.finish("登录失败，请检查验证码是否正确。")

    except Exception:
        await ncm_login_cmd.finish("登录过程中出现错误，请稍后重试。")


@ncm_logout_cmd.handle()
async def handle_logout(event: MessageEvent):
    if not isinstance(event, PrivateMessageEvent):
        return

    try:
        url = f"{SERVER_URL}{plugin_config.ncm_logout_endpoint}"
        response = await HTTPXClient.post(url)
        if response and response.json().get("success"):
            await ncm_logout_cmd.finish("已成功退出网易云音乐账号。")
        else:
            await ncm_logout_cmd.finish("登出失败，请稍后重试。")
    except Exception:
        await ncm_logout_cmd.finish("登出过程中出现错误，请稍后重试。")


async def is_ncm_logged_in():
    try:
        url = f"{SERVER_URL}{plugin_config.ncm_login_status_endpoint}"
        response = await HTTPXClient.get(url)
        if response and response.json().get("success"):
            return True
        return False
    except Exception:
        return False


async def get_song_id(song_name: str):
    if not song_name:
        return None
    if song_name.isdigit():
        return song_name

    res = await ncm.cloudsearch.GetSearchResult(song_name, 1, 10)
    if "result" not in res or "songCount" not in res["result"]:
        return None

    if res["result"]["songCount"] == 0:
        return None

    logged_in = await is_ncm_logged_in()

    for song in res["result"]["songs"]:
        # 如果未登录，跳过vip
        if not logged_in:
            privilege = song["privilege"]
            if "chargeInfoList" not in privilege:
                continue

            charge_info_list = privilege["chargeInfoList"]
            if len(charge_info_list) == 0:
                continue

            if charge_info_list[0]["chargeType"] == 1:
                continue

        return song["id"]

    return None


async def get_song_title(song_id):
    response = await ncm.track.GetTrackDetail(song_id)
    return response["songs"][0]["name"]
