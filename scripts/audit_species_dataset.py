"""Audit species_dataset folders and (optionally) score dive-report photos.

Usage:
    python scripts/audit_species_dataset.py
    python scripts/audit_species_dataset.py --data-root D:\\Ship_shape_prediction\\marine_report\\data\\species_dataset
    python scripts/audit_species_dataset.py --dive-audit
    python scripts/audit_species_dataset.py --dive-audit --dive-dir Report_to_extract_images/extracted/before

Writes:
    species_review/dataset_counts.json
    species_review/dive_audit.csv          (with --dive-audit)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import yaml
except ImportError:
    raise SystemExit("pip install pyyaml")

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}

DEFAULT_DATA_ROOT = Path(r"D:\Ship_shape_prediction\marine_report\data\species_dataset")
DEFAULT_CLASSES = ROOT / "data" / "species_classes.yaml"
REVIEW_DIR = ROOT / "species_review"

DIVE_DIRS = [
    ROOT / "Report_to_extract_images" / "extracted" / "before",
    ROOT / "Report_to_extract_images" / "extracted" / "after",
    ROOT / "backend" / "assets" / "birch_reference" / "extracted",
]


def load_schema(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def collect_by_class(data_root: Path, schema: dict) -> tuple[dict[str, list[Path]], list[str]]:
    warnings: list[str] = []
    id_to_folder: dict[str, str] = {}
    for entry in schema.get("classes") or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        cid = str(entry["id"])
        id_to_folder[cid] = str(entry.get("dataset_folder") or cid)

    by_class: dict[str, list[Path]] = {cid: [] for cid in id_to_folder}
    mapped_folders = set(id_to_folder.values())

    for cid, folder in id_to_folder.items():
        class_dir = data_root / folder
        if not class_dir.is_dir():
            warnings.append(f"Missing folder for {cid}: {class_dir}")
            continue
        for p in class_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in IMG_EXT:
                by_class[cid].append(p)

    for child in sorted(data_root.iterdir()):
        if child.is_dir() and child.name not in mapped_folders and not child.name.startswith("_"):
            warnings.append(f"Unknown top-level folder (not in yaml): {child.name}")

    return by_class, warnings


def write_counts(data_root: Path, by_class: dict[str, list[Path]], warnings: list[str]) -> Path:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out = REVIEW_DIR / "dataset_counts.json"
    payload = {
        "data_root": str(data_root),
        "images_per_class": {k: len(v) for k, v in sorted(by_class.items())},
        "total_images": sum(len(v) for v in by_class.values()),
        "warnings": warnings,
        "notes": [
            "clean_paint should grow with real post-clean dive photos (extracted/after).",
            "Before-cleaning fouled photos belong in algae/barnacles/macroalgae/mussels — not Clean.",
        ],
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def dive_audit(dive_dirs: list[Path]) -> Path:
    os.environ.setdefault("NAUTICAI_BACKEND", "native")
    from PIL import Image

    from backend.inference import species as species_inf

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = REVIEW_DIR / "dive_audit.csv"
    rows: list[dict] = []

    for d in dive_dirs:
        if not d.is_dir():
            print(f"  (skip missing) {d}")
            continue
        for p in sorted(d.iterdir()):
            if not p.is_file() or p.suffix.lower() not in IMG_EXT:
                continue
            try:
                r = species_inf.predict(Image.open(p).convert("RGB"))
            except Exception as e:
                rows.append({
                    "path": str(p),
                    "source_dir": d.name,
                    "error": str(e),
                })
                continue
            dist = r.get("distribution") or []
            top3 = "; ".join(f"{x['id']}:{x['prob']:.3f}" for x in dist[:3])
            rows.append({
                "path": str(p),
                "source_dir": d.name,
                "predicted_top": r["top"],
                "fouling_pct": r["fouling_pct"],
                "top3": top3,
                "likely_mislabel": (
                    "yes" if d.name == "before" and r["top"] == "clean_paint" else
                    "maybe" if r["top"] == "clean_paint" and (r["fouling_pct"] or 0) < 5 else
                    ""
                ),
            })

    fieldnames = ["path", "source_dir", "predicted_top", "fouling_pct", "top3", "likely_mislabel", "error"]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    c = Counter(r.get("predicted_top") for r in rows if "predicted_top" in r)
    mis = sum(1 for r in rows if r.get("likely_mislabel") == "yes")
    print(f"Dive audit: {len(rows)} images -> {out_csv}")
    print("  predictions:", dict(c))
    print(f"  before-folder called clean_paint: {mis}")
    return out_csv


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    ap.add_argument("--classes", type=Path, default=DEFAULT_CLASSES)
    ap.add_argument("--dive-audit", action="store_true", help="Score dive folders with current model")
    ap.add_argument("--dive-dir", type=Path, action="append", default=[], help="Extra folder to audit")
    args = ap.parse_args()

    data_root = args.data_root.resolve()
    if not data_root.is_dir():
        print(f"Dataset root not found: {data_root}")
        print("Set --data-root or copy species_dataset into the project.")
        return 1

    schema = load_schema(args.classes.resolve())
    by_class, warnings = collect_by_class(data_root, schema)
    counts_path = write_counts(data_root, by_class, warnings)

    print(f"Dataset: {data_root}")
    for cid, paths in sorted(by_class.items()):
        print(f"  {cid:14} {len(paths):6}")
    print(f"  TOTAL        {sum(len(v) for v in by_class.values()):6}")
    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"  - {w}")
    print(f"Wrote {counts_path}")

    if args.dive_audit:
        dirs = list(DIVE_DIRS)
        dirs.extend(args.dive_dir)
        dive_audit(dirs)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
