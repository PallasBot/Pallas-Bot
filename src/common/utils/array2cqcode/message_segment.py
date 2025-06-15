class BaseMessageSegment:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    @property
    def cqcode(self):
        if self.type == "text":
            return self.data.get("text")
        message = f"[CQ:{self.type}"
        for k, v in self.__dict__.get("data").items():
            message += f",{k}={self.escape(v)}"
        message += "]"
        return message

    @staticmethod
    def escape(data: str) -> str:
        return data.replace("&", "&amp;").replace("[", "&#91;").replace("]", "&#93;").replace(",", "&#44;")
