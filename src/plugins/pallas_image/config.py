from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class Config(BaseModel, extra="ignore"):
    pallas_image_min_priority: int = 5
    pallas_image_base_url: str = ""
    pallas_image_api_key: str = ""
    pallas_image_model: str = "gpt-image-2"
    # 与 size 二选一；皆空则请求体不传比例/尺寸，由接口默认
    pallas_image_aspect_ratio: str = Field(
        default="",
        description="如 21:9, 16:9, 1:1 等；非空才写入 generations 的 aspect_ratio",
    )
    pallas_image_size: str = ""
    pallas_image_quality: str = "auto"
    pallas_image_response_format: str = "b64_json"
    pallas_image_use_edits_for_reference_images: bool = True
    pallas_image_merge_reference_urls_into_prompt: bool = False
    pallas_image_default_edit_prompt: str = "按参考图调整"
    pallas_image_request_timeout: float = Field(default=180.0, gt=10.0, le=600.0)
    pallas_image_max_concurrency: int = Field(default=2, ge=1, le=16)
    pallas_image_http_transport: str = "auto"
    pallas_image_tls_impersonate: str = "chrome124"
    pallas_image_http_user_agent: str = "curl/8.5.0"
    pallas_image_draw_group_whitelist: list[int] = Field(default_factory=list)
    pallas_image_draw_per_user_limit: int = Field(
        default=0,
        ge=0,
        le=1_000_000,
        description="每人每天在每群可调用「牛牛画画」次数上限；0 表示不限制（按进程本地日期）",
    )
    pallas_image_draw_unlimited_group_ids: list[int] = Field(default_factory=list)
    pallas_image_draw_unlimited_user_ids: list[int] = Field(default_factory=list)
    pallas_image_draw_command_cooldown: int = Field(default=3, ge=0, le=3600)


_raw = get_plugin_config(Config)


class ImageGenSettings:
    __slots__ = ("_c", "_draw_unlimited_groups", "_draw_unlimited_users")

    def __init__(self, c: Config) -> None:
        object.__setattr__(self, "_c", c)
        object.__setattr__(
            self,
            "_draw_unlimited_groups",
            frozenset(c.pallas_image_draw_unlimited_group_ids),
        )
        object.__setattr__(
            self,
            "_draw_unlimited_users",
            frozenset(c.pallas_image_draw_unlimited_user_ids),
        )

    @property
    def min_priority(self) -> int:
        return self._c.pallas_image_min_priority

    @property
    def base_url(self) -> str:
        return self._c.pallas_image_base_url

    @property
    def api_key(self) -> str:
        return self._c.pallas_image_api_key

    @property
    def model(self) -> str:
        return self._c.pallas_image_model

    @property
    def aspect_ratio(self) -> str:
        return self._c.pallas_image_aspect_ratio

    @property
    def size(self) -> str:
        return self._c.pallas_image_size

    @property
    def quality(self) -> str:
        return self._c.pallas_image_quality

    @property
    def response_format(self) -> str:
        return self._c.pallas_image_response_format

    @property
    def use_edits_for_reference_images(self) -> bool:
        return self._c.pallas_image_use_edits_for_reference_images

    @property
    def merge_reference_urls_into_prompt(self) -> bool:
        return self._c.pallas_image_merge_reference_urls_into_prompt

    @property
    def default_edit_prompt(self) -> str:
        return self._c.pallas_image_default_edit_prompt

    @property
    def request_timeout(self) -> float:
        return self._c.pallas_image_request_timeout

    @property
    def max_concurrency(self) -> int:
        return self._c.pallas_image_max_concurrency

    @property
    def http_transport(self) -> str:
        return self._c.pallas_image_http_transport

    @property
    def tls_impersonate(self) -> str:
        return self._c.pallas_image_tls_impersonate

    @property
    def http_user_agent(self) -> str:
        return self._c.pallas_image_http_user_agent

    @property
    def draw_group_whitelist(self) -> list[int]:
        return self._c.pallas_image_draw_group_whitelist

    @property
    def draw_per_user_limit(self) -> int:
        return self._c.pallas_image_draw_per_user_limit

    @property
    def draw_unlimited_group_ids(self) -> list[int]:
        return self._c.pallas_image_draw_unlimited_group_ids

    @property
    def draw_unlimited_user_ids(self) -> list[int]:
        return self._c.pallas_image_draw_unlimited_user_ids

    @property
    def draw_unlimited_group_ids_set(self) -> frozenset[int]:
        return self._draw_unlimited_groups

    @property
    def draw_unlimited_user_ids_set(self) -> frozenset[int]:
        return self._draw_unlimited_users

    @property
    def draw_command_cooldown(self) -> int:
        return self._c.pallas_image_draw_command_cooldown


image_gen_config = ImageGenSettings(_raw)
