"""AI 仓（Pallas-Bot-AI）运行时专属环境键：不应由 Bot webui.json 落盘或注入 os.environ。"""

from __future__ import annotations

# 遗留 pip ollama 插件写入 Bot webui 的端点键，4.0 已改由 AI 仓统一 API 承担。
DEPRECATED_OLLAMA_PLUGIN_ENV_KEYS: frozenset[str] = frozenset({
    "OLLAMA_CHAT_ENDPOINT",
    "OLLAMA_DEL_SESSION_ENDPOINT",
    "OLLAMA_UNLOAD_ENDPOINT",
    "OLLAMA_MODEL_ENDPOINT",
    "OLLAMA_SYSTEM_PROMPT_PATH",
    "OLLAMA_MIN_PRIORITY",
})

# 推理后端 / Celery / 模型运行时参数，仅应在 Pallas-Bot-AI 的 .env 或运行时文件配置。
AI_SERVICE_RUNTIME_ENV_KEYS: frozenset[str] = frozenset({
    "LLM_NUM_GPU",
    "OLLAMA_NUM_GPU",
    "LLM_MODEL",
    "OLLAMA_MODEL",
    "LLM_BACKEND_URL",
    "OLLAMA_URL",
    "LLM_AUTO_START",
    "OLLAMA_AUTO_START",
    "LLM_AUTO_PULL",
    "OLLAMA_AUTO_PULL",
    "LLM_STARTUP_TIMEOUT",
    "OLLAMA_STARTUP_TIMEOUT",
    "LLM_TEMPERATURE",
    "OLLAMA_TEMPERATURE",
    "LLM_REQUEST_TIMEOUT",
    "OLLAMA_REQUEST_TIMEOUT",
    "LLM_MAX_HISTORIES",
    "OLLAMA_MAX_HISTORIES",
    "LLM_MAX_RETRIES",
    "OLLAMA_MAX_RETRIES",
    "LLM_RETRY_BACKOFF",
    "OLLAMA_RETRY_BACKOFF",
    "LLM_THINK_ENABLED",
    "LLM_PROVIDER_MODE",
    "LLM_REMOTE_BASE_URL",
    "LLM_REMOTE_API_KEY",
    "LLM_REMOTE_MODEL",
    "CELERY_WORKER_CONCURRENCY",
    "CELERY_WORKER_SOFT_SHUTDOWN_TIMEOUT",
})

MISPLACED_AI_ENV_KEYS: frozenset[str] = AI_SERVICE_RUNTIME_ENV_KEYS | DEPRECATED_OLLAMA_PLUGIN_ENV_KEYS


def normalize_env_key(key: str) -> str:
    return (key or "").strip().upper()


def is_misplaced_ai_env_key(key: str) -> bool:
    return normalize_env_key(key) in MISPLACED_AI_ENV_KEYS
