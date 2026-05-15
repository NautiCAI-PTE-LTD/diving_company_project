"""Runtime abstraction for the three vision models.

The backend supports three execution backends, picked automatically per model:

1. **TensorRT engine** (`.engine` / `.plan`) — preferred on Jetson Orin /
   any device with TensorRT installed. Reads the engine via pycuda.
2. **ONNX Runtime** (`.onnx`) — fast portable fallback. Used when ONNX
   Runtime + CUDA EP is installed but TensorRT is not.
3. **Native** (PyTorch `.pth` / `.pt`, Keras `.keras`) — original path that
   the development workstation uses today.

The first two are activated only if the artefact exists next to the original
checkpoint and the corresponding runtime is importable. Otherwise we silently
fall back so the dev box keeps working unchanged.

Lookup convention (relative to the original checkpoint path):
    Models/Ship_classification_v2.pth
      → TensorRT preference: Models/Ship_classification_v2.engine
      → ONNX preference:     Models/Ship_classification_v2.onnx
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
import logging
import os

import numpy as np

log = logging.getLogger("nauticai.runtime")

# Env knobs ------------------------------------------------------------------
# NAUTICAI_BACKEND=auto|trt|onnx|native — force a specific backend (default auto)
_FORCE = os.environ.get("NAUTICAI_BACKEND", "auto").strip().lower()
# NAUTICAI_TRT_FP16=1 — build new engines in FP16 (only relevant if engine
# generation is triggered at runtime; usually we ship a pre-built engine).
_TRT_FP16 = os.environ.get("NAUTICAI_TRT_FP16", "1").strip() not in ("0", "false", "no")


@dataclass
class RuntimeChoice:
    backend: str        # "trt" | "onnx" | "native"
    artefact: Optional[Path]
    reason: str


def resolve(checkpoint: Path) -> RuntimeChoice:
    """Decide which backend to use for ``checkpoint``.

    The caller is then expected to load the chosen artefact through the right
    helper (``TensorRTEngine`` / ``OnnxSession`` / native PyTorch).
    """
    stem = checkpoint.with_suffix("")
    trt_path  = stem.with_suffix(".engine")
    plan_path = stem.with_suffix(".plan")
    onnx_path = stem.with_suffix(".onnx")

    if _FORCE in ("native",):
        return RuntimeChoice("native", None, "NAUTICAI_BACKEND=native")

    # 1) TensorRT
    if _FORCE in ("auto", "trt"):
        candidate = trt_path if trt_path.exists() else (plan_path if plan_path.exists() else None)
        if candidate is not None:
            try:
                import tensorrt  # noqa: F401
                import pycuda.driver  # noqa: F401
                return RuntimeChoice("trt", candidate, f"engine={candidate.name}")
            except ImportError as e:
                log.info("Skipping TensorRT for %s (%s)", checkpoint.name, e)
        elif _FORCE == "trt":
            return RuntimeChoice(
                "native", None,
                f"NAUTICAI_BACKEND=trt but no engine next to {checkpoint.name}",
            )

    # 2) ONNX Runtime
    if _FORCE in ("auto", "onnx") and onnx_path.exists():
        try:
            import onnxruntime  # noqa: F401
            return RuntimeChoice("onnx", onnx_path, f"onnx={onnx_path.name}")
        except ImportError as e:
            log.info("Skipping ONNX Runtime for %s (%s)", checkpoint.name, e)

    return RuntimeChoice("native", None, "fallback to native checkpoint")


# ---------------------------------------------------------------------------
# TensorRT helper
# ---------------------------------------------------------------------------
def _resolve_trt_shape(shape: tuple, batch: int = 1) -> tuple:
    """Engines built with dynamic batch report ``-1`` in dim 0.  Fix before
    allocating GPU memory (``np.prod`` on ``-1`` overflows mem_alloc)."""
    out = []
    for i, d in enumerate(shape):
        if d == -1:
            out.append(batch if i == 0 else 1)
        else:
            out.append(int(d))
    return tuple(out)


class TensorRTEngine:
    """Thin wrapper around a TensorRT engine for synchronous single-batch
    inference. Designed for the small classifiers used here — not optimised
    for streaming or batched throughput.
    """

    def __init__(self, engine_path: Path, batch: int = 1):
        import tensorrt as trt
        import pycuda.autoinit  # noqa: F401  — initialise the CUDA context
        import pycuda.driver as cuda

        self._trt = trt
        self._cuda = cuda
        self._batch = batch
        self._logger = trt.Logger(trt.Logger.WARNING)
        runtime = trt.Runtime(self._logger)
        with open(engine_path, "rb") as f:
            self.engine = runtime.deserialize_cuda_engine(f.read())
        self.context = self.engine.create_execution_context()

        # Collect IO binding metadata.
        self.input_name = None
        self.output_name = None
        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            mode = self.engine.get_tensor_mode(name)
            if mode == trt.TensorIOMode.INPUT:
                self.input_name = name
                self.input_dtype = trt.nptype(self.engine.get_tensor_dtype(name))
            else:
                self.output_name = name
                self.output_dtype = trt.nptype(self.engine.get_tensor_dtype(name))

        # Resolve dynamic shapes (batch=-1 from build_trt.py optimisation profile).
        raw_in = tuple(self.engine.get_tensor_shape(self.input_name))
        self.input_shape = _resolve_trt_shape(raw_in, batch=batch)
        if not self.context.set_input_shape(self.input_name, self.input_shape):
            raise RuntimeError(
                f"TensorRT set_input_shape failed for {engine_path.name}: "
                f"{raw_in} -> {self.input_shape}"
            )
        raw_out = tuple(self.engine.get_tensor_shape(self.output_name))
        if any(d < 0 for d in raw_out):
            raw_out = tuple(self.context.get_tensor_shape(self.output_name))
        self.output_shape = _resolve_trt_shape(raw_out, batch=batch)

        log.info(
            "TRT engine %s · in=%s out=%s dtypes=%s/%s",
            engine_path.name, self.input_shape, self.output_shape,
            self.input_dtype, self.output_dtype,
        )

        # Allocate persistent device buffers
        in_size = int(np.prod(self.input_shape)) * np.dtype(self.input_dtype).itemsize
        out_size = int(np.prod(self.output_shape)) * np.dtype(self.output_dtype).itemsize
        if in_size <= 0 or out_size <= 0:
            raise RuntimeError(
                f"Invalid TRT buffer size for {engine_path.name}: "
                f"in={self.input_shape} out={self.output_shape}"
            )
        self._d_input = cuda.mem_alloc(in_size)
        self._d_output = cuda.mem_alloc(out_size)
        self.stream = cuda.Stream()
        self.context.set_tensor_address(self.input_name, int(self._d_input))
        self.context.set_tensor_address(self.output_name, int(self._d_output))

    def infer(self, x: np.ndarray) -> np.ndarray:
        """Run a single inference. ``x`` must match ``input_shape`` / ``input_dtype``."""
        cuda = self._cuda
        x = np.ascontiguousarray(x.astype(self.input_dtype, copy=False))
        if tuple(x.shape) != self.input_shape:
            raise ValueError(
                f"TRT input shape mismatch: got {x.shape}, expected {self.input_shape}"
            )
        out = np.empty(self.output_shape, dtype=self.output_dtype)
        cuda.memcpy_htod_async(self._d_input, x, self.stream)
        self.context.execute_async_v3(stream_handle=self.stream.handle)
        cuda.memcpy_dtoh_async(out, self._d_output, self.stream)
        self.stream.synchronize()
        return out


# ---------------------------------------------------------------------------
# ONNX Runtime helper
# ---------------------------------------------------------------------------
class OnnxSession:
    """Wraps an onnxruntime.InferenceSession. Picks CUDAExecutionProvider
    when available, otherwise falls back to CPUExecutionProvider so the
    same code works on developer laptops without a GPU."""

    def __init__(self, onnx_path: Path):
        import onnxruntime as ort
        providers = []
        try:
            available = ort.get_available_providers()
        except Exception:
            available = []
        if "TensorrtExecutionProvider" in available:
            providers.append("TensorrtExecutionProvider")
        if "CUDAExecutionProvider" in available:
            providers.append("CUDAExecutionProvider")
        providers.append("CPUExecutionProvider")

        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(onnx_path), so, providers=providers)
        self.input_name  = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        log.info("ONNX session for %s using providers=%s",
                 onnx_path.name, [p[0] if isinstance(p, tuple) else p for p in self.session.get_providers()])

    def infer(self, x: np.ndarray) -> np.ndarray:
        return self.session.run([self.output_name], {self.input_name: x})[0]


# ---------------------------------------------------------------------------
# Preprocessing helpers (kept identical to the PyTorch transforms so the
# ONNX / TRT outputs match the native path bit-for-bit-ish).
# ---------------------------------------------------------------------------
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(1, 3, 1, 1)
_IMAGENET_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(1, 3, 1, 1)


def preprocess_imagenet(pil_img, hw: Tuple[int, int]) -> np.ndarray:
    """Resize → CHW → normalise. Returns NCHW float32 with batch=1."""
    from PIL import Image
    h, w = hw
    img = pil_img.convert("RGB").resize((w, h), Image.BILINEAR)
    arr = np.asarray(img, dtype=np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)[None, ...]          # 1, C, H, W
    arr = (arr - _IMAGENET_MEAN) / _IMAGENET_STD
    return arr.astype(np.float32, copy=False)


def preprocess_keras_effnetv2(pil_img, hw: Tuple[int, int]) -> np.ndarray:
    """Match the EfficientNetV2 Keras pipeline used by the before/after
    model — raw uint8 RGB (the model has its own Rescaling layer)."""
    from PIL import Image
    h, w = hw
    img = pil_img.convert("RGB").resize((w, h), Image.BILINEAR)
    return np.asarray(img, dtype=np.float32)[None, ...]  # 1, H, W, C
