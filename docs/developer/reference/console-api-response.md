# 控制台 API 响应约定

实现：`pallas.console.webui.api_response`。新路由与 OpenAPI 导出路由默认采用信封格式。

## 信封格式

成功：

```json
{
  "ok": true,
  "data": { }
}
```

错误（HTTP 非 2xx）：

```json
{
  "ok": false,
  "error": "人类可读说明",
  "data": null
}
```

## 代码示例

```python
from pallas.console.webui.api_response import api_ok, api_err

@router.get("/example")
async def example():
    return api_ok({"items": []})

@router.post("/example")
async def example_fail():
    return api_err("缺少参数", status_code=400)
```

## 与遗留路由

历史路由可能直接返回裸对象或 `HTTPException(detail=...)`。重构时优先改为信封，前端 `unwrap()` 已兼容 `ok/data/error`。

## 相关

- `openspec/pallas-console-v1.json`（`uv run python tools/sync_console_openapi.py`）
- WebUI `src/api/generated/pallasConsoleOpenapi.ts` · `src/api/http.ts` · `unwrap()`
- [OpenAPI 双仓同步](../webui.md#openapi-契约)
