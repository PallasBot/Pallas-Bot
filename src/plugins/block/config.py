from pydantic import BaseModel


class Config(BaseModel, extra="ignore"):
    bots: set[int] = set()
