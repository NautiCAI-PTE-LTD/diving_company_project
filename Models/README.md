# Models directory

This folder holds the trained model weights consumed by the backend at runtime.
The binaries are **not** tracked in git because two of them exceed GitHub's
100 MB per-file limit. They are distributed separately via Google Drive (see
the project's internal share link) and must be copied in by hand on every
fresh clone.

## Required files

| File                                 | Size      | Used by                                  |
| ------------------------------------ | --------- | ---------------------------------------- |
| `Ship_classification_v2.pth`         | ~107 MB   | `backend/inference/region.py` (Swin-Tiny) |
| `Before_and_after_v2.keras`          | ~49 MB    | `backend/inference/before_after.py`       |
| `species_classifier_bundle.pt`       | ~16 MB    | `backend/inference/species.py` (EffNet-B0)|

Total: ~172 MB.

## How to install

### Workstation (Windows / Linux dev)

1. Download `Models_for_Jetson.zip` from the shared Drive folder.
2. Unzip into this directory so the three files above sit at the top level:

   ```
   Models/
     ├─ Ship_classification_v2.pth
     ├─ Before_and_after_v2.keras
     └─ species_classifier_bundle.pt
   ```
3. Start the backend (`uvicorn backend.main:app --reload --port 8000`). The
   first request after boot will lazy-load each model into GPU memory.

### Jetson Orin Nano (edge deployment)

The Jetson uses **TensorRT FP16 engines** for high-throughput inference.
After unzipping the weights into `Models/`, run the build pipeline once:

```bash
python scripts/export_onnx.py        # → produces *.onnx next to each .pth/.keras
python scripts/build_trt.py --fp16   # → produces *.engine consumed at runtime
```

See `deploy/jetson/README.md` for the full Jetson deployment recipe.

### GCP / cloud GPU (NVIDIA L4, A10, T4)

Same ONNX → TensorRT pipeline on the **GPU VM** (not on a laptop):

```bash
./deploy/gcp-l4/setup_gpu_models.sh
```

Copy `deploy/gcp-l4/env.production.example` → `backend/.env` with `NAUTICAI_GPU_PROFILE=l4`.

See **`deploy/gcp-l4/README.md`** for GCE + S3/CloudFront layout.

Optional fast path without pre-built `.engine` files: set `NAUTICAI_ORT_TRT=1` so ONNX Runtime compiles TensorRT kernels on first run (cached under `Models/.ort_trt_cache/`).

## Why not Git LFS?

Git LFS would work but burns GitHub's monthly LFS bandwidth quota every time
the Jetson re-clones the repo. Hosting the zip on Drive sidesteps that and
keeps the public history clean.
