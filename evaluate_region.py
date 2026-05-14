"""Evaluate the hull-region classifier on a single-class folder.

Designed for the situation where you have a small folder of one class
(e.g. ``Report_to_extract_images/extracted/Bow``) and want to know:

  * How often does the model predict the correct class (top-1 accuracy)?
  * How often does the correct class appear in top-3?
  * If it's wrong, *which* classes is it confusing the right one with?
  * What's the mean confidence on correct vs wrong calls?

By default it scores via the production wrapper
``backend.inference.region.predict`` (=
``Models/Ship_classification_vby_swin.pth``).

Usage:
    python evaluate_region.py                                  # Bow folder, default
    python evaluate_region.py --folder path/to/folder --class Bow
    python evaluate_region.py --limit 5
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from PIL import Image, UnidentifiedImageError  # noqa: E402

DEFAULT_FOLDER = ROOT / "Report_to_extract_images" / "extracted" / "Bow"
DEFAULT_CLASS  = "Bow"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def list_images(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in IMG_EXTS)


def fmt_pct(num, den): return f"{(100.0*num/den):5.1f}%" if den else "  n/a"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", type=str, default=str(DEFAULT_FOLDER),
                    help="Folder of images (all assumed to be the same true class)")
    ap.add_argument("--class", dest="cls", type=str, default=DEFAULT_CLASS,
                    help="Ground-truth class id for every image in --folder")
    ap.add_argument("--limit", type=int, default=0,
                    help="Score only the first N images (debug).")
    ap.add_argument("--topk", type=int, default=3,
                    help="K for top-K accuracy reporting (default 3).")
    args = ap.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        print(f"!! Folder not found: {folder}")
        return 2

    from backend import config                              # noqa: E402
    from backend.inference import region                    # noqa: E402

    print(f"Model:    {config.SHIP_REGION_CKPT}")
    print(f"Device:   {config.DEVICE}")
    print(f"Folder:   {folder}")
    print(f"GT class: {args.cls!r}")

    print("\nWarming up model ...")
    t0 = time.perf_counter()
    region.predict(Image.new("RGB", (224, 224), (50, 80, 110)))
    warm_ms = (time.perf_counter() - t0) * 1000
    print(f"  warm-up: {warm_ms:.0f} ms")

    classes = region.class_names()
    print(f"  model classes ({len(classes)}): {classes}")
    if args.cls not in classes:
        print(f"!! GT class {args.cls!r} is not in the model's class list")
        return 3
    gt_idx = classes.index(args.cls)
    print(f"  GT class index: {gt_idx}")

    files = list_images(folder)
    if args.limit:
        files = files[: args.limit]
    if not files:
        print("!! No images found.")
        return 4
    print(f"\nScoring {len(files)} images ...")

    rows: list[dict] = []
    top1_hits = 0
    topk_hits = 0
    confused_with = Counter()
    conf_correct: list[float] = []
    conf_wrong:   list[float] = []

    for i, p in enumerate(files, 1):
        try:
            with Image.open(p) as im:
                res = region.predict(im)
        except (UnidentifiedImageError, OSError) as e:
            print(f"  ! could not open {p.name}: {e.__class__.__name__}")
            continue
        # res = {id, display, confidence, distribution: [{id, display, prob}, ...]}
        dist = res["distribution"]
        top1 = dist[0]["id"]
        topk_ids = [d["id"] for d in dist[: args.topk]]
        gt_prob = next((d["prob"] for d in dist if d["id"] == args.cls), 0.0)

        is_top1 = (top1 == args.cls)
        is_topk = (args.cls in topk_ids)
        if is_top1:
            top1_hits += 1
            conf_correct.append(res["confidence"])
        else:
            confused_with[top1] += 1
            conf_wrong.append(res["confidence"])
        if is_topk:
            topk_hits += 1

        rows.append({
            "image": p.name,
            "top1_pred": top1,
            "top1_conf": round(res["confidence"], 4),
            "gt_in_top3": int(is_topk) if args.topk == 3 else "",
            "gt_rank": next((rank + 1 for rank, d in enumerate(dist)
                             if d["id"] == args.cls), -1),
            "gt_prob": round(gt_prob, 4),
            "top3": " > ".join(f"{d['id']}:{d['prob']:.2f}" for d in dist[:3]),
        })
        print(f"  [{i:2d}/{len(files)}] {p.name[:55]:55s}  "
              f"top1={top1:<22s} conf={res['confidence']:.2f}  "
              f"gt_rank={rows[-1]['gt_rank']:2d}  gt_prob={gt_prob:.2f}")

    n = len(rows)
    print("\n=========== SUMMARY ===========")
    print(f"  scored             : {n}")
    print(f"  top-1 accuracy     : {fmt_pct(top1_hits, n)}   ({top1_hits}/{n})")
    print(f"  top-{args.topk} accuracy     : {fmt_pct(topk_hits, n)}   ({topk_hits}/{n})")
    if conf_correct:
        print(f"  mean conf (correct): {sum(conf_correct)/len(conf_correct):.3f}")
    if conf_wrong:
        print(f"  mean conf (wrong)  : {sum(conf_wrong)/len(conf_wrong):.3f}")

    if confused_with:
        print("\n  most-confused-with (when wrong):")
        for cls, cnt in confused_with.most_common():
            print(f"     {cls:<22s} x {cnt}")

    out_path = ROOT / "eval_region_predictions.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"\nWrote: {out_path}   ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
