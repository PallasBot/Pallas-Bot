@echo off
REM Windows 入口：等价于 scripts/pallas / uv run pallas
cd /d "%~dp0.."
uv run python -m pallas.console.cli %*
