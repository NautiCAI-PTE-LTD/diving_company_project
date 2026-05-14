"""Marine fouling-species classifier (EfficientNet-B0, 5 classes).

Backend selection (auto, see ``_runtime.resolve``):
    1. TensorRT engine — ``Models/species_classifier_bundle.engine``
    2. ONNX Runtime   — ``Models/species_classifier_bundle.onnx``
    3. Native PyTorch — ``Models/species_classifier_bundle.pt``
"""
from __future__ import annotations
from threading import Lock
from typing import Optional
import logging

import numpy as np
from PIL import Image

from .. import config
from . import _runtime

log = logging.getLogger("nauticai.species")

_LOCK = Lock()
_RUNTIME: Optional[_runtime.RuntimeChoice] = None
_MODEL = None
_TFM = None
_CLASS_NAMES: list[str] = []
_IMG_SIZE: int = 224


def _load_native_torch() -> tuple:
    import torch
    import timm
    from torchvision import transforms

    ckpt = torch.load(str(config.SPECIES_CKPT), map_location="cpu", weights_only=False)
    meta = ckpt["meta"]
    class_names = list(meta["class_names"])
    img_size = int(meta.get("img_size", 224))
    model = timm.create_model(meta["arch"], pretrained=False,
                              num_classes=meta["num_classes"])
    model.load_state_dict(ckpt["model_state"])
    model.to(config.DEVICE).eval()
    tfm = transforms.Compose([
        transforms.Resize((img_size, img_size)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                             std =[0.229, 0.224, 0.225]),
    ])
    return model, tfm, class_names, img_size


def _read_meta_fallback() -> tuple[list[str], int]:
    try:
        import torch
        ckpt = torch.load(str(config.SPECIES_CKPT), map_location="cpu", weights_only=False)
        meta = ckpt["meta"]
        return list(meta["class_names"]), int(meta.get("img_size", 224))
    except Exception:
        log.warning("Couldn't read meta from %s — using config.SPECIES",
                    config.SPECIES_CKPT)
        return list(config.SPECIES), 224


def _load() -> None:
    global _MODEL, _TFM, _CLASS_NAMES, _RUNTIME, _IMG_SIZE
    if _MODEL is not None:
        return
    _RUNTIME = _runtime.resolve(config.SPECIES_CKPT)
    log.info("Species classifier backend=%s · %s", _RUNTIME.backend, _RUNTIME.reason)

    if _RUNTIME.backend == "trt":
        _MODEL = _runtime.TensorRTEngine(_RUNTIME.artefact)
        _CLASS_NAMES, _IMG_SIZE = _read_meta_fallback()
    elif _RUNTIME.backend == "onnx":
        _MODEL = _runtime.OnnxSession(_RUNTIME.artefact)
        _CLASS_NAMES, _IMG_SIZE = _read_meta_fallback()
    else:
        _MODEL, _TFM, _CLASS_NAMES, _IMG_SIZE = _load_native_torch()


def predict(pil_img: Image.Image) -> dict:
    """Returns {top, top_display, distribution: [{id, display, prob}, ...], fouling_pct}."""
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
        [{"id": c, "display": config.SPECIES_DISPLAY.get(c, c), "prob": float(p)}
         for c, p in zip(_CLASS_NAMES, probs)],
        key=lambda r: -r["prob"],
    )
    top = pairs[0]

    fouling_pct = 0.0
    for p in pairs:
        if p["id"] != "clean_paint":
            fouling_pct += p["prob"]
    fouling_pct = round(fouling_pct * 100.0, 1)

    return {
        "top": top["id"],
        "top_display": top["display"],
        "distribution": pairs,
        "fouling_pct": fouling_pct,
    }


def class_names() -> list[str]:
    with _LOCK:
        _load()
    return list(_CLASS_NAMES)


def runtime_info() -> dict:
    with _LOCK:
        _load()
    return {"backend": _RUNTIME.backend, "reason": _RUNTIME.reason,
            "artefact": str(_RUNTIME.artefact) if _RUNTIME.artefact else None}
