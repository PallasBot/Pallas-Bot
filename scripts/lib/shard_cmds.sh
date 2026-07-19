# Pallas-Bot 分片命令实现
[[ -n "${_PALLAS_SHARD_CMDS_LOADED:-}" ]] && return 0
_PALLAS_SHARD_CMDS_LOADED=1

cmd_start_hub_only() {
  require_coord_redis_for_shard_start || return 1

  local hub_url="http://127.0.0.1:${HUB_PORT}"
  local worker_counts
  worker_counts="$(count_running_production_workers)"
  local worker_running="${worker_counts%% *}"
  local worker_total="${worker_counts##* }"

  print_title "Pallas-Bot 分片模式 · 启动 hub（不启 worker）"
  echo "  hub 端口   ${HUB_PORT}"
  if [[ "${worker_total}" -gt 0 ]]; then
    echo "  worker     保持现状（${worker_running}/${worker_total} 运行，本次不启动 worker）"
  else
    echo "  worker     本次不启动（需单独 start 或 restart --workers-only）"
  fi
  echo "  $(shard_coord_backend_hint)"
  echo ""
  echo "  正在启动 hub…"

  start_hub_process

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo ""
    echo "  （预览模式，未实际启动进程）"
    return 0
  fi

  echo ""
  echo "  正在确认 hub 是否就绪…"
  local hub_ok=0
  if is_running "${PID_HUB}"; then
    hub_ok=1
  else
    echo "  · 控制台 hub 未在运行，请查看日志: ${LOG_DIR}/hub.log"
  fi

  print_title "hub 启动完成"
  echo "  汇总       hub $([[ "${hub_ok}" -eq 1 ]] && echo 运行中 || echo 未就绪)"
  if [[ "${hub_ok}" -eq 1 ]]; then
    echo "  WebUI      ${hub_url}/pallas/"
    echo "  协议端     ${hub_url}/pallas/protocol/"
  fi
  echo ""
  echo "  常用命令"
  echo "    status                  查看运行状态"
  echo "    start --workers-only    仅拉起缺失 worker"
  echo "    restart --workers-only  全量重启 worker"
  echo "    restart --hub-only       仅重启 hub"
  if [[ "${hub_ok}" -eq 0 ]]; then
    return 1
  fi
}

cmd_start_workers_only() {
  require_coord_redis_for_shard_start || return 1

  local workers="${WORKER_COUNT_OVERRIDE:-$(calc_worker_count)}"
  local running_before worker_mode
  running_before="$(count_running_production_worker_ids)"
  worker_mode="$(resolve_production_worker_start_mode "${workers}")"
  if [[ "${SCALE_ONLY}" -eq 0 && "${worker_mode}" == "scale" ]]; then
    SCALE_ONLY=1
  fi

  if [[ "${SCALE_ONLY}" -eq 0 && "${worker_mode}" == "skip" ]]; then
    print_title "Pallas-Bot 分片模式 · 启动缺失 worker（保留已运行进程）"
    print_config_summary "${workers}"
    if is_running "${PID_HUB}"; then
      echo "  hub        保持运行（:${HUB_PORT}）"
    else
      echo "  hub        未运行（本次不启动 hub）"
    fi
    echo "  worker     已全部运行（${running_before}/${workers}），跳过启动与端口重分配"
    echo "  $(shard_coord_backend_hint)"
    print_title "worker 无需启动"
    echo "  汇总       worker ${running_before}/${workers} 运行 · $(shard_coord_backend_hint)"
    echo "  提示       需全量重启时请执行 restart --workers-only"
    return 0
  fi

  print_title "Pallas-Bot 分片模式 · 启动缺失 worker（保留已运行进程）"
  print_config_summary "${workers}"
  if is_running "${PID_HUB}"; then
    echo "  hub        保持运行（:${HUB_PORT}）"
  else
    echo "  hub        未运行（本次不启动 hub）"
  fi
  if [[ "${SCALE_ONLY}" -eq 1 ]]; then
    echo "  worker     部分运行（${running_before}/${workers}），仅启动缺失 worker"
    echo "  端口策略   扩容模式（registry 端口，不重分配、不同步协议端）"
  else
    echo "  端口策略   冷启动（评估端口并同步协议端 ws_url）"
  fi
  echo "  $(shard_coord_backend_hint)"
  echo ""

  if [[ "${SCALE_ONLY}" -eq 1 ]]; then
    workers="$(calc_worker_count)"
    echo "  正在启动缺失 worker（已在运行的分片将跳过）…"
    start_missing_production_workers "${workers}"
  else
    prepare_shard_ports "${workers}" || return 1
    workers="$(calc_worker_count)"
    echo ""
    echo "  正在启动 worker…"
    start_production_workers "${workers}"
  fi

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo ""
    echo "  （预览模式，未实际启动）"
    return 0
  fi

  echo ""
  echo "  正在确认 worker…"
  local worker_running=0 worker_fail=0
  local f
  for f in "${RUN_DIR}"/worker-*.pid; do
    [[ -e "${f}" ]] || continue
    case "$(basename "${f}" .pid)" in worker-test|worker-test2) continue ;; esac
    if is_running "${f}"; then
      worker_running=$((worker_running + 1))
    else
      worker_fail=$((worker_fail + 1))
      local wname
      wname="$(basename "${f}" .pid)"
      echo "  · ${wname} 启动后已退出，请查看: ${LOG_DIR}/${wname}.log"
    fi
  done

  print_title "worker 扩容完成"
  echo "  汇总       worker ${worker_running}/${workers} 运行 · $(shard_coord_backend_hint)"
  if [[ "${worker_fail}" -gt 0 ]]; then
    echo "  提示       部分 worker 未保持运行，请检查端口与日志"
  elif [[ "${worker_running}" -lt "${workers}" ]]; then
    echo "  提示       仍有 worker 未启动，可再次执行 start --workers-only"
  fi
}

cmd_start() {
  if [[ "${WORKERS_ONLY}" -eq 1 && "${HUB_ONLY}" -eq 1 ]]; then
    echo "  --workers-only 与 --hub-only 不能同时使用" >&2
    return 1
  fi
  if [[ "${HUB_ONLY}" -eq 1 ]]; then
    cmd_start_hub_only
    return
  fi
  if [[ "${WORKERS_ONLY}" -eq 1 ]]; then
    cmd_start_workers_only
    return
  fi
  require_coord_redis_for_shard_start || return 1

  local workers="${WORKER_COUNT_OVERRIDE:-$(calc_worker_count)}"
  local hub_url="http://127.0.0.1:${HUB_PORT}"
  local worker_mode running_before
  worker_mode="$(resolve_production_worker_start_mode "${workers}")"
  running_before="$(count_running_production_worker_ids)"

  print_title "Pallas-Bot 分片模式 · 启动"
  print_config_summary "${workers}"
  case "${worker_mode}" in
    skip)
      echo "  worker     已全部运行（${running_before}/${workers}），跳过 worker 启动与端口重分配"
      ;;
    scale)
      echo "  worker     部分运行（${running_before}/${workers}），仅启动缺失 worker"
      echo "  端口策略   扩容模式（registry 端口，不重分配、不同步协议端）"
      ;;
    cold)
      if [[ "${SKIP_OCCUPIED_PORTS}" -eq 1 ]]; then
        echo "  端口策略   自动跳过占用"
      else
        echo "  端口策略   严格 起点+分片号"
      fi
      ;;
  esac
  echo "  $(shard_coord_backend_hint)"
  echo ""

  if [[ "${worker_mode}" == "cold" ]]; then
    wait_worker_ports_released "${workers}" || true
    echo ""
    prepare_shard_ports "${workers}" || return 1
    workers="$(calc_worker_count)"
  fi
  echo ""
  echo "  正在启动进程…"

  start_hub_process

  if [[ "${DRY_RUN}" -eq 0 && "${worker_mode}" == "cold" ]]; then
    sleep 1
  fi

  case "${worker_mode}" in
    skip)
      ;;
    scale)
      workers="$(calc_worker_count)"
      start_missing_production_workers "${workers}"
      ;;
    cold)
      start_production_workers "${workers}"
      ;;
  esac

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo ""
    echo "  （预览模式，未实际启动进程）"
    return 0
  fi

  echo ""
  echo "  正在确认进程是否就绪…"
  local hub_ok=0 worker_running=0 worker_fail=0
  if is_running "${PID_HUB}"; then
    hub_ok=1
  else
    echo "  · 控制台 hub 未在运行，请查看日志: ${LOG_DIR}/hub.log"
  fi
  local f
  for f in "${RUN_DIR}"/worker-*.pid; do
    [[ -e "${f}" ]] || continue
    case "$(basename "${f}" .pid)" in worker-test|worker-test2) continue ;; esac
    if is_running "${f}"; then
      worker_running=$((worker_running + 1))
    else
      worker_fail=$((worker_fail + 1))
      local wname
      wname="$(basename "${f}" .pid)"
      echo "  · ${wname} 启动后已退出，请查看: ${LOG_DIR}/${wname}.log"
    fi
  done

  print_title "启动完成"
  echo "  汇总       hub $([[ "${hub_ok}" -eq 1 ]] && echo 运行中 || echo 未就绪) · worker ${worker_running}/${workers} 运行"
  if [[ "${hub_ok}" -eq 1 ]]; then
    echo "  WebUI      ${hub_url}/pallas/"
    echo "  协议端     ${hub_url}/pallas/protocol/"
  fi
  echo ""
  echo "  常用命令"
  echo "    status              查看运行状态与 Redis"
  echo "    restart --workers-only   仅重启 worker（保留 hub）"
  echo "    restart --hub-only       仅重启 hub（保留 worker）"
  echo "    test start          仅启测试 worker"
  echo "    tail -f ${LOG_DIR}/worker-0.log"
  if [[ "${worker_fail}" -gt 0 ]]; then
    echo ""
    echo "  部分 worker 未保持运行，多为端口占用或配置错误；修复后执行 restart。"
  elif [[ "${hub_ok}" -eq 1 ]] && [[ "${worker_running}" -eq "${workers}" ]]; then
    echo ""
    echo "  全部进程已就绪。"
  elif [[ "${worker_mode}" == "skip" && "${worker_running}" -eq "${workers}" ]]; then
    echo ""
    echo "  worker 已在运行，本次未重复启动；需全量重启请执行 restart --workers-only。"
  fi
}

cmd_stop() {
  if [[ "${WORKERS_ONLY}" -eq 1 && "${HUB_ONLY}" -eq 1 ]]; then
    echo "  --workers-only 与 --hub-only 不能同时使用" >&2
    return 1
  fi
  if [[ "${HUB_ONLY}" -eq 1 ]]; then
    local worker_counts
    worker_counts="$(count_running_production_workers)"
    local worker_running="${worker_counts%% *}"
    local worker_total="${worker_counts##* }"
    print_title "Pallas-Bot 分片模式 · 停止 hub（保留 worker）"
    if [[ "${worker_total}" -gt 0 ]]; then
      echo "  worker     保持运行（${worker_running}/${worker_total}）"
    else
      echo "  worker     未运行"
    fi
    echo ""
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      echo "  · hub  控制台：将停止（预览）"
      echo ""
      echo "  （预览模式，未实际停止进程）"
      return 0
    fi
    stop_hub_process
    echo ""
    echo "  hub 已处理完毕（生产 worker 与测试 worker-test 未停止）。"
    return 0
  fi
  if [[ "${WORKERS_ONLY}" -eq 1 ]]; then
    print_title "Pallas-Bot 分片模式 · 停止 worker（保留 hub）"
    if is_running "${PID_HUB}"; then
      echo "  hub        保持运行（端口 ${HUB_PORT}）"
    else
      echo "  hub        未运行"
    fi
    echo ""
    stop_production_workers
    echo ""
    echo "  生产 worker 已处理完毕（测试 worker-test 未停止）。"
    return 0
  fi
  print_title "Pallas-Bot 分片模式 · 停止$([[ "${FORCE_STOP}" -eq 1 ]] && echo '（强制）')"
  stop_one "worker-test" "测试 worker-test"
  stop_production_workers
  stop_hub_process
  stop_orphan_shard_processes
  echo ""
  echo "  全部分片进程已处理完毕。"
}

cmd_status() {
  local workers=0
  local running_workers=0
  local stale_workers=0
  local expected_workers
  expected_workers="$(calc_worker_count)"
  local hub_url="http://127.0.0.1:${HUB_PORT}"
  local hub_state="未运行"

  print_title "Pallas-Bot 分片模式 · 运行状态"

  echo "  配置摘要"
  print_config_summary "${expected_workers}"
  echo ""

  print_redis_status_block
  echo ""

  print_observability_status_block
  echo ""

  echo "  进程"
  if is_running "${PID_HUB}"; then
    hub_state="运行中"
    echo "    hub        ${hub_state}  :${HUB_PORT}"
    echo "               ${hub_url}/pallas/"
  else
    if [[ -f "${PID_HUB}" ]]; then
      hub_state="未运行（残留 pid）"
    fi
    echo "    hub        ${hub_state}"
  fi

  local f
  for f in "${RUN_DIR}"/worker-*.pid; do
    [[ -e "${f}" ]] || continue
    case "$(basename "${f}" .pid)" in worker-test|worker-test2) continue ;; esac
    workers=$((workers + 1))
    local name port state
    name="$(basename "${f}" .pid)"
    port=""
    if [[ "${name}" =~ worker-([0-9]+) ]]; then
      port="$(registry_port_for_shard "${BASH_REMATCH[1]}")"
    fi
    if is_running "${f}"; then
      running_workers=$((running_workers + 1))
      state="运行中"
    else
      stale_workers=$((stale_workers + 1))
      state="未运行"
    fi
    printf "    %-10s %-6s  WS:%s\n" "${name}" "${state}" "${port}"
  done
  if [[ "${workers}" -eq 0 && "${expected_workers}" -eq 0 ]]; then
    echo "    （尚无生产 worker，请先 start）"
  else
    echo "    小计       ${running_workers}/${expected_workers} 运行"
    if [[ "${running_workers}" -lt "${expected_workers}" ]]; then
      local sid=0 missing=0
      while [[ "${sid}" -lt "${expected_workers}" ]]; do
        local pf="${RUN_DIR}/worker-${sid}.pid"
        if ! is_running "${pf}"; then
          missing=$((missing + 1))
          local mport
          mport="$(registry_port_for_shard "${sid}")"
          echo "    worker-${sid}   未启动  WS:${mport}"
        fi
        sid=$((sid + 1))
      done
    fi
  fi

  echo ""
  echo "  测试 worker-test"
  if registry_test_enabled; then
    local tsid tport
    tsid="$(registry_test_shard_id)"
    tport="$(registry_test_port)"
    if is_running "${PID_WORKER_TEST}"; then
      echo "    状态       运行中  分片 ${tsid}  WS:${tport}"
    else
      echo "    状态       未运行  分片 ${tsid}  WS:${tport}（test start）"
    fi
  else
    echo "    状态       未配置（test init）"
  fi

  echo ""
  echo "  日志       ${LOG_DIR}/"

  if [[ "${stale_workers}" -gt 0 || "${running_workers}" -lt "${expected_workers}" ]]; then
    echo ""
    if [[ "${running_workers}" -lt "${expected_workers}" ]]; then
      echo "  提示：应有 ${expected_workers} 个 worker，当前仅 ${running_workers} 个在运行"
    else
      echo "  提示：${stale_workers} 个 worker 未运行"
    fi
    if is_running "${PID_HUB}"; then
      echo "    ./scripts/run_sharded_bot.sh start --workers-only"
      echo "    ./scripts/run_sharded_bot.sh restart --workers-only   # 需全量重启时"
    else
      echo "    ./scripts/run_sharded_bot.sh restart"
      echo "    ./scripts/run_sharded_bot.sh start --hub-only   # 仅启 WebUI 控制台"
    fi
  elif [[ "${running_workers}" -eq 0 ]] && ! is_running "${PID_HUB}"; then
    echo ""
    echo "  提示：当前无运行中的分片进程"
    echo "    ./scripts/run_sharded_bot.sh start"
  elif [[ "${running_workers}" -gt 0 ]] && ! is_running "${PID_HUB}"; then
    echo ""
    echo "  提示：worker 在运行但 hub 未运行（WebUI 不可用）"
    echo "    ./scripts/run_sharded_bot.sh start --hub-only"
  fi
}

cmd_restart_hub_only() {
  require_coord_redis_for_shard_start || return 1

  print_title "Pallas-Bot 分片模式 · 重启 hub（保留 worker）"
  echo "  hub 端口   ${HUB_PORT}"
  local worker_counts
  worker_counts="$(count_running_production_workers)"
  local worker_running="${worker_counts%% *}"
  local worker_total="${worker_counts##* }"
  if [[ "${worker_total}" -gt 0 ]]; then
    echo "  worker     保持运行（${worker_running}/${worker_total}）"
  else
    echo "  worker     未运行"
  fi
  echo ""

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "  · hub  控制台：将重启（预览）"
    echo ""
    echo "  （预览模式，未实际重启进程）"
    return 0
  fi

  stop_hub_process
  echo ""
  echo "  正在启动 hub…"
  start_hub_process

  echo ""
  echo "  正在确认 hub…"
  local hub_ok=0
  if is_running "${PID_HUB}"; then
    hub_ok=1
  else
    echo "  · 控制台 hub 未在运行，请查看日志: ${LOG_DIR}/hub.log"
  fi

  print_title "hub 重启完成"
  echo "  汇总       hub $([[ "${hub_ok}" -eq 1 ]] && echo 运行中 || echo 未就绪)"
  if [[ "${hub_ok}" -eq 1 ]]; then
    echo "  WebUI      http://127.0.0.1:${HUB_PORT}/pallas/"
  fi
  if [[ "${hub_ok}" -eq 0 ]]; then
    return 1
  fi
}

cmd_restart_workers_only() {
  require_coord_redis_for_shard_start || return 1

  local workers="${WORKER_COUNT_OVERRIDE:-$(calc_worker_count)}"

  print_title "Pallas-Bot 分片模式 · 重启 worker（保留 hub）"
  print_config_summary "${workers}"
  if is_running "${PID_HUB}"; then
    echo "  hub        保持运行（:${HUB_PORT}）"
  else
    echo "  hub        未运行（仅 worker；WebUI 需单独 start --hub-only）"
  fi
  echo ""

  stop_production_workers
  echo ""
  wait_worker_ports_released "${workers}" || true
  echo ""
  prepare_shard_ports "${workers}" || return 1
  workers="$(calc_worker_count)"
  echo ""
  echo "  正在启动 worker…"
  start_production_workers "${workers}"

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo ""
    echo "  （预览模式，未实际启动）"
    return 0
  fi

  echo ""
  echo "  正在确认 worker…"
  local worker_running=0 worker_fail=0
  local f
  for f in "${RUN_DIR}"/worker-*.pid; do
    [[ -e "${f}" ]] || continue
    case "$(basename "${f}" .pid)" in worker-test|worker-test2) continue ;; esac
    if is_running "${f}"; then
      worker_running=$((worker_running + 1))
    else
      worker_fail=$((worker_fail + 1))
      local wname
      wname="$(basename "${f}" .pid)"
      echo "  · ${wname} 启动后已退出，请查看: ${LOG_DIR}/${wname}.log"
    fi
  done

  print_title "worker 重启完成"
  echo "  汇总       worker ${worker_running}/${workers} 运行 · $(shard_coord_backend_hint)"
  if [[ "${worker_fail}" -gt 0 ]]; then
    echo "  提示       部分 worker 未保持运行，请检查端口与日志"
  fi
}

cmd_restart() {
  if [[ "${WORKERS_ONLY}" -eq 1 && "${HUB_ONLY}" -eq 1 ]]; then
    echo "  --workers-only 与 --hub-only 不能同时使用" >&2
    return 1
  fi
  if [[ "${HUB_ONLY}" -eq 1 ]]; then
    cmd_restart_hub_only
    return
  fi
  if [[ "${WORKERS_ONLY}" -eq 1 ]]; then
    cmd_restart_workers_only
    return
  fi
  local workers="${WORKER_COUNT_OVERRIDE:-$(calc_worker_count)}"
  cmd_stop
  echo ""
  wait_worker_ports_released "${workers}" || true
  echo ""
  cmd_start
}
