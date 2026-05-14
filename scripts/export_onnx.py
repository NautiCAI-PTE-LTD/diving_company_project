"""Export every production model to ONNX.

Run this once on a workstation with PyTorch + TensorFlow installed before
shipping the bundle to a Jetson. Produces:

    Models/Ship_classification_v2.onnx
    Models/species_classifier_bundle.onnx
    Models/Before_and_after_v2.onnx

The Jetson then runs ``scripts/build_trt.py`` against these ONNX files to
produce ``.engine`` files used at inference time.

Usage:
    python scripts/export_onnx.py                  # export all
    python scripts/export_onnx.py --only region    # just one
    python scripts/export_onnx.py --opset 17       # override ONNX opset
"""
from __future__ import annotations
from pathlib import Path
import argparse
import logging
import sys

# Allow running from anywhere — add project root to sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import config  # noqa: E402
from backend.inference import region as region_inf  # noqa: E402
from backend.inference import species as species_inf  # noqa: E402

log = logging.getLogger("export_onnx")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s")


def export_region(opset: int = 17) -> Path:
    import torch
    region_inf._load()  # populates _MODEL / _TFM
    model = region_inf._MODEL.cpu().eval()
    out_path = config.SHIP_REGION_CKPT.with_suffix(".onnx")
    dummy = torch.randn(1, 3, 224, 224, dtype=torch.float32)
    log.info("Exporting region (Swin-Tiny) → %s", out_path)
    torch.onnx.export(
        model, dummy, str(out_path),
        input_names=["input"], output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=opset,
        do_constant_folding=True,
    )
    return out_path


def export_species(opset: int = 17) -> Path:
    import torch
    species_inf._load()
    model = species_inf._MODEL.cpu().eval()
    out_path = config.SPECIES_CKPT.with_suffix(".onnx")
    dummy = torch.randn(1, 3, 224, 224, dtype=torch.float32)
    log.info("Exporting species (EffNet-B0) → %s", out_path)
    torch.onnx.export(
        model, dummy, str(out_path),
        input_names=["input"], output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=opset,
        do_constant_folding=True,
    )
    return out_path


def export_before_after(opset: int = 17) -> Path:
    """Use tf2onnx because the model is a Keras file. Requires ``pip install
    tf2onnx`` plus a matching TensorFlow install."""
    try:
        import tensorflow as tf
        import tf2onnx
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "tf2onnx is required to export the Before/After Keras model. "
            "Install with: pip install tf2onnx onnx"
        ) from e

    src = config.BEFORE_AFTER_CKPT
    out_path = src.with_suffix(".onnx")
    log.info("Exporting before/after (Keras EffNetV2-B0) → %s", out_path)
    model = tf.keras.models.load_model(str(src))
    in_shape = model.inputs[0].shape  # (None, H, W, 3)
    h = int(in_shape[1] or 224); w = int(in_shape[2] or 224)
    spec = (tf.TensorSpec((None, h, w, 3), tf.float32, name="input"),)
    tf2onnx.convert.from_keras(model, input_signature=spec, opset=opset,
                               output_path=str(out_path))
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["region", "species", "before_after"],
                        help="Export just one model")
    parser.add_argument("--opset", type=int, default=17,
                        help="ONNX opset (default 17; TensorRT 8.6 supports up to 19)")
    args = parser.parse_args()

    targets = ["region", "species", "before_after"]
    if args.only:
        targets = [args.only]

    out_paths: list[Path] = []
    for t in targets:
        if t == "region":
            out_paths.append(export_region(opset=args.opset))
        elif t == "species":
            out_paths.append(export_species(opset=args.opset))
        elif t == "before_after":
            out_paths.append(export_before_after(opset=args.opset))

    log.info("Done. Files written:")
    for p in out_paths:
        log.info("  %s (%.1f MB)", p, p.stat().st_size / 1e6)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
