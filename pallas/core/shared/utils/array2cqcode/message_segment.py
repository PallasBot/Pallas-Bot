class BaseMessageSegment:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    @property
    def cqcode(self):
        if self.type == "text":
            text = (self.data or {}).get("text")
            return "" if text is None else str(text)
        message = f"[CQ:{self.type}"
        data = self.__dict__.get("data") or {}
        for k, v in data.items():
            message += f",{k}={self.escape(v)}"
        message += "]"
        return message

    @staticmethod
    def escape(data: object) -> str:
        # OneBot 段字段常为 int（如 at.qq），须先转成 str 再做 CQ 转义
        return str(data).replace("&", "&amp;").replace("[", "&#91;").replace("]", "&#93;").replace(",", "&#44;")
