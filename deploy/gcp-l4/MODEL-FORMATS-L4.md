# Model formats on NVIDIA L4

The API does **not** run `.pth` / `.pt` / `.keras` directly in production on L4 when faster artefacts exist.

## Speed order (per photo, all 3 models)

| Priority | File type | Used for | Typical L4 latency |
| -------- | --------- | -------- | ------------------ |
| 1 | **`.engine`** | TensorRT FP16 | ~15–35 ms |
| 2 | **`.onnx`** | ONNX Runtime + CUDA | ~25–50 ms |
| 3 | **`.pth` / `.pt` / `.keras`** | Native PyTorch / TensorFlow | ~80–150 ms |

Logic: `backend/inference/_runtime.py` → `resolve()` picks `.engine` → `.onnx` → native checkpoint.

## What each training file is

| Source file | Format | Export target | L4 production use |
| ----------- | ------ | ------------- | ----------------- |
| `Ship_classification_v2.pth` | PyTorch | `Ship_classification_v2.onnx` → `.engine` | ONNX or TRT, not `.pth` |
| `species_classifier_bundle.pt` | PyTorch bundle | `species_classifier_bundle.onnx` → `.engine` | ONNX or TRT, not `.pt` |
| `Before_and_after_v2.keras` | Keras | `Before_and_after_v2.onnx` → `.engine` | ONNX or TRT (Keras on GPU is slow) |

## GCS zip contents (recommended)

| Include | Why |
| ------- | --- |
| All 3 **`.onnx`** | Fast path immediately after VM install |
| All 3 **sources** (`.pth`, `.keras`, `.pt`) | Re-export if needed; required for some TRT tooling |
| **`.engine`** | Do **not** zip from Windows — build on the L4 VM with `scripts/build_trt.py --fp16` |

## One-time ONNX export (before building zip on Windows)

```powershell
cd F:\Diving_company_project
.\.venv\Scripts\Activate.ps1
$env:NAUTICAI_BACKEND = "native"
python scripts\export_onnx.py
```

Then:

```powershell
.\deploy\gcp-l4\build-l4-gcs-bundle.ps1
```

## On the L4 VM after unzip

1. API starts with **ONNX CUDA** (from zip).
2. Optional: `python scripts/build_trt.py --fp16` → **`.engine`** (fastest).
3. Set `NAUTICAI_BACKEND=auto` and `NAUTICAI_GPU_PROFILE=l4` in `backend/.env`.

Check: `curl http://127.0.0.1:8000/api/system` → backends should show `onnx` or `trt`, `device: cuda`.
