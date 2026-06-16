from pydantic import BaseModel, Field


class Config(BaseModel):
    template_enable: bool = Field(default=True, description="模板开关")
