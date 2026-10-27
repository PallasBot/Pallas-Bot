ARG UV_IMAGE=ghcr.io/astral-sh/uv:latest
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${UV_IMAGE} AS uv
FROM ${PYTHON_IMAGE}

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_CONCURRENT_DOWNLOADS=4 \
    UV_CONCURRENT_INSTALLS=2 \
    UV_CONCURRENT_BUILDS=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp
COPY . /app
RUN uv sync --frozen --no-dev --no-editable --no-cache \
    && mkdir -p /app/data /app/resource \
    && chown 10001:10001 /app/data /app/resource
USER 10001:10001
EXPOSE 8765
ENTRYPOINT ["/app/.venv/bin/python", "-m", "pallas.console.cli.main"]
CMD ["mcp", "serve", "--host", "0.0.0.0", "--allow-remote", "--allowed-host", "127.0.0.1:8765"]
