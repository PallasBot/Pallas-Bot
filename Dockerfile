# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM python:3.12-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y ffmpeg build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./

RUN pip install --upgrade pip && \
    pip install uv && \
    uv pip install --system ".[perf]"

ADD https://github.com/ufoscout/docker-compose-wait/releases/download/2.12.1/wait /app/wait

RUN chmod +x /app/wait

RUN echo "./wait" >> /app/prestart.sh

COPY . .

CMD ["nb", "run"]
