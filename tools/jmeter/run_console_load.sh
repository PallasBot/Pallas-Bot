#!/usr/bin/env bash
# 控制台只读 API JMeter 压测
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PROP_FILE="${JMETER_PROP_FILE:-$ROOT/tools/jmeter/local.properties}"
if [[ -f "$PROP_FILE" ]]; then
# shellcheck disable=SC1090
  source "$PROP_FILE"
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8088}"
THREADS="${THREADS:-20}"
RAMP_SEC="${RAMP_SEC:-5}"
DURATION_SEC="${DURATION_SEC:-60}"
OUT_DIR="${OUT_DIR:-$ROOT/data/bot/jmeter}"
mkdir -p "$OUT_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
JTL="$OUT_DIR/console_read_${STAMP}.jtl"
LOG="$OUT_DIR/jmeter_${STAMP}.log"

if [[ -z "${PALLAS_TOKEN:-}" ]]; then
  if [[ "${PALLAS_BENCH_DEV_TOKEN:-}" == "1" ]]; then
  PALLAS_TOKEN="$(cd "$ROOT" && uv run python -c "from src.console.webui.console_login import mint_session_token; print(mint_session_token())")"
  export PALLAS_TOKEN
  elif [[ -z "${PALLAS_CONSOLE_PASSWORD:-}" ]]; then
    echo "请设置 PALLAS_TOKEN、PALLAS_CONSOLE_PASSWORD，或本地压测 PALLAS_BENCH_DEV_TOKEN=1" >&2
    exit 1
  else
  PALLAS_TOKEN="$(python3 - <<PY
import json, urllib.request
req = urllib.request.Request(
    "http://${HOST}:${PORT}/pallas/api/auth/login",
    data=json.dumps({"password": """${PALLAS_CONSOLE_PASSWORD}"""}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=15) as resp:
    body = json.load(resp)
print(body["data"]["token"])
PY
)"
  export PALLAS_TOKEN
  fi
fi

JMETER_BIN="${JMETER_BIN:-}"
if [[ -z "$JMETER_BIN" && -x /tmp/apache-jmeter-5.6.3/bin/jmeter ]]; then
  JMETER_BIN="/tmp/apache-jmeter-5.6.3/bin/jmeter"
fi
if [[ -z "$JMETER_BIN" ]]; then
  JMETER_BIN="$(command -v jmeter || true)"
fi
if [[ -n "$JMETER_BIN" ]] && ! "$JMETER_BIN" -v 2>&1 | grep -qE 'The Apache Software Foundation.*[5-9]\.'; then
  JMETER_BIN=""
fi
if [[ -z "$JMETER_BIN" ]] && command -v docker >/dev/null 2>&1 && docker image inspect justb4/jmeter >/dev/null 2>&1; then
  USE_DOCKER_JMETER=1
fi
if [[ -z "$JMETER_BIN" && "${USE_DOCKER_JMETER:-}" != "1" ]]; then
  echo "未找到 jmeter，请安装 apt-get install jmeter、解压 5.6 到 /tmp/apache-jmeter-5.6.3，或 docker pull justb4/jmeter" >&2
  exit 1
fi

echo "JMeter -> http://${HOST}:${PORT} threads=${THREADS} duration=${DURATION_SEC}s"
echo "结果: ${JTL}"

export JVM_ARGS="${JVM_ARGS:--Dxstream.security.allow=* -Dxstream.security.allowTypes=*}"
export JAVA_OPTS="${JAVA_OPTS:-$JVM_ARGS}"

run_jmeter_native() {
  if [[ -n "$JMETER_BIN" ]]; then
    "$JMETER_BIN" -n \
      -t "$ROOT/tools/jmeter/console_read_load.jmx" \
      -l "$JTL" -j "$LOG" \
      -JHOST="$HOST" -JPORT="$PORT" \
      -JTHREADS="$THREADS" -JRAMP_SEC="$RAMP_SEC" -JDURATION_SEC="$DURATION_SEC" \
      -JPALLAS_TOKEN="$PALLAS_TOKEN" 2>>"$LOG"
    return $?
  fi
  java -Dxstream.security.allow='*' -Djmeter.home=/usr/share/jmeter \
    -jar /usr/share/jmeter/bin/ApacheJMeter.jar -n \
    -t "$ROOT/tools/jmeter/console_read_load.jmx" \
    -l "$JTL" -j "$LOG" \
    -JHOST="$HOST" -JPORT="$PORT" \
    -JTHREADS="$THREADS" -JRAMP_SEC="$RAMP_SEC" -JDURATION_SEC="$DURATION_SEC" \
    -JPALLAS_TOKEN="$PALLAS_TOKEN" 2>>"$LOG"
}

run_jmeter_docker() {
  docker run --rm --network host \
    -v "$ROOT:/work" -w /work justb4/jmeter -n \
    -t /work/tools/jmeter/console_read_load.jmx \
    -l "/work/${JTL#$ROOT/}" -j "/work/${LOG#$ROOT/}" \
    -JHOST="$HOST" -JPORT="$PORT" \
    -JTHREADS="$THREADS" -JRAMP_SEC="$RAMP_SEC" -JDURATION_SEC="$DURATION_SEC" \
    -JPALLAS_TOKEN="$PALLAS_TOKEN" 2>>"$LOG"
}

JMETER_OK=0
if [[ "${FORCE_HTTP_LOAD:-}" != "1" ]]; then
  if [[ "${USE_DOCKER_JMETER:-}" == "1" ]]; then
    run_jmeter_docker && [[ -s "$JTL" ]] && JMETER_OK=1
  elif run_jmeter_native && [[ -s "$JTL" ]]; then
    JMETER_OK=1
  else
    echo "JMeter 无法加载 JMX 或未生成 JTL，改用 httpx 并发探针" >&2
  fi
fi

if [[ "$JMETER_OK" != "1" ]]; then
  uv run python "$ROOT/tools/jmeter/http_console_load.py" \
    --host "$HOST" \
    --port "$PORT" \
    --token "$PALLAS_TOKEN" \
    --concurrency "$THREADS" \
    --duration-sec "$DURATION_SEC" \
    --out-dir "$OUT_DIR"
  exit $?
fi

python3 - <<'PY' "$JTL" "$OUT_DIR/summary_${STAMP}.txt"
import sys
from collections import defaultdict
path = sys.argv[1]
out = sys.argv[2]
by = defaultdict(list)
with open(path, encoding="utf-8", errors="replace") as f:
    header = f.readline().strip().split(",")
    idx = {k: i for i, k in enumerate(header)}
    for line in f:
        parts = line.strip().split(",")
        if len(parts) < len(header):
            continue
        label = parts[idx["label"]]
        if not label.startswith("GET "):
            continue
        elapsed = int(parts[idx["elapsed"]])
        ok = parts[idx["success"]] == "true"
        by[label].append((elapsed, ok))
lines = ["# JMeter 摘要", ""]
for label in sorted(by):
    rows = by[label]
    ms = [e for e, _ in rows]
    ok_n = sum(1 for _, o in rows if o)
    ms.sort()
    p95 = ms[int(len(ms) * 0.95) - 1] if ms else 0
    lines.append(
        f"{label}: samples={len(rows)} ok={ok_n} avg_ms={sum(ms)/len(ms):.1f} p95_ms={p95}"
    )
text = "\n".join(lines) + "\n"
print(text)
open(out, "w", encoding="utf-8").write(text)
PY

echo "摘要: $OUT_DIR/summary_${STAMP}.txt"
