from pydantic import BaseModel


class Config(BaseModel, extra="ignore"):
    ai_server_host: str = "127.0.0.1"
    ai_server_port: int = 9099
    sing_enable: bool = False
    sing_endpoint: str = "/api/sing"
    play_endpoint: str = "/api/play"
    sing_length: int = 120
    sing_speakers: dict = {
        "帕拉斯": "pallas",
        "牛牛": "pallas",
    }
