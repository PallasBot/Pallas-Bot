from .config import Config, get_help_config
from .styles import get_default_style, load_custom_styles

AVAILABLE_STYLES: dict[str, object] = {}
DEFAULT_STYLE_NAME: str = ""


def refresh_style_cache(cfg: Config | None = None) -> None:
    global AVAILABLE_STYLES, DEFAULT_STYLE_NAME
    c = cfg or get_help_config()
    AVAILABLE_STYLES = load_custom_styles(c)
    DEFAULT_STYLE_NAME = get_default_style(c)
