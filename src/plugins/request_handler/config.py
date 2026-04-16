from pydantic import BaseModel


class Config(BaseModel, extra="ignore"):
    # 是否将申请通知发送给 SUPERUSER（默认不发送，避免重复打扰）
    request_handler_notify_superusers: bool = False
