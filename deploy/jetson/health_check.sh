#!/usr/bin/env bash
# Full stack health check for NautiCAI on Jetson (Xavier / Orin).
# Usage:  cd ~/diving_company_project && bash deploy/jetson/health_check.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "========== NautiCAI Jetson health check =========="
echo "Project: $ROOT"
echo

pass() { echo "  [OK]   $*"; }
fail() { echo "  [FAIL] $*"; FAIL=1; }
warn() { echo "  [WARN] $*"; }
FAIL=0

# --- GPU hardware ---
echo "--- GPU ---"
if command -v tegrastats >/dev/null 2>&1; then
  pass "tegrastats available (Jetson)"
else
  warn "tegrastats not found"
fi
if [ -d /dev/nvidia0 ] || [ -e /dev/nvhost-ctrl ]; then
  pass "NVIDIA device nodes present"
else
  fail "No NVIDIA device nodes — check JetPack / driver"
fi

# --- Python venv ---
echo "--- Python ---"
if [ -f "$ROOT/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
  pass "venv activated: $(which python) ($(python -V 2>&1))"
else
  fail "Missing .venv — run: python3 -m venv .venv && pip install -r backend/requirements-jetson.txt"
fi

python - <<'PY' || fail "PyTorch CUDA check failed"
import sys
try:
    import torch
except ImportError:
    sys.exit("torch not installed")
if not torch.cuda.is_available():
    sys.exit("torch.cuda.is_available() is False")
name = torch.cuda.get_device_name(0)
free, total = torch.cuda.mem_get_info(0)
print(f"  [OK]   PyTorch CUDA: {name} · free {free/1e9:.1f} GB / {total/1e9:.1f} GB")
PY

python - <<'PY' || warn "TensorRT import failed"
try:
    import tensorrt as trt
    print(f"  [OK]   TensorRT {trt.__version__}")
except ImportError as e:
    print(f"  [WARN] TensorRT: {e}")
PY

# --- Model engines ---
echo "--- TensorRT engines ---"
for f in Ship_classification_v2 species_classifier_bundle Before_and_after_v2; do
  p="$ROOT/Models/${f}.engine"
  if [ -f "$p" ]; then
    pass "$(basename "$p") ($(du -h "$p" | cut -f1))"
  else
    fail "Missing $p"
  fi
done

# --- Backend API ---
echo "--- Backend (port 8000) ---"
if curl -sf --max-time 3 http://127.0.0.1:8000/api/health >/dev/null; then
  pass "GET /api/health"
  SYS="$(curl -sf http://127.0.0.1:8000/api/system)"
  echo "$SYS" | python3 -c "
import json,sys
d=json.load(sys.stdin)
w=d.get('warmup','?')
dev=d.get('device','?')
ocr=d.get('ocr_gpu',False)
gpu=d.get('gpu_name','?')
mb=d.get('model_backends',{})
trt=all(mb.get(k,{}).get('backend')=='trt' for k in ('region','species','before_after'))
print(f'  [INFO] warmup={w} device={dev} ocr_gpu={ocr} gpu={gpu} all_trt={trt}')
if w!='ready': print('  [WARN] warmup not ready — wait or check uvicorn logs')
if dev!='cuda': print('  [FAIL] device is not cuda')
if not trt: print('  [WARN] not all models on TensorRT')
" || warn "Could not parse /api/system"
else
  fail "Backend not responding — start with: export NAUTICAI_USE_SQLITE=1 && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"
fi

# --- nginx / UI ---
echo "--- Frontend (nginx port 80) ---"
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1/ || echo 000)"
if [ "$CODE" = "200" ]; then
  pass "GET / → HTTP $CODE"
else
  fail "GET / → HTTP $CODE (build: cd frontend && npm install && npm run build; configure nginx)"
fi
API_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1/api/system || echo 000)"
if [ "$API_CODE" = "200" ]; then
  pass "GET /api/system via nginx → HTTP $API_CODE"
else
  fail "GET /api/system via nginx → HTTP $API_CODE (check proxy_pass in /etc/nginx/sites-available/nauticai)"
fi
if [ -d "$ROOT/frontend/dist" ]; then
  pass "frontend/dist exists"
else
  fail "frontend/dist missing — run: cd frontend && npm install && npm run build"
fi

# --- Inference speed (optional, ~30s) ---
echo "--- Inference benchmark (one dummy image) ---"
if curl -sf --max-time 3 http://127.0.0.1:8000/api/health >/dev/null; then
  python "$ROOT/backend/smoke_perf.py" 2>/dev/null | tail -8 || warn "smoke_perf.py failed"
else
  warn "Skipping benchmark — backend down"
fi

echo
if [ "${FAIL:-0}" -eq 0 ]; then
  echo "========== ALL CHECKS PASSED =========="
  echo "Open UI: http://$(hostname -I | awk '{print $1}')/"
  echo "GPU inference: backend only (TensorRT). UI is static files via nginx."
else
  echo "========== SOME CHECKS FAILED =========="
  exit 1
fi
