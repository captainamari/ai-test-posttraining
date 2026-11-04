#!/usr/bin/env bash
# ---------------------------------------------------------------
# monitor_server.sh
# 服务器/训练状态快照脚本
# 用法:
#   ./monitor_server.sh            单次打印一份状态快照
#   ./monitor_server.sh -l LOG     单次快照并追加写入 LOG 文件
#   ./monitor_server.sh -w SEC     每 SEC 秒循环打印一次（watch 模式）
# ---------------------------------------------------------------
set -euo pipefail

LOG_FILE=""
WATCH_INTERVAL=0

while getopts "l:w:" opt; do
  case "$opt" in
    l) LOG_FILE="$OPTARG" ;;
    w) WATCH_INTERVAL="$OPTARG" ;;
    *) echo "用法: $0 [-l logfile] [-w interval_sec]"; exit 1 ;;
  esac
done

divider() { printf '%s\n' "------------------------------------------------------------"; }

snapshot() {
  local ts
  ts=$(date '+%Y-%m-%d %H:%M:%S')
  echo "============================================================"
  echo "快照时间: $ts"
  divider

  # 1. 系统负载 & CPU
  echo "[CPU / 负载]"
  echo "CPU核数: $(nproc)"
  if [ -r /proc/loadavg ]; then
    echo "Load Average (1m/5m/15m): $(awk '{print $1" / "$2" / "$3}' /proc/loadavg)"
  fi
  if command -v mpstat >/dev/null 2>&1; then
    mpstat 1 1 | tail -n 2
  else
    # 用 /proc/stat 做一次简单采样算总体 CPU 使用率
    top -bn1 2>/dev/null | grep -i "Cpu(s)" || true
  fi
  divider

  # 2. 内存
  echo "[内存]"
  free -h
  divider

  # 3. GPU（若存在 nvidia-smi 则显示，否则提示无 GPU / 不可见）
  echo "[GPU]"
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw --format=csv,noheader
    echo "--- GPU 进程 ---"
    nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null || echo "(无计算进程或不支持)"
  else
    echo "未检测到 nvidia-smi，当前环境无 GPU 或 GPU 不可见（可能在无 GPU 的容器/开发机中）"
  fi
  divider

  # 4. 磁盘
  echo "[磁盘空间]"
  df -h --output=target,size,used,avail,pcent 2>/dev/null | grep -Ev 'tmpfs|overlay|shm' || df -h
  divider

  # 5. 磁盘 IO（可选，若有 iostat）
  if command -v iostat >/dev/null 2>&1; then
    echo "[磁盘 IO（1秒采样）]"
    iostat -x 1 2 2>/dev/null | tail -n +$(( $(iostat -x 1 2 2>/dev/null | grep -n '^Device' | tail -1 | cut -d: -f1) )) || true
    divider
  fi

  # 6. 训练相关进程（python/torchrun 等，按 CPU 占用排序取前5）
  echo "[训练相关进程 Top5 (按CPU)]"
  ps aux --sort=-%cpu | awk 'NR==1 || /python|torchrun|deepspeed|accelerate/' | grep -v grep | head -n 6
  divider

  # 7. 网络连接数（简单统计）
  echo "[网络]"
  if command -v ss >/dev/null 2>&1; then
    echo "TCP 连接总数: $(ss -tan | tail -n +2 | wc -l)"
  fi
  divider
}

run_once() {
  if [ -n "$LOG_FILE" ]; then
    snapshot | tee -a "$LOG_FILE"
  else
    snapshot
  fi
}

if [ "$WATCH_INTERVAL" -gt 0 ] 2>/dev/null; then
  while true; do
    run_once
    sleep "$WATCH_INTERVAL"
  done
else
  run_once
fi
