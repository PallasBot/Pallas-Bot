from pydantic import BaseModel


class Config(BaseModel, extra="ignore"):
    ai_server_host: str = "127.0.0.1"
    ai_server_port: int = 9099
    chat_enable: bool = False
    chat_endpoint: str = "/api/chat"
    del_session_endpoint: str = "/api/del_session"
    tts_enable: bool = False
