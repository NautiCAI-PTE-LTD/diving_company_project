#!/usr/bin/env python3
"""Quick GPU inference check — backends, latency, VRAM hint.

Usage on the L4 VM:
  export NAUTICAI_DEVICE=cuda NAUTICAI_GPU_PROFILE=l4
  python scripts/verify_gpu_inference.py
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image

from backend import config
from backend.inference import _runtime as rt
from backend.inference import before_after as ba
from backend.inference import region as reg
from backend.inference import species as sp


def _bench(label: str, fn, pil: Image.Image, n: int = 8) -> float:
    for _ in range(2):
        fn(pil)
    if config.DEVICE == "cuda":
        import torch
        torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(n):
        fn(pil)
    if config.DEVICE == "cuda":
        import torch
        torch.cuda.synchronize()
    ms = (time.perf_counter() - t0) / n * 1000
    print(f"  {label}: {ms:.1f} ms/image (n={n})")
    return ms


def main() -> int:
    print(f"device={config.DEVICE}  profile={config.GPU_PROFILE or '(none)'}")
    for ckpt in (config.SHIP_REGION_CKPT, config.SPECIES_CKPT, config.BEFORE_AFTER_CKPT):
        ch = rt.resolve(ckpt)
        print(f"  {ckpt.name} -> {ch.backend} ({ch.reason})")

    pil = Image.new("RGB", (1280, 960), (40, 80, 120))
    print("\nWarmup + benchmark (1280px input -> 224 model):")
    r_ms = _bench("region", reg.predict, pil)
    s_ms = _bench("species", sp.predict, pil)
    b_ms = _bench("before/after", ba.predict, pil)
    total = r_ms + s_ms + b_ms
    print(f"  three models serial total: ~{total:.1f} ms/image")

    if config.DEVICE == "cuda":
        try:
            import torch
            alloc = torch.cuda.memory_allocated() / 1e9
            reserved = torch.cuda.memory_reserved() / 1e9
            print(f"\nCUDA memory: allocated={alloc:.2f} GB reserved={reserved:.2f} GB")
        except Exception:
            pass

    backends = {rt.resolve(c).backend for c in (
        config.SHIP_REGION_CKPT, config.SPECIES_CKPT, config.BEFORE_AFTER_CKPT)}
    if "trt" in backends:
        print("\nOK: TensorRT engines active (best L4 throughput).")
    elif backends == {"onnx"}:
        print("\nOK: ONNX Runtime CUDA active. Run setup_gpu_models.sh to add .engine for more speed.")
    else:
        print("\nWARN: Using native PyTorch/Keras — export ONNX + TRT on this VM for production speed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
