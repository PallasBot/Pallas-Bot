@echo off
REM Windows：PostgreSQL 逻辑备份
cd /d "%~dp0..\.."
where uv >nul 2>&1
if %ERRORLEVEL%==0 (
  uv run python tools/scripts/backup_pg.py %*
) else (
  python tools/scripts/backup_pg.py %*
)
