#!/usr/bin/env bash
# Jetson Orin Nano bootstrap — installs system packages, creates the venv,
# installs the right PyTorch wheel, and runs requirements-jetson.txt.
#
# Usage:
#   chmod +x deploy/jetson/install.sh
#   ./deploy/jetson/install.sh
#
# Pre-requisites:
#   - JetPack 6.x flashed
#   - Cloned this repo to ~/diving_company_project (or wherever)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

echo "──────────────────────────────────────────────────────────────────────"
echo " NautiCAI · Jetson Orin Nano installer"
echo " Repo: $REPO_DIR"
echo "──────────────────────────────────────────────────────────────────────"

# 1. System packages
sudo apt update
sudo apt install -y \
    python3-pip python3-venv python3-dev \
    libopenblas-dev libomp-dev libjpeg-dev libpng-dev libtiff-dev \
    libpq-dev curl

# 2. Performance mode
echo "[+] Setting MAXN power profile + jetson_clocks"
sudo nvpmodel -m 0 || true
sudo jetson_clocks  || true

# 3. Virtualenv
if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip wheel setuptools

# 4. PyTorch + torchvision — these wheels are not on PyPI for aarch64+CUDA,
#    you must download the one matching your JetPack version yourself.
#    See: https://developer.download.nvidia.com/compute/redist/jp/v60/pytorch/
TORCH_WHEEL="${TORCH_WHEEL:-}"
if [[ -z "$TORCH_WHEEL" ]]; then
    echo "[!] TORCH_WHEEL not set."
    echo "    Download the wheel for your JetPack version from"
    echo "    https://developer.download.nvidia.com/compute/redist/jp/v60/pytorch/"
    echo "    then rerun with:"
    echo "      TORCH_WHEEL=/path/to/torch-2.3.0-cp310-cp310-linux_aarch64.whl ./deploy/jetson/install.sh"
    exit 1
fi
pip install "$TORCH_WHEEL"

# 5. torchvision compiled against this torch (matches version table in
#    https://github.com/pytorch/vision#installation)
TV_REF="${TV_REF:-v0.18.0}"
pip install --no-build-isolation "torchvision @ git+https://github.com/pytorch/vision.git@${TV_REF}"

# 6. Project deps
pip install -r backend/requirements-jetson.txt
# easyocr's wheel insists on pinning torch via PyPI; install it without deps
# after torch is already present.
pip install --no-deps easyocr

# 7. Quick sanity check
python - <<'PY'
import torch, sys
print("torch          :", torch.__version__)
print("cuda available :", torch.cuda.is_available())
print("device         :", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU")
try:
    import tensorrt
    print("tensorrt       :", tensorrt.__version__)
except Exception as e:
    print("tensorrt       : NOT IMPORTABLE —", e, file=sys.stderr)
try:
    import onnxruntime as ort
    print("onnxruntime    :", ort.__version__, "providers=", ort.get_available_providers())
except Exception as e:
    print("onnxruntime    : NOT IMPORTABLE —", e, file=sys.stderr)
PY

echo ""
echo "──────────────────────────────────────────────────────────────────────"
echo " Done. Next steps:"
echo "   1. Copy Models/*.pth, *.keras, *.pt into Models/"
echo "   2. Copy the corresponding *.onnx files from your dev box"
echo "   3. Build TRT engines:  python scripts/build_trt.py --fp16"
echo "   4. Start the backend:  uvicorn backend.main:app --host 0.0.0.0 --port 8000"
echo "──────────────────────────────────────────────────────────────────────"
