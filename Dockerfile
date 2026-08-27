# 基础镜像默认 Docker Hub；国内/弱网拉 registry-1.docker.io 失败时：
#   docker build --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim -t pallasbot:local .
#（镜像站域名以当时可用为准；部署说明见 docs/deploy/docker.md）
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

WORKDIR /app

# CI 传入发版 tag 或 git describe，运行时 /health 的 pallas_bot 优先读此环境变量
ARG PALLAS_BOT_VERSION=
ENV PALLAS_BOT_VERSION=${PALLAS_BOT_VERSION}
# CI 传入完整 commit，供无 Git 的容器校验 WebUI Release 兼容性
ARG PALLAS_BOT_COMMIT=
ENV PALLAS_BOT_COMMIT=${PALLAS_BOT_COMMIT}

# 默认只使用 Docker CLI 连接显式挂载的宿主机 daemon；不在容器内启动 dockerd
ARG INSTALL_DOCKER_CLI=1
# 可选 Python 包索引；留空时使用 pip / uv 默认索引
ARG UV_DEFAULT_INDEX=

# 合并安装依赖，清理缓存，减少镜像层数
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    if [ "$INSTALL_DOCKER_CLI" = "1" ]; then \
        apt-get install -y --no-install-recommends docker.io; \
    fi && \
    if [ -n "$UV_DEFAULT_INDEX" ]; then \
        pip install --index-url "$UV_DEFAULT_INDEX" --upgrade pip && \
        pip install --index-url "$UV_DEFAULT_INDEX" uv; \
    else \
        pip install --upgrade pip && \
        pip install uv; \
    fi && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml LICENSE ./
# .dockerignore 排除了 *.md；给 hatchling 提供最小 README 以满足 pyproject readme=
RUN printf '%s\n' '# Pallas-Bot' > README.md

# 默认 extras：perf=jieba-next；pg 为空壳（兼容旧构建参数，PG 驱动已在主依赖）
# 官方扩展不进镜像 extras，运行时用插件商店或 `pallas ext install`
# 分片 Redis 等见 deploy/README.md；构建排除见 .dockerignore；编排见 docs/deploy/docker.md
ARG PALLAS_UV_EXTRAS=perf,pg
RUN if [ -n "$UV_DEFAULT_INDEX" ]; then \
        uv pip install --system --default-index "$UV_DEFAULT_INDEX" ".[${PALLAS_UV_EXTRAS}]" --no-cache-dir; \
    else \
        uv pip install --system ".[${PALLAS_UV_EXTRAS}]" --no-cache-dir; \
    fi && \
    apt-get purge -y build-essential && \
    apt-get autoremove -y && \
    rm -rf /root/.cache/pip

COPY . .

# 与 compose 的 APP_MODULE（如 bot:app）配合；本地开发入口为 `uv run pallas`
CMD ["nb", "run"]
