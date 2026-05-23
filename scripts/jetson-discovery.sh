#!/usr/bin/env bash
# NautiCAI — full Jetson discovery for deployment planning.
#
# Run ON THE JETSON (SSH or local terminal), from anywhere:
#   chmod +x scripts/jetson-discovery.sh
#   ./scripts/jetson-discovery.sh
#
# Or without cloning first (paste on Jetson — creates report in $HOME):
#   curl -fsSL https://raw.githubusercontent.com/NautiCAI-PTE-LTD/diving_company_project/main/scripts/jetson-discovery.sh -o /tmp/jetson-discovery.sh \
#     && bash /tmp/jetson-discovery.sh
#
# Share: jetson-discovery-report.txt

set -u

REPO_ROOT="${REPO_ROOT:-}"
if [ -z "$REPO_ROOT" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || SCRIPT_DIR=""
  if [ -n "$SCRIPT_DIR" ] && [ -d "$SCRIPT_DIR/../backend" ]; then
    REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
  elif [ -d "$HOME/diving_company_project/backend" ]; then
    REPO_ROOT="$HOME/diving_company_project"
  elif [ -d "/opt/nauticai/app/backend" ]; then
    REPO_ROOT="/opt/nauticai/app"
  else
    REPO_ROOT="${HOME:-/tmp}"
  fi
fi

OUT_FILE="${OUT_FILE:-$REPO_ROOT/jetson-discovery-report.txt}"
if [ ! -w "$(dirname "$OUT_FILE")" ] 2>/dev/null; then
  OUT_FILE="${HOME}/jetson-discovery-report.txt"
fi

section() { printf '\n========== %s ==========\n\n' "$1"; }
run() { printf '%s\n' "$*"; eval "$@" 2>/dev/null || printf '(failed: %s)\n' "$*"; }

{
  echo "NautiCAI Jetson discovery report"
  echo "Generated: $(date -Iseconds 2>/dev/null || date)"
  echo "Hostname: $(hostname -f 2>/dev/null || hostname)"
  echo "User: $(whoami)"
  echo "Repo (detected): $REPO_ROOT"
  echo "Report file: $OUT_FILE"

  section "1. Board and JetPack (L4T)"
  if [ -r /etc/nv_tegra_release ]; then
    cat /etc/nv_tegra_release
  else
    echo "NOT a Tegra device? /etc/nv_tegra_release missing"
  fi
  if [ -r /proc/device-tree/model ]; then
    echo -n "Device tree model: "
    tr -d '\0' < /proc/device-tree/model
    echo
  fi
  if command -v jetson_release >/dev/null 2>&1; then
    jetson_release 2>/dev/null || true
  else
    echo "jetson_release: not installed (optional: sudo pip3 install jetson-stats && sudo jtop once)"
  fi
  if [ -r /etc/nvpmodel.conf ]; then
    echo "nvpmodel.conf: present"
  fi
  if command -v nvpmodel >/dev/null 2>&1; then
    echo "--- nvpmodel -q ---"
    nvpmodel -q 2>&1 || true
  fi
  if command -v jetson_clocks >/dev/null 2>&1; then
    echo "jetson_clocks: available"
  else
    echo "jetson_clocks: MISSING (upgrade JetPack 6.x recommended)"
  fi

  section "2. CPU, RAM, swap, thermals"
  if command -v lscpu >/dev/null 2>&1; then
    lscpu | grep -E 'Model name|Architecture|CPU\(s\)|Thread|MHz' || lscpu | head -12
  fi
  free -h 2>/dev/null || true
  if [ -r /proc/meminfo ]; then
    awk '/MemTotal|MemAvailable|SwapTotal|SwapFree/ {print}' /proc/meminfo
  fi
  if command -v tegrastats >/dev/null 2>&1; then
    echo "--- tegrastats (2s sample) ---"
    timeout 2 tegrastats --interval 500 2>/dev/null | tail -3 || true
  fi

  section "3. Disk space (need ~2 GB repo + ~500 MB models + engines)"
  df -hT / /home "$REPO_ROOT" 2>/dev/null | sort -u || df -h
  for p in "$REPO_ROOT" "$REPO_ROOT/Models" "$REPO_ROOT/backend/storage" "$HOME"; do
    [ -d "$p" ] && du -sh "$p" 2>/dev/null | awk -v p="$p" '{print "du " p ": " $1}'
  done

  section "4. NVIDIA GPU / CUDA / TensorRT (JetPack packages)"
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi -L 2>&1 || true
    nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv 2>&1 || true
  else
    echo "nvidia-smi: not on PATH (normal on some Orin Nano images)"
  fi
  ls -la /dev/nvidia* /dev/nvhost-* 2>/dev/null | head -8 || echo "No /dev/nvidia* nodes"
  echo "--- dpkg: JetPack ML stack ---"
  dpkg -l 2>/dev/null | grep -E 'nvidia-l4t-core|nvidia-jetpack|tensorrt|libcudnn|cuda-toolkit|libnvinfer' | awk '{print $2, $3}' | head -25 || true
  echo "--- LD_LIBRARY_PATH ---"
  echo "${LD_LIBRARY_PATH:-<empty>}"

  section "5. Python and project venv"
  echo "python3: $(command -v python3 2>/dev/null) $(python3 --version 2>&1)"
  VENV="$REPO_ROOT/.venv"
  if [ -f "$VENV/bin/activate" ]; then
    echo "venv: $VENV (exists)"
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
    echo "venv python: $(which python) $(python -V 2>&1)"
    python - <<'PY' 2>&1 || true
import sys
checks = []
def try_import(name, attr=None):
    try:
        m = __import__(name)
        v = getattr(m, "__version__", None) or getattr(m, attr or "", None)
        checks.append(f"  OK  {name}: {v}")
    except Exception as e:
        checks.append(f"  FAIL {name}: {e}")
try_import("torch")
try:
    import torch
    checks.append(f"  OK  torch.cuda.is_available(): {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        checks.append(f"  OK  torch.cuda.get_device_name(0): {torch.cuda.get_device_name(0)}")
        free, total = torch.cuda.mem_get_info(0)
        checks.append(f"  OK  GPU mem free/total GB: {free/1e9:.2f} / {total/1e9:.2f}")
except Exception as e:
    checks.append(f"  FAIL torch cuda: {e}")
try_import("torchvision")
try_import("tensorrt")
try_import("onnxruntime")
try_import("pycuda")
try_import("cv2", "opencv_version")
try_import("easyocr")
print("\n".join(checks))
PY
  else
    echo "venv: NOT FOUND at $VENV"
    echo "  → run: ./deploy/jetson/install.sh (after setting TORCH_WHEEL=...)"
  fi

  section "6. Model weights and TensorRT artefacts (required for deploy)"
  MODELS="$REPO_ROOT/Models"
  if [ -d "$MODELS" ]; then
    echo "Models directory: $MODELS"
    ls -lh "$MODELS" 2>/dev/null | awk 'NR==1 || /\.(pth|keras|pt|onnx|engine)$/ {print}'
    echo "--- checklist ---"
    for f in \
      Ship_classification_v2.pth \
      Ship_classification_v2.onnx \
      Ship_classification_v2.engine \
      species_classifier_bundle.pt \
      species_classifier_bundle.onnx \
      species_classifier_bundle.engine \
      Before_and_after_v2.keras \
      Before_and_after_v2.onnx \
      Before_and_after_v2.engine
    do
      if [ -f "$MODELS/$f" ]; then
        echo "  [YES] $f ($(du -h "$MODELS/$f" | cut -f1))"
      else
        echo "  [NO]  $f"
      fi
    done
    echo "Models total: $(du -sh "$MODELS" 2>/dev/null | cut -f1)"
  else
    echo "Models/: MISSING — copy Models_for_Jetson.zip from dev PC"
  fi

  section "7. Backend config (secrets redacted)"
  ENV_FILE="$REPO_ROOT/backend/.env"
  if [ -f "$ENV_FILE" ]; then
    echo "backend/.env: exists"
    grep -E '^[A-Z_]+=' "$ENV_FILE" 2>/dev/null | sed -E \
      's/(DATABASE_URL=postgresql:\/\/)[^@]+@/\1***@/; s/(JWT_SECRET=).+/\1***REDACTED***/; s/(PASSWORD=).+/\1***/' || true
  else
    echo "backend/.env: MISSING"
  fi
  if [ -n "${DATABASE_URL:-}" ]; then echo "DATABASE_URL env: set (shell)"; else echo "DATABASE_URL env: not set"; fi

  section "8. Services: backend, nginx, systemd"
  if curl -sf --max-time 3 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "uvicorn :8000: UP"
    curl -sf http://127.0.0.1:8000/api/system 2>/dev/null | python3 -m json.tool 2>/dev/null || \
      curl -sf http://127.0.0.1:8000/api/system 2>/dev/null || true
  else
    echo "uvicorn :8000: DOWN (not started yet)"
  fi
  if command -v systemctl >/dev/null 2>&1; then
    systemctl is-active nauticai 2>/dev/null && echo "systemd nauticai: $(systemctl is-active nauticai)" || echo "systemd nauticai: not installed or inactive"
    systemctl is-active nginx 2>/dev/null && echo "systemd nginx: $(systemctl is-active nginx)" || echo "systemd nginx: inactive"
  fi
  if command -v nginx >/dev/null 2>&1; then
    nginx -v 2>&1 || true
    [ -f /etc/nginx/sites-enabled/nauticai ] && echo "nginx site nauticai: enabled" || echo "nginx site nauticai: not configured"
  fi
  CODE_ROOT="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1/ 2>/dev/null || echo 000)"
  CODE_API="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1/api/health 2>/dev/null || echo 000)"
  echo "HTTP GET / → $CODE_ROOT  (expect 200 after frontend build + nginx)"
  echo "HTTP GET /api/health → $CODE_API  (expect 200 when proxied)"
  [ -d "$REPO_ROOT/frontend/dist" ] && echo "frontend/dist: YES ($(du -sh "$REPO_ROOT/frontend/dist" | cut -f1))" || echo "frontend/dist: NO — run frontend/build-jetson.sh"

  section "9. Node.js (frontend build)"
  if command -v node >/dev/null 2>&1; then
    echo "node: $(node -v) path=$(command -v node)"
    echo "npm: $(npm -v 2>/dev/null)"
  else
    echo "node: NOT INSTALLED (need Node >= 18, recommend 20.x)"
  fi

  section "10. Network (how divers reach the Jetson)"
  echo "--- IP addresses ---"
  hostname -I 2>/dev/null || ip -4 addr show 2>/dev/null | grep -oP 'inet \K[\d.]+' || true
  echo "--- listening ports (22 SSH, 80 web, 8000 API) ---"
  if command -v ss >/dev/null 2>&1; then
    ss -tlnp 2>/dev/null | grep -E ':22 |:80 |:443 |:8000 ' || ss -tlnp | head -12
  fi
  if command -v curl >/dev/null 2>&1; then
  PUB=$(curl -sf --max-time 5 https://api.ipify.org 2>/dev/null || echo unknown)
  echo "Outbound public IP (if routed): $PUB"
  fi
  echo "--- Wi-Fi / Ethernet (link state) ---"
  ip link show 2>/dev/null | grep -E '^[0-9]+:|state UP' | head -20 || true

  section "11. Git repo state"
  if [ -d "$REPO_ROOT/.git" ]; then
    git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null && git -C "$REPO_ROOT" status -sb 2>/dev/null | head -5
  else
    echo "Not a git clone at $REPO_ROOT"
  fi

  section "12. Deploy readiness summary (auto)"
  READY=0
  BLOCKERS=""
  [ -r /etc/nv_tegra_release ] || BLOCKERS="${BLOCKERS}\n- Not detected as Jetson (no nv_tegra_release)"
  command -v jetson_clocks >/dev/null 2>&1 || BLOCKERS="${BLOCKERS}\n- jetson_clocks missing — JetPack too old?"
  awk '/MemTotal/ {if ($2<7000000) exit 1}' /proc/meminfo 2>/dev/null || BLOCKERS="${BLOCKERS}\n- RAM < ~7 GB (Orin Nano 8GB expected)"
  AVAIL_KB=$(df -k / 2>/dev/null | awk 'NR==2 {print $4}')
  [ -n "$AVAIL_KB" ] && [ "$AVAIL_KB" -gt 5000000 ] 2>/dev/null || BLOCKERS="${BLOCKERS}\n- Root disk < ~5 GB free"
  [ -f "$REPO_ROOT/Models/Ship_classification_v2.pth" ] || BLOCKERS="${BLOCKERS}\n- Missing Models/*.pth (weights)"
  [ -f "$REPO_ROOT/.venv/bin/python" ] || BLOCKERS="${BLOCKERS}\n- Missing .venv (run deploy/jetson/install.sh)"
  if [ -z "$BLOCKERS" ]; then
    echo "Core hardware: OK for Jetson deploy"
    READY=1
  else
    echo "Blockers found:"
    printf '%b\n' "$BLOCKERS"
  fi
  echo ""
  echo "After install, run: bash deploy/jetson/health_check.sh"

  section "13. YOUR ANSWERS (fill in and send back)"
  cat <<'EOF'
JETSON_MODEL=             # Orin Nano 8GB | Orin NX | Xavier NX | other
JETPACK_VERSION=          # e.g. 6.0 / 6.1 (from jetson_release or flash notes)
POWER_MODE=               # MAXN (0) | 15W | battery
REPO_PATH=                # e.g. /home/ubuntu/diving_company_project
INTERNET_ON_VESSEL=       # Wi-Fi | Ethernet | offline-only | hotspot from phone
WHO_ACCESSES_UI=          # diver tablet on LAN | remote VPN | both
DATABASE=                 # Supabase URL ready? | SQLite ok for trial? | ship has no cloud
TORCH_WHEEL_DOWNLOADED=   # yes path=... | no — need link for your JetPack
ONNX_FILES_ON_JETSON=     # yes | no — will copy from Windows PC
TRT_ENGINES_BUILT=        # yes | no — will run build_trt.py on Jetson
TEAMVIEWER_OR_SSH=        # how you connect to configure
VESSEL_LOCATION=          # country / port (for latency & support)
EOF

} >"$OUT_FILE" 2>&1

chmod 644 "$OUT_FILE" 2>/dev/null || true
echo ""
echo "=============================================="
echo " Jetson report saved to:"
echo "   $OUT_FILE"
echo ""
echo " Next:"
echo "   1. Edit section 13 (YOUR ANSWERS) in that file"
echo "   2. Copy file to your PC:  scp user@jetson:$OUT_FILE ."
echo "   3. Share the file (or paste contents) for deploy help"
echo " After deploy:  bash deploy/jetson/health_check.sh"
echo "=============================================="
