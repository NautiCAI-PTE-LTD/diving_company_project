#!/usr/bin/env bash
# Full backend deploy on a GCP L4 VM.
#
# Prerequisites on VM:
#   - Ubuntu 22.04, NVIDIA driver 535+, nvidia-smi works
#   - gcloud CLI (or gsutil) authenticated for your bucket
#   - App repo cloned at /opt/nauticai/app (or set INSTALL_DIR)
#
# Before running, upload from your PC:
#   deploy/gcp-l4/dist/nauticai-l4-gcs-bundle.zip  →  gs://$GCS_BUCKET/$GCS_ZIP
#
# Usage (public HTTPS zip):
#   export BUNDLE_URL=https://storage.googleapis.com/BUCKET/nauticai-l4-gcs-bundle.zip
#   export REPO_URL=https://github.com/YOUR_ORG/diving_company_project.git
#   ./deploy/gcp-l4/install-on-vm.sh
#
# Usage (private GCS bucket):
#   export GCS_BUCKET=nauticai-prod-artifacts
#   export GCS_ZIP=nauticai-l4-gcs-bundle.zip
set -euo pipefail

BUNDLE_URL="${BUNDLE_URL:-}"
GCS_BUCKET="${GCS_BUCKET:-}"
GCS_ZIP="${GCS_ZIP:-nauticai-l4-gcs-bundle.zip}"
INSTALL_DIR="${INSTALL_DIR:-/opt/nauticai/app}"
MODELS_DIR="${MODELS_DIR:-/opt/nauticai/Models}"
BUNDLE_DIR="${BUNDLE_DIR:-/opt/nauticai/bundle}"
REPO_URL="${REPO_URL:-}"
BRANCH="${BRANCH:-main}"

echo "══════════════════════════════════════════════════════════════"
echo " NautiCAI · L4 full install"
if [[ -n "$BUNDLE_URL" ]]; then
  echo " Bundle: ${BUNDLE_URL}"
else
  echo " Bucket: gs://${GCS_BUCKET}/${GCS_ZIP}"
fi
echo " App:    ${INSTALL_DIR}"
echo " Models: ${MODELS_DIR}"
echo "══════════════════════════════════════════════════════════════"

if ! command -v nvidia-smi &>/dev/null; then
  echo "ERROR: nvidia-smi not found. Install NVIDIA driver 535+ and reboot."
  exit 1
fi
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader

sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip git curl ca-certificates unzip \
  libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgomp1

sudo mkdir -p /opt/nauticai "$MODELS_DIR" "$BUNDLE_DIR"
sudo chown -R "$USER:$USER" /opt/nauticai

echo "Downloading bundle..."
rm -rf "$BUNDLE_DIR"/*
if [[ -n "$BUNDLE_URL" ]]; then
  curl -fL --retry 3 --retry-delay 5 -o "$BUNDLE_DIR/bundle.zip" "$BUNDLE_URL"
elif [[ -n "$GCS_BUCKET" ]]; then
  if ! command -v gcloud &>/dev/null; then
    echo "Installing Google Cloud CLI..."
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | \
      sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list
    sudo apt-get update && sudo apt-get install -y google-cloud-cli
  fi
  gcloud storage cp "gs://${GCS_BUCKET}/${GCS_ZIP}" "$BUNDLE_DIR/bundle.zip"
else
  echo "ERROR: set BUNDLE_URL (public https) or GCS_BUCKET"
  exit 1
fi
unzip -q -o "$BUNDLE_DIR/bundle.zip" -d "$BUNDLE_DIR"

mkdir -p "$MODELS_DIR"
cp -f "$BUNDLE_DIR"/models/* "$MODELS_DIR/" 2>/dev/null || cp -f "$BUNDLE_DIR"/models/*.* "$MODELS_DIR/"

for f in \
  Ship_classification_v2.pth \
  Before_and_after_v2.keras \
  species_classifier_bundle.pt; do
  if [[ ! -f "${MODELS_DIR}/${f}" ]]; then
    echo "ERROR: Missing ${MODELS_DIR}/${f} after unzip"
    exit 1
  fi
done
echo "Models installed under ${MODELS_DIR}"

if [[ -n "$REPO_URL" ]]; then
  if [[ ! -d "${INSTALL_DIR}/.git" ]]; then
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
  else
    git -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH" || true
    git -C "$INSTALL_DIR" checkout "$BRANCH" || true
    git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH" 2>/dev/null || true
  fi
fi

if [[ ! -f "${INSTALL_DIR}/backend/main.py" ]]; then
  echo "ERROR: App not found at ${INSTALL_DIR}. Clone the repo first or set REPO_URL."
  exit 1
fi

cd "$INSTALL_DIR"
ln -sfn "$MODELS_DIR" "$INSTALL_DIR/Models"

# Copy deploy scripts from bundle if repo deploy folder is older
if [[ -d "$BUNDLE_DIR/deploy/gcp-l4" ]]; then
  mkdir -p deploy/gcp-l4
  cp -f "$BUNDLE_DIR"/deploy/gcp-l4/*.sh deploy/gcp-l4/ 2>/dev/null || true
  cp -f "$BUNDLE_DIR"/deploy/gcp-l4/env.production.example deploy/gcp-l4/ 2>/dev/null || true
  cp -f "$BUNDLE_DIR"/deploy/gcp-l4/nauticai-api.service deploy/gcp-l4/ 2>/dev/null || true
  chmod +x deploy/gcp-l4/*.sh 2>/dev/null || true
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -U pip wheel setuptools
pip install -r backend/requirements.txt -r backend/requirements-gpu.txt

export NAUTICAI_DEVICE=cuda
# L4 production path: .onnx (from zip) or .engine (built below) — not raw .pth/.keras/.pt
if [[ ! -f "${MODELS_DIR}/Ship_classification_v2.onnx" ]] \
   || [[ ! -f "${MODELS_DIR}/Before_and_after_v2.onnx" ]] \
   || [[ ! -f "${MODELS_DIR}/species_classifier_bundle.onnx" ]]; then
  echo "ONNX missing — exporting from source checkpoints (one-time)..."
  export NAUTICAI_BACKEND=native
  python scripts/export_onnx.py
else
  echo "ONNX present (fast L4 path) — skipping export"
fi
export NAUTICAI_BACKEND=auto

if python -c "import tensorrt" 2>/dev/null; then
  if [[ ! -f "${MODELS_DIR}/Ship_classification_v2.engine" ]]; then
    echo "Building TensorRT engines (10–20 min)..."
    python scripts/build_trt.py --fp16 --workspace-mb 2048
  else
    echo "TensorRT engines present — skipping build"
  fi
else
  echo "TensorRT not installed — using ONNX Runtime CUDA (fine on L4)"
fi

export NAUTICAI_GPU_PROFILE=l4
python scripts/verify_gpu_inference.py || true

mkdir -p backend/storage/uploads backend/storage/reports
if [[ ! -f backend/.env ]]; then
  cp deploy/gcp-l4/env.production.example backend/.env
  JWT=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
  echo "" >> backend/.env
  echo "# Generated on install — edit DATABASE_URL before production traffic" >> backend/.env
  echo "JWT_SECRET=${JWT}" >> backend/.env
  echo ""
  echo "[!] Edit ${INSTALL_DIR}/backend/.env — set DATABASE_URL (Supabase/Postgres)"
fi

sed "s/^User=.*/User=${USER}/; s/^Group=.*/Group=${USER}/" deploy/gcp-l4/nauticai-api.service \
  | sudo tee /etc/systemd/system/nauticai-api.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable nauticai-api
sudo systemctl restart nauticai-api || sudo systemctl start nauticai-api

sleep 3
if curl -sf http://127.0.0.1:8000/api/health >/dev/null; then
  echo ""
  echo "SUCCESS — API is up on port 8000"
  curl -s http://127.0.0.1:8000/api/health
  echo ""
  EXTERNAL=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip 2>/dev/null || true)
  if [[ -n "$EXTERNAL" ]]; then
    echo "External URL: http://${EXTERNAL}:8000/api/health"
    echo "Open firewall TCP 8000 or put HTTPS in front before AWS UI goes live."
  fi
else
  echo "WARN: health check failed — run: journalctl -u nauticai-api -n 80 --no-pager"
  exit 1
fi
