from pydantic import BaseModel


class Config(BaseModel, extra="ignore"):
    # 是否将申请通知发送给 SUPERUSER（默认不发送，避免重复打扰）
    request_handler_notify_superusers: bool = False
    # 是否定时轮询「被过滤」好友申请并私聊管理员（间隔 4 小时）
    request_handler_poll_doubt_friends: bool = True
