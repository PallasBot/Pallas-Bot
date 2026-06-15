"""生图请求参数组合与回退序列。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .config import image_gen_config

COMMON_QUALITIES = ("auto", "standard", "high", "medium", "low", "hd")
COMMON_SIZES = ("1024x1024", "1024x1792", "1792x1024", "512x512")
COMMON_ASPECT_RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4")


@dataclass(frozen=True)
class ImageGenRequestOptions:
    size: str = ""
    aspect_ratio: str = ""
    quality: str = ""
    response_format: str = ""
    include_ref_images: bool = True

    @classmethod
    def from_config(cls) -> ImageGenRequestOptions:
        cfg = image_gen_config
        return cls(
            size=(cfg.size or "").strip(),
            aspect_ratio=(cfg.aspect_ratio or "").strip(),
            quality=(cfg.quality or "").strip(),
            response_format=(cfg.response_format or "b64_json").strip(),
            include_ref_images=True,
        )

    def log_label(self) -> str:
        parts: list[str] = []
        if self.size:
            parts.append(f"size={self.size}")
        elif self.aspect_ratio:
            parts.append(f"aspect_ratio={self.aspect_ratio}")
        if self.quality:
            parts.append(f"quality={self.quality}")
        if self.response_format:
            parts.append(f"response_format={self.response_format}")
        if not self.include_ref_images:
            parts.append("no_image_field")
        return " ".join(parts) if parts else "minimal"


def response_format_attempts(configured: str | None = None) -> list[str]:
    primary = (
        (configured if configured is not None else (image_gen_config.response_format or "b64_json")).strip().lower()
    )
    if primary == "b64_json":
        return ["b64_json", "url"]
    if primary == "url":
        return ["url", "b64_json"]
    if primary:
        return [primary, "b64_json", "url"]
    return ["b64_json", "url"]


def quality_attempts(configured: str) -> list[str]:
    primary = configured.strip()
    out: list[str] = []
    if primary:
        out.append(primary)
    if "" not in out:
        out.append("")
    out.extend(q for q in COMMON_QUALITIES if q != primary)
    return out


def dimension_attempts(size: str, aspect_ratio: str) -> list[tuple[str, str]]:
    primary_s = size.strip()
    primary_ar = aspect_ratio.strip()
    out: list[tuple[str, str]] = []
    if primary_s:
        out.append((primary_s, ""))
    elif primary_ar:
        out.append(("", primary_ar))
    if ("", "") not in out:
        out.append(("", ""))
    out.extend((s, "") for s in COMMON_SIZES if s != primary_s)
    out.extend(("", ar) for ar in COMMON_ASPECT_RATIOS if ar != primary_ar)
    return out


def dedupe_request_options(options: list[ImageGenRequestOptions]) -> list[ImageGenRequestOptions]:
    seen: set[tuple[str, str, str, str, bool]] = set()
    out: list[ImageGenRequestOptions] = []
    for o in options:
        key = (o.size, o.aspect_ratio, o.quality, o.response_format, o.include_ref_images)
        if key in seen:
            continue
        seen.add(key)
        out.append(o)
    return out


def without_response_format(opt: ImageGenRequestOptions) -> ImageGenRequestOptions:
    return replace(opt, response_format="")


def image_gen_fast_attempts(
    *,
    with_ref_urls: bool,
    omit_response_format: bool = False,
) -> list[ImageGenRequestOptions]:
    """快档：配置原样、换 response_format、去 quality、去 image 字段。"""
    base = ImageGenRequestOptions.from_config()
    if omit_response_format:
        base = without_response_format(base)
    seq: list[ImageGenRequestOptions] = [base]
    if not omit_response_format:
        seq.extend(
            replace(base, response_format=rf)
            for rf in response_format_attempts(base.response_format)
            if rf != base.response_format
        )
    if base.quality:
        seq.append(replace(base, quality=""))
    merge_refs = image_gen_config.merge_reference_urls_into_prompt
    if with_ref_urls and not merge_refs:
        seq.append(replace(base, include_ref_images=False))
    return dedupe_request_options(seq)


def image_gen_slow_attempts(
    *,
    with_ref_urls: bool,
    omit_response_format: bool = False,
) -> list[ImageGenRequestOptions]:
    """慢档：常见 quality / 尺寸 / 极简组合。"""
    base = ImageGenRequestOptions.from_config()
    if omit_response_format:
        base = without_response_format(base)
    fast_keys = {
        (o.size, o.aspect_ratio, o.quality, o.response_format, o.include_ref_images)
        for o in image_gen_fast_attempts(
            with_ref_urls=with_ref_urls,
            omit_response_format=omit_response_format,
        )
    }
    seq: list[ImageGenRequestOptions] = []

    def add(opt: ImageGenRequestOptions) -> None:
        key = (opt.size, opt.aspect_ratio, opt.quality, opt.response_format, opt.include_ref_images)
        if key not in fast_keys:
            seq.append(opt)

    for q in quality_attempts(base.quality):
        if q and q != base.quality:
            add(replace(base, quality=q))
    for sz, ar in dimension_attempts(base.size, base.aspect_ratio):
        if sz != base.size or ar != base.aspect_ratio:
            add(replace(base, size=sz, aspect_ratio=ar))
    relaxed = replace(base, size="", aspect_ratio="", quality="")
    add(relaxed)
    if not omit_response_format:
        for rf in response_format_attempts(""):
            add(replace(relaxed, response_format=rf))
    merge_refs = image_gen_config.merge_reference_urls_into_prompt
    if with_ref_urls and not merge_refs:
        add(replace(relaxed, include_ref_images=False))
    return dedupe_request_options(seq)


def capped_param_attempts(
    *,
    with_ref_urls: bool,
    omit_response_format: bool = False,
) -> list[ImageGenRequestOptions]:
    """快档 + 可选慢档，受 max_param_attempts 限制。"""
    fast = image_gen_fast_attempts(
        with_ref_urls=with_ref_urls,
        omit_response_format=omit_response_format,
    )
    out = list(fast)
    if not image_gen_config.slow_param_fallback:
        max_n = image_gen_config.max_param_attempts
        return out[:max_n] if max_n > 0 else out
    slow = image_gen_slow_attempts(
        with_ref_urls=with_ref_urls,
        omit_response_format=omit_response_format,
    )
    seen = {(o.size, o.aspect_ratio, o.quality, o.response_format, o.include_ref_images) for o in out}
    for o in slow:
        key = (o.size, o.aspect_ratio, o.quality, o.response_format, o.include_ref_images)
        if key in seen:
            continue
        seen.add(key)
        out.append(o)
    max_n = image_gen_config.max_param_attempts
    if max_n > 0:
        return out[:max_n]
    return out


def image_gen_request_attempts(
    *,
    with_ref_urls: bool,
    omit_response_format: bool = False,
) -> list[ImageGenRequestOptions]:
    """兼容旧名：等同 capped_param_attempts。"""
    return capped_param_attempts(
        with_ref_urls=with_ref_urls,
        omit_response_format=omit_response_format,
    )
