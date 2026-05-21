from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field

from src.common.webui import config_from_env, install_hot_reload_config


class ImageBackendEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: str = Field(
        default="",
        description="显示名称（网关检测、牛牛网关命令等）；留空则按顺序显示为备线 N。",
    )
    base_url: str = Field(
        default="",
        description="备选 API 根 URL（建议以 / 结尾；插件会拼接 v1/images/...，勿写成 .../v1）。",
    )
    api_key: str = Field(default="", description="备选 API 密钥。")
    model: str = Field(
        default="",
        description="可选模型名；留空则使用主配置 pallas_image_model。",
    )
    omit_response_format: bool = Field(
        default=False,
        description=(
            "仅作用于本条备选：为 true 时请求体不含 OpenAI 的 response_format；"
            "由上游按自家文档返回图片（常见为 JSON 内 b64_json）。"
            "与全局 pallas_image_response_format 及厂商文档中的 output_format 不是同一参数。"
        ),
    )


class Config(BaseModel, extra="ignore"):
    pallas_image_min_priority: int = Field(
        default=5,
        description="「牛牛画画」等指令的插件优先级下限；数值越大越晚处理，便于被其他插件拦截。",
    )
    pallas_image_base_url: str = Field(
        default="",
        description=(
            "主 API 根 URL（如 OpenAI 兼容网关），须含协议；建议以 / 结尾。"
            "插件会拼接 v1/images/generations，勿将 base 写成已含 /v1 的路径以免重复。"
        ),
    )
    pallas_image_api_key: str = Field(default="", description="调用图像 API 的密钥或 Token。")
    pallas_image_primary_name: str = Field(
        default="",
        description="主网关显示名称；留空时 WebUI 与检测结果显示为「主网关」。",
    )
    pallas_image_api_backends: list[ImageBackendEntry] = Field(
        default_factory=list,
        description=(
            "备选 API 列表；主配置失败后按顺序尝试。"
            "每项含 base_url、api_key；name、model、omit_response_format 可选。"
            "WebUI 插件配置页提供列表编辑；环境变量仍为 JSON 数组。"
        ),
    )
    pallas_image_model: str = Field(default="gpt-image-2", description="默认使用的图像模型名。")
    pallas_image_aspect_ratio: str = Field(
        default="",
        description="画幅比例，如 21:9、16:9、1:1；与 size 二选一填写，皆空则由接口默认。",
    )
    pallas_image_size: str = Field(
        default="",
        description="像素尺寸规格（如 1024x1024）；与 aspect_ratio 二选一，皆空则由接口默认。",
    )
    pallas_image_quality: str = Field(default="auto", description="生成质量档位，取值依上游 API 文档。")
    pallas_image_response_format: str = Field(
        default="b64_json",
        description=(
            "主网关及未设 omit_response_format 的备选所请求的返回格式（如 b64_json、url）。"
            "若某备选上游无 response_format 字段，请在该备选网关条目勾选 omit_response_format。"
        ),
    )
    pallas_image_use_edits_for_reference_images: bool = Field(
        default=True,
        description="带参考图时是否走 edits 接口而非纯文生图。",
    )
    pallas_image_merge_reference_urls_into_prompt: bool = Field(
        default=False,
        description="是否把参考图 URL 合并写进提示词（部分网关需要）。",
    )
    pallas_image_default_edit_prompt: str = Field(
        default="按参考图调整",
        description="编辑/参考图模式未给出文案时使用的默认提示词。",
    )
    pallas_image_request_timeout: float = Field(
        default=180.0,
        ge=10.0,
        le=600.0,
        description="单次图像请求超时时间（秒）。",
    )
    pallas_image_max_concurrency: int = Field(
        default=2,
        ge=1,
        le=32,
        description="全局并发生成请求上限，防止打爆上游或本机。",
    )
    pallas_image_http_transport: str = Field(
        default="auto",
        description="HTTP 客户端实现：auto / httpx / curl 等，参见插件实现说明。",
    )
    pallas_image_tls_impersonate: str = Field(
        default="chrome124",
        description="使用 curl 模拟 TLS 指纹时的浏览器标识（如 chrome124）。",
    )
    pallas_image_http_user_agent: str = Field(
        default="curl/8.5.0",
        description="出站请求 User-Agent，部分 CDN 会校验。",
    )
    pallas_image_draw_group_whitelist: list[int] = Field(
        default_factory=list,
        description="非空时仅允许这些群号使用画画指令；空表示不按群白名单限制。",
    )
    pallas_image_draw_per_user_limit: int = Field(
        default=0,
        ge=0,
        le=1_000_000,
        description="每人每群每日可调用画画次数上限；0 为不限制（按进程自然日）。",
    )
    pallas_image_draw_unlimited_group_ids: list[int] = Field(
        default_factory=list,
        description="不受每人每日次数限制的群号列表。",
    )
    pallas_image_draw_unlimited_user_ids: list[int] = Field(
        default_factory=list,
        description="不受每人每日次数限制的 QQ 号列表。",
    )
    pallas_image_draw_command_cooldown: int = Field(
        default=3,
        ge=0,
        le=3600,
        description="同一群两次「牛牛画画」的最短间隔（秒）；在真正开始调用上游时扣减，非发「欢呼吧」时。",
    )
    # 画画重试与耗时：快档（换 response_format 等）优先，慢档（尺寸/quality 扫描）可关见下项
    pallas_image_max_param_attempts: int = Field(
        default=6,
        ge=0,
        le=32,
        description="每个 API backend 内最多尝试的参数组合数（快档+慢档合计）；0 不限制。",
    )
    pallas_image_slow_param_fallback: bool = Field(
        default=True,
        description="快档失败后是否继续慢档（遍历常见 size/quality 等）；关闭可显著减少失败耗时。",
    )
    pallas_image_draw_total_timeout: float = Field(
        default=480.0,
        gt=30.0,
        le=1800.0,
        description="单次画画从进入队列到结束的上限（秒），含排队、下载参考图与多轮重试；偏慢上游宜加大。",
    )
    pallas_image_ref_download_timeout: float = Field(
        default=30.0,
        gt=1.0,
        le=120.0,
        description="并行下载每张参考图的单张超时（秒）。",
    )
    pallas_image_draw_max_pending: int = Field(
        default=8,
        ge=0,
        le=64,
        description="进程内同时进行中的画画任务上限（含已回复「欢呼吧」尚未结束的）；0 不限制。",
    )

    @classmethod
    def from_env(cls) -> Self:
        return migrate_legacy_gateway_config(config_from_env(cls, parse_env_value=parse_pallas_image_env_value))


def migrate_legacy_gateway_config(c: Config) -> Config:
    """旧部署仅写 api_backends、主站 base_url/api_key 为空时，将首条有效备选提升为主网关。"""
    if (c.pallas_image_base_url or "").strip() and (c.pallas_image_api_key or "").strip():
        return c
    backends = list(c.pallas_image_api_backends)
    if not backends:
        return c
    first = backends[0]
    first_url = (first.base_url or "").strip()
    first_key = (first.api_key or "").strip()
    if not first_url or not first_key:
        return c
    first_name = (first.name or "").strip()
    first_model = (first.model or "").strip()
    global_model = (c.pallas_image_model or "").strip()
    updates: dict[str, Any] = {
        "pallas_image_base_url": first_url,
        "pallas_image_api_key": first_key,
        "pallas_image_api_backends": backends[1:],
        "pallas_image_model": first_model or global_model,
    }
    if not (c.pallas_image_primary_name or "").strip() and first_name:
        updates["pallas_image_primary_name"] = first_name
    return c.model_copy(update=updates)


def parse_pallas_image_env_value(name: str, raw: str, ann: Any) -> Any:
    text = raw.strip()
    ann_text = str(ann).lower()
    if "bool" in ann_text:
        return text.lower() in ("1", "true", "yes", "on")
    if "list" in ann_text or "dict" in ann_text:
        if not text:
            return [] if "list" in ann_text else {}
        parsed = json.loads(text)
        if name == "pallas_image_api_backends" and isinstance(parsed, list):
            return [ImageBackendEntry.model_validate(x) for x in parsed if isinstance(x, dict)]
        return parsed
    if "float" in ann_text and "list" not in ann_text:
        return float(text)
    if "int" in ann_text and "list" not in ann_text:
        return int(text)
    return text


@dataclass(frozen=True)
class ImageApiBackend:
    base_url: str
    api_key: str
    model: str
    label: str
    name: str = ""
    omit_response_format: bool = False


class ImageGenSettings:
    __slots__ = ("_c", "_draw_unlimited_groups", "_draw_unlimited_users")

    def __init__(self, c: Config) -> None:
        object.__setattr__(self, "_c", migrate_legacy_gateway_config(c))
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

    def reload(self, c: Config) -> None:
        object.__setattr__(self, "_c", migrate_legacy_gateway_config(c))
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

    def api_backends(self) -> list[ImageApiBackend]:
        default_model = (self._c.pallas_image_model or "").strip()
        out: list[ImageApiBackend] = []
        seen: set[tuple[str, str, str]] = set()

        def append(
            url: str,
            key: str,
            model: str,
            label: str,
            *,
            name: str = "",
            omit_response_format: bool = False,
        ) -> None:
            sig = (url, key, model)
            if sig in seen:
                return
            seen.add(sig)
            out.append(
                ImageApiBackend(
                    base_url=url,
                    api_key=key,
                    model=model,
                    label=label,
                    name=(name or "").strip(),
                    omit_response_format=omit_response_format,
                )
            )

        primary_url = (self._c.pallas_image_base_url or "").strip()
        primary_key = (self._c.pallas_image_api_key or "").strip()
        primary_name = (self._c.pallas_image_primary_name or "").strip()
        if primary_url and primary_key:
            append(
                primary_url,
                primary_key,
                default_model,
                "primary",
                name=primary_name,
            )
        for i, entry in enumerate(self._c.pallas_image_api_backends):
            url = (entry.base_url or "").strip()
            key = (entry.api_key or "").strip()
            if not url or not key:
                continue
            model = (entry.model or "").strip() or default_model
            append(
                url,
                key,
                model,
                f"fallback-{i}",
                name=(entry.name or "").strip(),
                omit_response_format=entry.omit_response_format,
            )
        return out

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

    @property
    def max_param_attempts(self) -> int:
        return self._c.pallas_image_max_param_attempts

    @property
    def slow_param_fallback(self) -> bool:
        return self._c.pallas_image_slow_param_fallback

    @property
    def draw_total_timeout(self) -> float:
        return self._c.pallas_image_draw_total_timeout

    @property
    def ref_download_timeout(self) -> float:
        return self._c.pallas_image_ref_download_timeout

    @property
    def draw_max_pending(self) -> int:
        return self._c.pallas_image_draw_max_pending


def on_pallas_image_config_reload(cfg: Config) -> None:
    image_gen_config.reload(cfg)
    from .runtime_state import sync_image_gen_semaphore

    sync_image_gen_semaphore(cfg.pallas_image_max_concurrency)


plugin_webui = install_hot_reload_config(
    Config,
    config_module=__name__,
    parse_env_value=parse_pallas_image_env_value,
    on_reload=on_pallas_image_config_reload,
)
get_pallas_image_config = plugin_webui.get
reload_image_gen_config = plugin_webui.reload
clear_pallas_image_config_cache = plugin_webui.clear_cache


def active_image_gen_settings() -> ImageGenSettings:
    """刷新磁盘/环境配置并返回进程内 image_gen_config（与 WebUI 热重载一致）。"""
    reload_image_gen_config()
    return image_gen_config


image_gen_config = ImageGenSettings(get_pallas_image_config())
