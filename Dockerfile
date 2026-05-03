# 基础镜像默认 Docker Hub；国内/弱网拉 registry-1.docker.io 失败时：
#   docker build --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim -t pallasbot:local .
#（镜像站域名以当时可用为准，见 docs/DockerDeployment.md）
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

WORKDIR /app

# 合并安装依赖，清理缓存，减少镜像层数
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    pip install --upgrade pip && \
    pip install uv && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./

# perf：jieba-next；pg：PostgreSQL 后端
RUN uv pip install --system ".[perf,pg]" --no-cache-dir && \
    apt-get purge -y build-essential && \
    apt-get autoremove -y && \
    rm -rf /root/.cache/pip

COPY . .

CMD ["nb", "run"]
