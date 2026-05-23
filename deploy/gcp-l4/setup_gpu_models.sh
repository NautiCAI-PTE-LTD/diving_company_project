#!/usr/bin/env bash
# One-time model prep on the GCP L4 (or any CUDA 12 + TensorRT) VM.
# Produces Models/*.onnx and Models/*.engine for maximum inference speed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if ! command -v nvidia-smi &>/dev/null; then
  echo "ERROR: nvidia-smi not found. Install NVIDIA driver 535+ first."
  exit 1
fi
echo "GPU:"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader

PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON=python3
fi

echo "Installing GPU Python deps..."
"$PYTHON" -m pip install -q -r backend/requirements.txt -r backend/requirements-gpu.txt

for f in \
  Models/Ship_classification_v2.pth \
  Models/species_classifier_bundle.pt \
  Models/Before_and_after_v2.keras; do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: Missing $f — copy model weights into Models/ first."
    exit 1
  fi
done

export NAUTICAI_BACKEND=native
export NAUTICAI_DEVICE=cuda

echo "Exporting ONNX (run once)..."
"$PYTHON" scripts/export_onnx.py

if "$PYTHON" -c "import tensorrt" 2>/dev/null; then
  echo "Building TensorRT FP16 engines (5–15 min total on L4)..."
  "$PYTHON" scripts/build_trt.py --fp16 --workspace-mb 2048
else
  echo "WARN: tensorrt not installed — skipping .engine build."
  echo "      Inference will use ONNX Runtime CUDA (still fast on L4)."
  echo "      To enable TRT: install NVIDIA TensorRT for CUDA 12, then pip install pycuda"
fi

echo "Verifying backends..."
export NAUTICAI_BACKEND=auto
export NAUTICAI_GPU_PROFILE=l4
"$PYTHON" scripts/verify_gpu_inference.py

echo ""
echo "Done. Add deploy/gcp-l4/env.production.example values to backend/.env and start:"
echo "  uvicorn backend.main:app --host 0.0.0.0 --port 8000"
