#!/usr/bin/env bash
# Paste on the L4 VM after SSH (one block). Uses your public GCS zip URL.
set -euo pipefail

export BUNDLE_URL="${BUNDLE_URL:-https://storage.googleapis.com/yolo-dataset-bucket-1/nauticai-l4-gcs-bundle.zip}"
export REPO_URL="${REPO_URL:-https://github.com/NautiCAI-PTE-LTD/diving_company_project.git}"
export INSTALL_DIR="${INSTALL_DIR:-/opt/nauticai/app}"
export MODELS_DIR="${MODELS_DIR:-/opt/nauticai/Models}"
export BUNDLE_DIR="${BUNDLE_DIR:-/opt/nauticai/bundle}"

echo "=== GPU ==="
nvidia-smi || { echo "Install NVIDIA driver and reboot first."; exit 1; }

echo "=== Packages ==="
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git curl ca-certificates unzip \
  libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgomp1

sudo mkdir -p /opt/nauticai "$MODELS_DIR" "$BUNDLE_DIR"
sudo chown -R "$USER:$USER" /opt/nauticai

echo "=== Download zip ==="
mkdir -p "$BUNDLE_DIR"
curl -fL --retry 3 --retry-delay 5 -o "$BUNDLE_DIR/bundle.zip" "$BUNDLE_URL"
unzip -q -o "$BUNDLE_DIR/bundle.zip" -d "$BUNDLE_DIR"
cp -f "$BUNDLE_DIR"/models/* "$MODELS_DIR/"

echo "=== Clone app ==="
if [[ ! -d "$INSTALL_DIR/.git" ]]; then
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"
git pull --ff-only 2>/dev/null || true
ln -sfn "$MODELS_DIR" "$INSTALL_DIR/Models"

echo "=== Python + deps ==="
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel setuptools
pip install -r backend/requirements.txt -r backend/requirements-gpu.txt

if [[ ! -f backend/.env ]]; then
  cp deploy/gcp-l4/env.production.example backend/.env
  echo "JWT_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')" >> backend/.env
fi

export NAUTICAI_DEVICE=cuda
export NAUTICAI_GPU_PROFILE=l4
export NAUTICAI_BACKEND=auto

if [[ ! -f "$MODELS_DIR/Ship_classification_v2.onnx" ]]; then
  export NAUTICAI_BACKEND=native
  python scripts/export_onnx.py
fi

if python -c "import tensorrt" 2>/dev/null && [[ ! -f "$MODELS_DIR/Ship_classification_v2.engine" ]]; then
  python scripts/build_trt.py --fp16 --workspace-mb 2048
fi

python scripts/verify_gpu_inference.py || true
mkdir -p backend/storage/uploads backend/storage/reports

sed "s/^User=.*/User=${USER}/; s/^Group=.*/Group=${USER}/" deploy/gcp-l4/nauticai-api.service \
  | sudo tee /etc/systemd/system/nauticai-api.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now nauticai-api

sleep 4
curl -sf http://127.0.0.1:8000/api/health && echo ""
IP=$(curl -sf -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip || true)
echo "=== Done ==="
echo "Local:  http://127.0.0.1:8000/api/health"
[[ -n "$IP" ]] && echo "External (open firewall TCP 8000): http://${IP}:8000/api/health"
echo "Edit DATABASE_URL: nano ${INSTALL_DIR}/backend/.env && sudo systemctl restart nauticai-api"
