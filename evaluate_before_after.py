"""Evaluate a Before/After classifier against the labelled extracted folders.

Walks every image under
    Report_to_extract_images/extracted/before/   (ground-truth = "before")
    Report_to_extract_images/extracted/after/    (ground-truth = "after")

By default it scores the *production* model loaded by
``backend.inference.before_after.predict`` (= ``Models/Before_and_after.h5``).
Pass ``--model Models/Before_and_after_v2.keras`` to score the new
EfficientNetV2-B0 model produced by ``train_before_after.py`` instead.

Reports:
    * per-folder counts + how the model classified them
    * 2x2 confusion matrix + accuracy + per-class precision/recall
    * mean confidence per (true, predicted) cell
    * "flip check" -- accuracy under the OPPOSITE convention

Outputs written next to the script:
    eval_before_after_predictions.csv   -- one row per image
    eval_before_after_mismatches.csv    -- rows where model != ground-truth

Usage:
    python evaluate_before_after.py
    python evaluate_before_after.py --model Models/Before_and_after_v2.keras
    python evaluate_before_after.py --invert        # force NAUTICAI_BA_INVERT=1 mapping (v1 only)
    python evaluate_before_after.py --limit 50      # quick smoke run
    python evaluate_before_after.py --workers 4     # parallel inference
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Make `python evaluate_before_after.py` find the `backend` package.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Quiet TF before it is imported by the backend module.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from PIL import Image, UnidentifiedImageError  # noqa: E402

EXTRACTED = ROOT / "Report_to_extract_images" / "extracted"
FOLDERS = {
    "before": EXTRACTED / "before",
    "after":  EXTRACTED / "after",
}
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


# ----------------------------------------------------------------- helpers ----
def list_images(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in IMG_EXTS)


def predict_one(path: Path, predict_fn) -> tuple[str, float, str | None]:
    """Return (pred_label, confidence, error)."""
    try:
        with Image.open(path) as im:
            res = predict_fn(im)
        return str(res["id"]), float(res["confidence"]), None
    except (UnidentifiedImageError, OSError) as e:
        return "error", 0.0, f"open: {e.__class__.__name__}"
    except Exception as e:  # model error, etc.
        return "error", 0.0, f"{e.__class__.__name__}: {e}"


def make_v2_predictor(model_path: Path):
    """Return a predict(pil_img)->{id,confidence} callable for the new
    EfficientNetV2-B0 ``.keras`` model produced by ``train_before_after.py``.

    The model expects raw [0,255] RGB float32 of shape (224,224,3); it
    handles its own normalisation internally (include_preprocessing=True).
    Sigmoid output: high -> 'after'. ``NAUTICAI_BA_INVERT=1`` flips it.
    """
    import numpy as np
    import tensorflow as tf

    model = tf.keras.models.load_model(str(model_path))
    # Pull img size from the model's input shape so this works for 224 / 240 / etc.
    in_shape = model.inputs[0].shape  # (None, H, W, 3)
    h, w = int(in_shape[1] or 224), int(in_shape[2] or 224)

    invert = os.environ.get("NAUTICAI_BA_INVERT", "0") == "1"

    def predict(pil_img):
        img = pil_img.convert("RGB").resize((w, h))
        arr = np.expand_dims(np.array(img, dtype=np.float32), 0)
        p = float(model.predict(arr, verbose=0)[0, 0])
        if invert:
            p = 1.0 - p
        if p >= 0.5:
            return {"id": "after",  "confidence": p}
        return {"id": "before", "confidence": 1.0 - p}

    return predict


def fmt_pct(num: int, den: int) -> str:
    return f"{(100.0*num/den):5.1f}%" if den else "  n/a"


# --------------------------------------------------------------------- main ----
def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate a Before/After classifier on extracted folders")
    ap.add_argument("--model", type=str, default="",
                    help="Path to a .keras model (the new v2). If omitted, the "
                         "shipped Models/Before_and_after.h5 (production) is used.")
    ap.add_argument("--invert", action="store_true",
                    help="Force NAUTICAI_BA_INVERT=1 (high sigmoid -> 'before')")
    ap.add_argument("--limit", type=int, default=0,
                    help="Only score the first N images per folder (debug).")
    ap.add_argument("--workers", type=int, default=1,
                    help="Parallel workers (TF model has its own lock; 1-2 is usually enough).")
    args = ap.parse_args()

    if args.invert:
        os.environ["NAUTICAI_BA_INVERT"] = "1"
        print("NAUTICAI_BA_INVERT=1  (using inverted convention)")

    # Pick the predictor.
    if args.model:
        model_path = Path(args.model)
        if not model_path.is_absolute():
            model_path = ROOT / model_path
        if not model_path.exists():
            print(f"!! Model not found: {model_path}")
            return 2
        print(f"Model:    {model_path}  (custom .keras)")
        predict_fn = make_v2_predictor(model_path)
    else:
        # Use the production wrapper around Models/Before_and_after.h5
        from backend import config                          # noqa: E402
        from backend.inference import before_after          # noqa: E402
        print(f"Model:    {config.BEFORE_AFTER_CKPT}")
        print(f"Device:   {config.DEVICE}")
        predict_fn = before_after.predict
    print(f"Invert:   {os.environ.get('NAUTICAI_BA_INVERT','0')}")
    for label, folder in FOLDERS.items():
        if not folder.exists():
            print(f"!! Missing folder: {folder}")
            return 2

    # Warm the model once before timing.
    print("\nWarming up model ...")
    t0 = time.perf_counter()
    predict_fn(Image.new("RGB", (224, 224), (50, 80, 110)))
    print(f"  warm-up: {(time.perf_counter()-t0)*1000:.0f} ms")

    # Collect work.
    work: list[tuple[str, Path]] = []
    counts_per_folder: dict[str, int] = {}
    for label, folder in FOLDERS.items():
        files = list_images(folder)
        if args.limit:
            files = files[: args.limit]
        counts_per_folder[label] = len(files)
        for p in files:
            work.append((label, p))
    total = len(work)
    print(f"\nScoring {total} images "
          + " | ".join(f"{k}={v}" for k, v in counts_per_folder.items()))

    rows: list[dict] = []
    t0 = time.perf_counter()

    def _job(item):
        gt, p = item
        pred, conf, err = predict_one(p, predict_fn)
        return {"gt": gt, "path": str(p), "pred": pred,
                "confidence": round(conf, 4), "error": err or ""}

    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for i, r in enumerate(pool.map(_job, work), 1):
                rows.append(r)
                if i % 50 == 0 or i == total:
                    print(f"  scored {i}/{total}")
    else:
        for i, item in enumerate(work, 1):
            rows.append(_job(item))
            if i % 50 == 0 or i == total:
                print(f"  scored {i}/{total}")

    elapsed = time.perf_counter() - t0
    print(f"\nDone in {elapsed:.1f}s  ({elapsed/max(total,1)*1000:.0f} ms/img)")

    # Confusion matrix (ignoring errors).
    cm = {("before","before"):0, ("before","after"):0,
          ("after","before"):0,  ("after","after"):0}
    conf_sums = {k: 0.0 for k in cm}
    errors: list[dict] = []
    for r in rows:
        if r["pred"] == "error":
            errors.append(r); continue
        key = (r["gt"], r["pred"])
        cm[key] += 1
        conf_sums[key] += r["confidence"]

    correct = cm[("before","before")] + cm[("after","after")]
    scored  = sum(cm.values())
    flipped = cm[("before","after")] + cm[("after","before")]

    def avg(key):
        n = cm[key]
        return (conf_sums[key]/n) if n else float("nan")

    print("\n========= CONFUSION MATRIX =========")
    print("                    pred=before    pred=after")
    print(f"   gt=before   {cm[('before','before')]:8d}        {cm[('before','after')]:8d}")
    print(f"   gt=after    {cm[('after','before')]:8d}        {cm[('after','after')]:8d}")
    print()
    print(f"   accuracy        : {fmt_pct(correct, scored)}   "
          f"({correct}/{scored})")
    print(f"   accuracy if FLIPPED labels: {fmt_pct(flipped, scored)}   "
          f"({flipped}/{scored})")
    if scored:
        if flipped > correct:
            print("\n   >> The model's class names look INVERTED for your folders.")
            print("      Re-run with `--invert`  (or set env NAUTICAI_BA_INVERT=1).")
        else:
            print("\n   >> Model class names match the folder labels.")

    # Per-class precision/recall.
    def safe_div(a, b): return (a/b) if b else float("nan")
    p_before = safe_div(cm[("before","before")],
                        cm[("before","before")] + cm[("after","before")])
    r_before = safe_div(cm[("before","before")],
                        cm[("before","before")] + cm[("before","after")])
    p_after  = safe_div(cm[("after","after")],
                        cm[("after","after")] + cm[("before","after")])
    r_after  = safe_div(cm[("after","after")],
                        cm[("after","after")] + cm[("after","before")])
    print()
    print(f"   precision before={p_before*100:5.1f}%   recall before={r_before*100:5.1f}%")
    print(f"   precision after ={p_after *100:5.1f}%   recall after ={r_after *100:5.1f}%")

    print("\n   mean confidence per (true, predicted) cell:")
    for k in (("before","before"),("before","after"),
              ("after","before"),("after","after")):
        print(f"     gt={k[0]:<6s} pred={k[1]:<6s}  n={cm[k]:4d}  conf={avg(k):.3f}")

    if errors:
        print(f"\n   skipped (load/predict errors): {len(errors)}")
        for r in errors[:5]:
            print(f"     {r['path']}  -- {r['error']}")
        if len(errors) > 5:
            print(f"     ... and {len(errors)-5} more")

    # Per-folder breakdown.
    print("\nPer-folder breakdown of model predictions:")
    for label in ("before", "after"):
        n = counts_per_folder[label]
        n_b = sum(1 for r in rows if r["gt"]==label and r["pred"]=="before")
        n_a = sum(1 for r in rows if r["gt"]==label and r["pred"]=="after")
        n_e = sum(1 for r in rows if r["gt"]==label and r["pred"]=="error")
        print(f"  extracted/{label:<6s} ({n:4d} imgs):  "
              f"before={n_b:4d}  after={n_a:4d}  errors={n_e:3d}")

    # CSV outputs.
    out_pred = ROOT / "eval_before_after_predictions.csv"
    out_miss = ROOT / "eval_before_after_mismatches.csv"
    fields = ["gt", "pred", "confidence", "path", "error"]
    with out_pred.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    miss = [r for r in rows
            if r["pred"] in ("before","after") and r["pred"] != r["gt"]]
    with out_miss.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(miss)
    print(f"\nWrote: {out_pred.name}   ({len(rows)} rows)")
    print(f"Wrote: {out_miss.name}   ({len(miss)} mismatches)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
