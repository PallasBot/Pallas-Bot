"""Pallas 控制台：与主程序分离的 Web 前端，通过本插件挂载静态与 API；配置原因见主插件 __init__ 说明。"""

from pydantic import BaseModel, Field


class Config(BaseModel):
    pallas_webui_enabled: bool = True
    pallas_webui_http_base: str = Field(
        default="/pallas",
        description="浏览器访问路径前缀，需与 Vite 的 base 一致（如 /pallas/）",
    )
    pallas_webui_dist_zip_url: str = Field(
        default="",
        description="dist 的 zip 直链；非空且 public 下无 index.html 时自动下载并解压",
    )
    pallas_webui_cors: bool = Field(
        default=True,
        description="为开发时前后端分离调试开启 CORS（例如 Vite dev 连远程 Bot）",
    )
    pallas_webui_log_lines_max: int = Field(
        default=2000,
        ge=50,
        le=5000,
        description="GET /pallas/api/logs 单次返回的最大行数上限",
    )
    pallas_webui_api_token: str = Field(
        default="",
        description="非空时：对 Bot/群 配置、实例相关写操作要求 X-Pallas-Token 或 ?token=",
    )
