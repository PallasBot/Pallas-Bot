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
        description="dist 的 zip 直链；留空时按 repo/tag/asset 自动拼接 GitHub Releases 下载地址",
    )
    pallas_webui_dist_zip_repo: str = Field(
        default="PallasBot/Pallas-Bot-WebUI",
        description="pallas_webui_dist_zip_url 为空时生效：GitHub 仓库（Owner/Repo）",
    )
    pallas_webui_dist_zip_tag: str = Field(
        default="",
        description="pallas_webui_dist_zip_url 为空时生效：版本标签（空=latest）",
    )
    pallas_webui_dist_zip_asset: str = Field(
        default="dist.zip",
        description="pallas_webui_dist_zip_url 为空时生效：发布资产文件名",
    )
    pallas_webui_cors: bool = Field(
        default=False,
        description=(
            "为开发时前后端分离调试开启 CORS（例如 Vite dev 连远程 Bot）；启用前请同时配置 pallas_webui_allowed_origins"
        ),
    )
    pallas_webui_allowed_origins: list[str] = Field(
        default_factory=list,
        description=(
            "启用 CORS 时允许的来源列表（如 ['http://localhost:5173']）；"
            "为空则不挂载 CORS 中间件；含 '*' 时强制关闭 allow_credentials"
        ),
    )
    pallas_webui_log_lines_max: int = Field(
        default=2000,
        ge=50,
        le=5000,
        description="GET /pallas/api/logs 单次返回的最大行数上限",
    )
    pallas_webui_api_token: str = Field(
        default="",
        description="控制台 API 鉴权 token；未配置时 /pallas/api/* 全部禁用（仅 /pallas/api/health 例外）",
    )
