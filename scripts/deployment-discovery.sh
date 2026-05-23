#!/usr/bin/env bash
# NautiCAI — deployment discovery (Linux VM / Jetson / OCI)
#   chmod +x scripts/deployment-discovery.sh
#   ./scripts/deployment-discovery.sh
# Optional: OUT_FILE=/tmp/report.txt REPO_ROOT=/opt/nauticai/app ./scripts/deployment-discovery.sh

set -u

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
OUT_FILE="${OUT_FILE:-$REPO_ROOT/deployment-discovery-report.txt}"

section() { printf '\n========== %s ==========\n\n' "$1"; }

{
  echo "NautiCAI deployment discovery report"
  echo "Generated: $(date -Iseconds 2>/dev/null || date)"
  echo "Host: $(hostname -f 2>/dev/null || hostname)"
  echo "User: $(whoami)"
  echo "Repo: $REPO_ROOT"

  section "Operating system"
  if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo "ID=$ID VERSION=$VERSION_ID PRETTY=$PRETTY_NAME"
  else
    uname -a
  fi
  echo "Kernel=$(uname -r)"
  echo "Arch=$(uname -m)"

  section "CPU and memory"
  if command -v lscpu >/dev/null 2>&1; then
    lscpu | grep -E 'Model name|CPU\(s\)|Thread|Architecture' || true
  fi
  if [ -r /proc/meminfo ]; then
    awk '/MemTotal/ {printf "RAM_GB=%.2f\n", $2/1024/1024}' /proc/meminfo
  fi

  section "Disk space"
  df -hT 2>/dev/null | head -20 || df -h
  for p in /opt/nauticai /opt/nauticai/data "$REPO_ROOT/Models" "$REPO_ROOT/backend/storage"; do
  if [ -d "$p" ]; then
    du -sh "$p" 2>/dev/null | awk -v path="$p" '{print "du " path ": " $1}'
  fi
  done
  if [ -d "$REPO_ROOT/Models" ]; then
    echo "Models_folder_MB=$(du -sm "$REPO_ROOT/Models" 2>/dev/null | awk '{print $1}')"
  else
    echo "Models_folder=MISSING (need ~172MB weights)"
  fi

  section "GPU (NVIDIA / Jetson)"
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv 2>/dev/null || nvidia-smi -L
  else
    echo "nvidia-smi=not found"
  fi
  if [ -r /etc/nv_tegra_release ]; then
    echo "--- Jetson ---"
    cat /etc/nv_tegra_release
    command -v jetson_release >/dev/null 2>&1 && jetson_release 2>/dev/null || true
    command -v nvpmodel >/dev/null 2>&1 && nvpmodel -q 2>/dev/null || true
  fi
  dpkg -l 2>/dev/null | grep -E 'nvidia-l4t-core|tensorrt|cuda-toolkit' | head -5 || true

  section "Toolchain"
  for cmd in git python3 python node npm docker docker-compose; do
    if command -v "$cmd" >/dev/null 2>&1; then
      echo -n "$cmd: "
      "$cmd" --version 2>&1 | head -1
    else
      echo "$cmd: not installed"
    fi
  done

  section "Docker"
  if command -v docker >/dev/null 2>&1; then
    docker info 2>/dev/null | grep -E 'Server Version|Operating System|Architecture|CPUs|Total Memory|Docker Root Dir' || docker info 2>&1 | head -15
    docker compose version 2>/dev/null || true
    docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true
  else
    echo "Docker not available"
  fi

  section "Firewall / listening ports (sample)"
  if command -v ss >/dev/null 2>&1; then
    ss -tlnp 2>/dev/null | grep -E ':22|:80|:443|:8000|:5432' || ss -tlnp | head -15
  elif command -v netstat >/dev/null 2>&1; then
    netstat -tlnp 2>/dev/null | head -15
  fi

  section "Local API probe"
  for url in http://127.0.0.1:8000/api/health http://127.0.0.1:8000/api/system; do
    if command -v curl >/dev/null 2>&1; then
      if out=$(curl -sf --max-time 3 "$url" 2>&1); then
        echo "$url OK: $out"
      else
        echo "$url not reachable"
      fi
    fi
  done

  section "Network"
  if command -v curl >/dev/null 2>&1; then
    ip=$(curl -sf --max-time 5 https://api.ipify.org?format=json 2>/dev/null | grep -oE '[0-9.]+' | head -1)
    echo "Public_IP=${ip:-unknown}"
  fi

  section "YOUR ANSWERS (edit file or paste in chat)"
  cat <<'EOF'
DEPLOY_TARGET=           # oracle-cloud | jetson | other-linux-vm
USERS_CONCURRENT=
NEED_GPU=                # yes | no
DATABASE_CHOICE=         # supabase | oci-postgres | docker local-db
DOMAIN_OR_IP=
HTTPS_REQUIRED=
FRONTEND_HOSTING=
MODELS_READY=
AUTH_USERS=
STORAGE_GB_PER_MONTH=
BUDGET_NOTES=
EOF

} >"$OUT_FILE"

chmod 644 "$OUT_FILE" 2>/dev/null || true
echo ""
echo "Report written to: $OUT_FILE"
echo "Fill in YOUR ANSWERS and share the file."
