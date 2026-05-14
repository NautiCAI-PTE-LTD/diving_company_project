"""Before / After cleaning binary classifier (EfficientNetV2-B0 fine-tune).

The production model file is ``Models/Before_and_after_v2.keras``. Backends:

    1. TensorRT engine — ``Models/Before_and_after_v2.engine``  (Jetson)
    2. ONNX Runtime   — ``Models/Before_and_after_v2.onnx``    (any GPU box)
    3. Native Keras   — ``Models/Before_and_after_v2.keras``   (dev laptop)

The Keras model bundles its own ``Rescaling`` layer (uint8 → [-1, 1]). The
ONNX exporter preserves that, so the preprocess pipeline is identical for
all three backends: just resize to the model's expected HxW and feed raw
float32 RGB pixels.

Public API (unchanged):
    predict(pil_img: PIL.Image.Image) -> {"id": "before"|"after", "confidence": float}

The convention is **high sigmoid -> "after" (clean)**, matching the
training labels (0 = before, 1 = after). Set ``NAUTICAI_BA_INVERT=1`` to
flip the convention without retraining.
"""
from __future__ import annotations
from threading import Lock
from typing import Optional
import logging
import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

import numpy as np
from PIL import Image

from .. import config
from . import _runtime

log = logging.getLogger("nauticai.before_after")
_LOCK = Lock()
_RUNTIME: Optional[_runtime.RuntimeChoice] = None
_MODEL = None
_INPUT_HW: tuple[int, int] = (224, 224)


def _load_native_keras() -> tuple:
    import tensorflow as tf
    model = tf.keras.models.load_model(str(config.BEFORE_AFTER_CKPT))
    in_shape = model.inputs[0].shape
    h = int(in_shape[1] or 224); w = int(in_shape[2] or 224)
    log.info("Before/After model ready · input=%dx%d · params=%d",
             h, w, model.count_params())
    return model, (h, w)


def _infer_hw_from_onnx(onnx_path) -> tuple[int, int]:
    try:
        import onnx
        m = onnx.load(str(onnx_path))
        shape = m.graph.input[0].type.tensor_type.shape.dim
        h = int(shape[1].dim_value or 224)
        w = int(shape[2].dim_value or 224)
        return (h, w)
    except Exception:
        return (224, 224)


def _load() -> None:
    """Lazy-load on first prediction. Idempotent."""
    global _MODEL, _INPUT_HW, _RUNTIME
    if _MODEL is not None:
        return
    _RUNTIME = _runtime.resolve(config.BEFORE_AFTER_CKPT)
    log.info("Before/After backend=%s · %s", _RUNTIME.backend, _RUNTIME.reason)

    if _RUNTIME.backend == "trt":
        _MODEL = _runtime.TensorRTEngine(_RUNTIME.artefact)
        # TRT shape is NHWC for this model (Keras-derived)
        shp = _MODEL.input_shape
        if len(shp) == 4 and shp[-1] == 3:
            _INPUT_HW = (int(shp[1]), int(shp[2]))
        else:
            _INPUT_HW = (int(shp[2]), int(shp[3]))
    elif _RUNTIME.backend == "onnx":
        _MODEL = _runtime.OnnxSession(_RUNTIME.artefact)
        _INPUT_HW = _infer_hw_from_onnx(_RUNTIME.artefact)
    else:
        _MODEL, _INPUT_HW = _load_native_keras()


def predict(pil_img: Image.Image) -> dict:
    """Return ``{"id": "before"|"after", "confidence": float in [0.5, 1.0]}``."""
    with _LOCK:
        _load()

    h, w = _INPUT_HW

    if _RUNTIME.backend in ("trt", "onnx"):
        arr = _runtime.preprocess_keras_effnetv2(pil_img, (h, w))
        out = _MODEL.infer(arr)
        p = float(np.asarray(out).reshape(-1)[0])
    else:
        img = pil_img.convert("RGB").resize((w, h))
        arr = np.expand_dims(np.array(img, dtype=np.float32), 0)
        p = float(_MODEL.predict(arr, verbose=0)[0, 0])

    if os.environ.get("NAUTICAI_BA_INVERT", "0") == "1":
        p = 1.0 - p

    if p >= 0.5:
        return {"id": "after",  "confidence": p}
    return {"id": "before", "confidence": 1.0 - p}


def runtime_info() -> dict:
    with _LOCK:
        _load()
    return {"backend": _RUNTIME.backend, "reason": _RUNTIME.reason,
            "artefact": str(_RUNTIME.artefact) if _RUNTIME.artefact else None}
