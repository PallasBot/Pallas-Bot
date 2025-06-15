from pydantic import BaseModel


class Config(BaseModel, extra="ignore"):
    sing_speakers: dict = {
        "帕拉斯": "pallas",
        "牛牛": "pallas",
    }
