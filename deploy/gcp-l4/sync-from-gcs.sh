#!/usr/bin/env bash
# Download model weights (and optional built ONNX/TRT) from GCS to /opt/nauticai/Models.
#
# Usage on the GPU VM:
#   export GCS_BUCKET=nauticai-prod-artifacts
#   cd /opt/nauticai/app && ./deploy/gcp-l4/sync-from-gcs.sh
set -euo pipefail

BUCKET="${GCS_BUCKET:?Set GCS_BUCKET, e.g. export GCS_BUCKET=nauticai-prod-artifacts}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MODELS_DIR="${MODELS_DIR:-/opt/nauticai/Models}"

mkdir -p "$MODELS_DIR"

echo "Syncing gs://${BUCKET}/models/ → ${MODELS_DIR}/"
gcloud storage cp -r "gs://${BUCKET}/models/*" "${MODELS_DIR}/"

if gcloud storage ls "gs://${BUCKET}/models-built/" &>/dev/null; then
  echo "Syncing optional built artefacts from models-built/ …"
  gcloud storage cp "gs://${BUCKET}/models-built/*" "${MODELS_DIR}/" 2>/dev/null || true
fi

for f in \
  Ship_classification_v2.pth \
  species_classifier_bundle.pt \
  Before_and_after_v2.keras; do
  if [[ ! -f "${MODELS_DIR}/${f}" ]]; then
    echo "ERROR: Still missing ${MODELS_DIR}/${f}"
    exit 1
  fi
done

# App expects Models/ next to repo root
if [[ "$MODELS_DIR" != "$ROOT/Models" ]]; then
  if [[ -e "$ROOT/Models" && ! -L "$ROOT/Models" ]]; then
    echo "WARN: $ROOT/Models exists; using MODELS_DIR=$MODELS_DIR in env or symlink manually."
  else
    ln -sfn "$MODELS_DIR" "$ROOT/Models"
  fi
fi

echo "Models ready in ${MODELS_DIR}"
