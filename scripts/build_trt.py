"""Build TensorRT engines from ONNX files. Run on the Jetson, not the dev box.

Usage on the Jetson Orin Nano:

    # 1. Make sure JetPack 6.x is installed (CUDA 12 + TensorRT 8.6+)
    # 2. Activate the project's venv: source .venv/bin/activate
    # 3. python scripts/build_trt.py --fp16

This converts every ``Models/*.onnx`` produced by ``export_onnx.py`` into a
matching ``Models/*.engine`` file. The first build is slow (1-5 min per model
because TensorRT searches kernels) — subsequent boots load the cached engine
in <100 ms.

INT8 calibration is NOT included here. Stick with FP16 unless you have a
representative calibration set; the accuracy/speed trade-off on Orin Nano
makes FP16 the practical choice.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import logging
import sys

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "Models"

log = logging.getLogger("build_trt")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s")


def build_engine(onnx_path: Path, fp16: bool = True, workspace_mb: int = 1024) -> Path:
    try:
        import tensorrt as trt
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "TensorRT is not importable. On a Jetson, install JetPack 6.x "
            "(it ships with TensorRT) then `pip install pycuda`."
        ) from e

    logger = trt.Logger(trt.Logger.INFO)
    builder = trt.Builder(logger)
    network = builder.create_network(
        1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
    )
    parser = trt.OnnxParser(network, logger)
    with open(onnx_path, "rb") as f:
        if not parser.parse(f.read()):
            for i in range(parser.num_errors):
                log.error("ONNX parse error: %s", parser.get_error(i))
            raise RuntimeError(f"Failed to parse {onnx_path}")

    cfg = builder.create_builder_config()
    cfg.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, workspace_mb * 1024 * 1024)
    if fp16 and builder.platform_has_fast_fp16:
        cfg.set_flag(trt.BuilderFlag.FP16)
        log.info("FP16 enabled for %s", onnx_path.name)

    # The classifiers run at a fixed 1x3x224x224 today, but make the
    # optimisation profile dynamic on batch axis so we can crank batch up
    # later without rebuilding.
    profile = builder.create_optimization_profile()
    input_tensor = network.get_input(0)
    in_shape = input_tensor.shape           # (-1, C, H, W) or (-1, H, W, C)
    name = input_tensor.name
    if in_shape[0] == -1:
        min_shape = (1,)   + tuple(in_shape[1:])
        opt_shape = (1,)   + tuple(in_shape[1:])
        max_shape = (8,)   + tuple(in_shape[1:])
    else:
        min_shape = opt_shape = max_shape = tuple(in_shape)
    profile.set_shape(name, min_shape, opt_shape, max_shape)
    cfg.add_optimization_profile(profile)

    log.info("Building engine for %s (this may take a few minutes)...", onnx_path.name)
    serialized = builder.build_serialized_network(network, cfg)
    if serialized is None:
        raise RuntimeError(f"TensorRT failed to build engine for {onnx_path}")

    out_path = onnx_path.with_suffix(".engine")
    out_path.write_bytes(serialized)
    log.info("Wrote %s (%.1f MB)", out_path, out_path.stat().st_size / 1e6)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fp16", action="store_true", default=True,
                        help="Build in FP16 (default)")
    parser.add_argument("--fp32", action="store_true",
                        help="Force FP32 — slower, but useful for accuracy checks")
    parser.add_argument("--workspace-mb", type=int, default=1024,
                        help="TensorRT workspace pool in MB (Orin Nano: 1024 is safe)")
    parser.add_argument("--only", help="Build a single ONNX file (path or name)")
    args = parser.parse_args()
    fp16 = args.fp16 and not args.fp32

    if args.only:
        target = Path(args.only)
        if not target.is_absolute():
            target = MODELS_DIR / target
        onnx_files = [target]
    else:
        onnx_files = sorted(MODELS_DIR.glob("*.onnx"))

    if not onnx_files:
        log.error("No ONNX files found in %s — run scripts/export_onnx.py first.", MODELS_DIR)
        return 1

    for p in onnx_files:
        build_engine(p, fp16=fp16, workspace_mb=args.workspace_mb)
    log.info("All engines built. Restart the backend to pick them up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
