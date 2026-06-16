# 基础镜像默认 Docker Hub；国内/弱网拉 registry-1.docker.io 失败时：
#   docker build --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim -t pallasbot:local .
#（镜像站域名以当时可用为准，见 docs/DockerDeployment.md）
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

WORKDIR /app

# CI 传入发版 tag 或 git describe，运行时 /health 的 pallas_bot 优先读此环境变量
ARG PALLAS_BOT_VERSION=
ENV PALLAS_BOT_VERSION=${PALLAS_BOT_VERSION}

# 合并安装依赖，清理缓存，减少镜像层数
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    pip install --upgrade pip && \
    pip install uv && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./

# perf：jieba-next；pg：PostgreSQL 后端
# deploy-shard：见 deploy/README.md
# 4.0 官方扩展：plugins-duel / plugins-game / deploy-full / deploy-all（见 docs/DockerDeployment.md）
# 构建上下文排除见 .dockerignore；extras 对照见 docs/DockerDeployment.md
ARG PALLAS_UV_EXTRAS=perf,pg
RUN uv pip install --system ".[${PALLAS_UV_EXTRAS}]" --no-cache-dir && \
    apt-get purge -y build-essential && \
    apt-get autoremove -y && \
    rm -rf /root/.cache/pip

COPY . .

CMD ["nb", "run"]
