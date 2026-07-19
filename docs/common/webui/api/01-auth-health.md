# 认证与健康检查

基址：`/pallas/api`（下文路径均相对此前缀）。

## 公开 / 半公开

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| GET | `/health` | 无 | Bot 与控制台版本、NoneBot 版本 |
| POST | `/auth/login` | 无 | Body `{"password": "..."}` → 设置会话 Cookie |
| GET | `/auth/setup-status` | 无 | 返回是否仍处于默认口令 / 首次引导阶段 |

## 需 token / 会话

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/system` | CPU/内存/磁盘、运行时长等（短 TTL 缓存） |
| GET | `/bots` | 已连接 Bot 实例列表（self_id、适配器、在线状态） |

### `/health` 响应要点

```json
{
  "ok": true,
  "nonebot2": "2.x.x",
  "pallas_bot": "x.y.z",
  "console": { "version": "...", "build": "..." }
}
```

### `/system` 响应

`data` 为系统资源快照；首页轮询约 5s，服务端有约 0.8s 读缓存。

### `/auth/setup-status` 响应要点

```json
{
  "ok": true,
  "data": {
    "auth_configured": true,
    "setup_completed": false,
    "default_password_active": true,
    "requires_setup": true
  }
}
```

含义：

- `default_password_active=true`：仍在使用自动生成的默认口令
- `requires_setup=true`：前端应引导用户先改密，再继续其他配置

## 前端对应

- `fetchSystem()` → `/system`
- `http.get("/health")`（健康探测）
- 登录：`POST /auth/login`（`public.py` 表单登录走 `/pallas/login`）

实现：`api.py`（health）、`extended_api.py`（system、bots）、`public.py`（login）。
