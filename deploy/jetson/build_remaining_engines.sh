#!/bin/bash
# Build Ship + Species TensorRT engines. Safe to run with nohup so TeamViewer
# disconnect does not stop the build. Requires Before/After engine already built.
set -euo pipefail

cd "${HOME}/diving_company_project"
source .venv/bin/activate
export PATH=/usr/local/cuda/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH

echo "=== Ship build START $(date) ==="
python scripts/build_trt.py --fp16 --only Ship_classification_v2.onnx

echo "=== Species build START $(date) ==="
python scripts/build_trt.py --fp16 --only species_classifier_bundle.onnx

echo "=== ALL DONE $(date) ==="
ls -lh Models/*.engine
