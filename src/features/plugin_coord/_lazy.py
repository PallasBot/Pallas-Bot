from __future__ import annotations

import importlib
from typing import Any


def import_symbol(module_path: str, name: str) -> Any | None:
    return import_symbol_any((module_path,), name)


def import_symbol_any(module_paths: tuple[str, ...] | list[str], name: str) -> Any | None:
    for module_path in module_paths:
        try:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, name, None)
            if fn is not None:
                return fn
        except Exception:
            continue
    return None
