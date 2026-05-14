"""Hull-region classifier (Swin-Tiny @ 224, 11 classes).

Backend selection (auto, see ``_runtime.resolve``):
    1. TensorRT engine — ``Models/Ship_classification_v2.engine``
    2. ONNX Runtime   — ``Models/Ship_classification_v2.onnx``
    3. Native PyTorch — ``Models/Ship_classification_v2.pth``
"""
from __future__ import annotations
from threading import Lock
from typing import Optional
import logging

import numpy as np
from PIL import Image

from .. import config
from . import _runtime

log = logging.getLogger("nauticai.region")

_LOCK = Lock()
_RUNTIME: Optional[_runtime.RuntimeChoice] = None
_MODEL = None              # PyTorch module (native) OR TensorRTEngine / OnnxSession
_TFM = None                # PyTorch transform (only used by native path)
_CLASS_NAMES: list[str] = []
_IMG_SIZE: int = 224


def _build_head(num_classes: int):
    """Mirrors head.0..6 found in Ship_classification_vby_swin.pth checkpoint:

        head.0 = BatchNorm1d(768)        ← running_mean/var present
        head.1 = ReLU
        head.2 = Linear(768 → 512)
        head.3 = ReLU
        head.4 = BatchNorm1d(512)        ← running_mean/var present
        head.5 = Dropout
        head.6 = Linear(512 → num_classes)

    Imports torch.nn locally so the module can be imported on a Jetson that
    only has TensorRT engines available (no PyTorch dep needed at runtime).
    """
    import torch.nn as nn
    return nn.Sequential(
        nn.BatchNorm1d(768),
        nn.ReLU(inplace=True),
        nn.Linear(768, 512),
        nn.ReLU(inplace=True),
        nn.BatchNorm1d(512),
        nn.Dropout(0.0),
        nn.Linear(512, num_classes),
    )


def _load_native_torch() -> tuple:
    """Slow path that builds the PyTorch model. Returns (model, tfm, class_names, img_size)."""
    import torch
    import torch.nn as nn
    import timm
    from torchvision import transforms

    class _SwinClassifier(nn.Module):
        def __init__(self, num_classes: int):
            super().__init__()
            self.base = timm.create_model("swin_tiny_patch4_window7_224",
                                          pretrained=False, num_classes=0)
            self.head = _build_head(num_classes)

        def forward(self, x):
            return self.head(self.base(x))

    ckpt = torch.load(str(config.SHIP_REGION_CKPT), map_location="cpu", weights_only=False)
    class_names = list(ckpt["class_names"])
    img_size = int(ckpt.get("img_size", 224))
    model = _SwinClassifier(num_classes=ckpt["num_classes"])
    model.load_state_dict(ckpt["model_state"])
    model.to(config.DEVICE).eval()
    tfm = transforms.Compose([
        transforms.Resize((img_size, img_size)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                             std =[0.229, 0.224, 0.225]),
    ])
    return model, tfm, class_names, img_size


def _read_class_names_fallback() -> tuple[list[str], int]:
    """When using TRT/ONNX we still need the class-name mapping & img size,
    which live in the original ``.pth`` checkpoint. Read just the metadata
    (cheap — torch.load reads the pickled header into CPU)."""
    try:
        import torch
        ckpt = torch.load(str(config.SHIP_REGION_CKPT), map_location="cpu",
                          weights_only=False)
        return list(ckpt["class_names"]), int(ckpt.get("img_size", 224))
    except Exception:
        log.warning("Couldn't read class names from %s — using config.HULL_REGIONS",
                    config.SHIP_REGION_CKPT)
        return list(config.HULL_REGIONS), 224


def _load() -> None:
    global _MODEL, _TFM, _CLASS_NAMES, _RUNTIME, _IMG_SIZE
    if _MODEL is not None:
        return
    _RUNTIME = _runtime.resolve(config.SHIP_REGION_CKPT)
    log.info("Region classifier backend=%s · %s", _RUNTIME.backend, _RUNTIME.reason)

    if _RUNTIME.backend == "trt":
        _MODEL = _runtime.TensorRTEngine(_RUNTIME.artefact)
        _CLASS_NAMES, _IMG_SIZE = _read_class_names_fallback()
    elif _RUNTIME.backend == "onnx":
        _MODEL = _runtime.OnnxSession(_RUNTIME.artefact)
        _CLASS_NAMES, _IMG_SIZE = _read_class_names_fallback()
    else:
        _MODEL, _TFM, _CLASS_NAMES, _IMG_SIZE = _load_native_torch()


def predict(pil_img: Image.Image) -> dict:
    """Returns {id, display, confidence, distribution: [{id, display, prob}, ...]}."""
    with _LOCK:
        _load()

    if _RUNTIME.backend in ("trt", "onnx"):
        x = _runtime.preprocess_imagenet(pil_img, (_IMG_SIZE, _IMG_SIZE))
        logits = _MODEL.infer(x).reshape(-1)
        e = np.exp(logits - logits.max())
        probs = (e / e.sum()).tolist()
    else:
        import torch
        with torch.inference_mode():
            x = _TFM(pil_img.convert("RGB")).unsqueeze(0).to(config.DEVICE,
                                                            non_blocking=True)
            if config.USE_FP16:
                with torch.amp.autocast("cuda", dtype=torch.float16):
                    logits = _MODEL(x).squeeze(0)
            else:
                logits = _MODEL(x).squeeze(0)
            probs = torch.softmax(logits.float(), dim=0).cpu().tolist()

    pairs = sorted(
        [{"id": c, "display": config.HULL_REGION_DISPLAY.get(c, c), "prob": float(p)}
         for c, p in zip(_CLASS_NAMES, probs)],
        key=lambda r: -r["prob"],
    )
    top = pairs[0]
    return {
        "id": top["id"],
        "display": top["display"],
        "confidence": top["prob"],
        "distribution": pairs,
    }


def class_names() -> list[str]:
    with _LOCK:
        _load()
    return list(_CLASS_NAMES)


def runtime_info() -> dict:
    """Diagnostic helper used by /api/system."""
    with _LOCK:
        _load()
    return {"backend": _RUNTIME.backend, "reason": _RUNTIME.reason,
            "artefact": str(_RUNTIME.artefact) if _RUNTIME.artefact else None}
