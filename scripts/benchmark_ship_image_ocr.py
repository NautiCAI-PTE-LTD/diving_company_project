"""
Benchmark vessel-name OCR on F:\\ship_image (mixed fleet photos).

Compares pick strategies on the same EasyOCR raw output, then maps to a
known fleet list via fuzzy matching.

Ground truth (optional): if images are in survey order, assumes 6 consecutive
blocks map to the vessel order you provide. Override with --labels-csv.

Usage:
  python scripts/benchmark_ship_image_ocr.py
  python scripts/benchmark_ship_image_ocr.py --limit 10
"""
from __future__ import annotations

import argparse
import csv
import difflib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image

SHIP_DIR = Path(r"F:\ship_image")
OUT_DIR = ROOT / "scripts" / "output"
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}

# User-provided fleet (survey order for block-based pseudo-GT)
FLEET_ORDER = [
    "Silverstone",
    "Patris",
    "Atlanta",
    "Dalma",
    "Skiathos",
    "Wolverine",
]
FLEET_NORM = {v.upper().replace(" ", ""): v for v in FLEET_ORDER}


def norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (s or "").upper())


def fuzzy_fleet(text: str, min_ratio: float = 0.72) -> str | None:
    t = norm(text)
    if not t or len(t) < 4:
        return None
    best_name, best_r = None, 0.0
    for key, display in FLEET_NORM.items():
        if key in t or t in key:
            return display
        r = difflib.SequenceMatcher(None, t, key).ratio()
        if r > best_r:
            best_r, best_name = r, display
    if best_r >= min_ratio:
        return best_name
    return None


def _discovery_pick(cands: list[dict], resolver) -> tuple[str, float]:
    if not cands:
        return "", 0.0
    payload = resolver(
        [{"text": x["text"], "confidence": x["confidence"]} for x in cands],
        image_id="x",
    )
    return payload.get("best_guess", "") or "", float(payload.get("best_confidence") or 0)


def _pick_line(cands: list[dict], picker) -> tuple[str, float]:
    if not cands:
        return "", 0.0
    b = picker(cands) or {}
    return str(b.get("text", "") or ""), float(b.get("confidence", 0) or 0)


def method_raw_top(cands: list[dict]) -> tuple[str, float]:
    if not cands:
        return "", 0.0
    c = cands[0]
    return c["text"], float(c["confidence"])


def method_max_conf(cands: list[dict]) -> tuple[str, float]:
    if not cands:
        return "", 0.0
    c = max(cands, key=lambda x: x["confidence"])
    return c["text"], float(c["confidence"])


def method_longest(cands: list[dict]) -> tuple[str, float]:
    pool = [c for c in cands if len(norm(c["text"])) >= 4]
    if not pool:
        return "", 0.0
    c = max(pool, key=lambda x: len(x["text"]))
    return c["text"], float(c["confidence"])


def block_labels(n: int, vessels: list[str]) -> list[str]:
    """Equal-ish blocks in sorted filename order."""
    per = n // len(vessels)
    rem = n % len(vessels)
    labels: list[str] = []
    idx = 0
    for i, v in enumerate(vessels):
        size = per + (1 if i < rem else 0)
        labels.extend([v] * size)
        idx += size
    while len(labels) < n:
        labels.append(vessels[-1])
    return labels[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=SHIP_DIR)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--labels-csv", type=Path, default=None,
                    help="CSV: filename,expected_vessel")
    args = ap.parse_args()

    from backend.inference import ocr as ocr_mod
    from backend.inference.ocr import _pick_vessel_name_line
    from backend.services.vessel_discovery import (
        _resolve_ocr_picks,
        ocr_guess_score,
        vessel_ocr_from_candidate_list,
    )

    paths = sorted(
        p for p in args.dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMG_EXT
    )
    if args.limit:
        paths = paths[: args.limit]
    if not paths:
        print("No images in", args.dir)
        return 1

    gt_by_file: dict[str, str] = {}
    if args.labels_csv and args.labels_csv.exists():
        with args.labels_csv.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                gt_by_file[row["filename"].strip()] = row["expected_vessel"].strip()
    else:
        bl = block_labels(len(paths), FLEET_ORDER)
        for p, lab in zip(paths, bl):
            gt_by_file[p.name] = lab

    methods = {
        "1_raw_top_score": method_raw_top,
        "2_max_confidence": method_max_conf,
        "3_longest_line": method_longest,
        "4_smart_pick": lambda c: _pick_line(c, _pick_vessel_name_line),
        "5_discovery_resolve": lambda c: _discovery_pick(c, vessel_ocr_from_candidate_list),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    detail_path = OUT_DIR / "ship_image_ocr_detail.csv"
    summary_path = OUT_DIR / "ship_image_ocr_summary.csv"

    rows_out: list[dict] = []
    stats: dict[str, dict] = defaultdict(lambda: {
        "correct": 0, "fleet_hit": 0, "any_line_hit": 0, "no_text": 0, "total": 0,
    })

    print(f"Processing {len(paths)} images from {args.dir} ...")
    for i, path in enumerate(paths, 1):
        gt = gt_by_file.get(path.name, "")
        print(f"  [{i}/{len(paths)}] {path.name} (expected: {gt})", flush=True)
        try:
            pil = Image.open(path).convert("RGB")
            payload = ocr_mod.extract(pil)
        except Exception as e:
            print(f"    OCR failed: {e}")
            for m in methods:
                stats[m]["total"] += 1
                stats[m]["no_text"] += 1
            rows_out.append({
                "file": path.name,
                "expected": gt,
                "error": str(e),
            })
            continue

        cands = payload.get("candidates") or []
        all_texts = [c["text"] for c in cands]
        any_fleet = set()
        for t in all_texts:
            f = fuzzy_fleet(t)
            if f:
                any_fleet.add(f)

        row = {
            "file": path.name,
            "expected": gt,
            "all_ocr_lines": " | ".join(all_texts[:12]),
            "any_fleet_in_lines": ",".join(sorted(any_fleet)) if any_fleet else "",
        }

        for mname, fn in methods.items():
            raw, conf = fn(cands)
            fleet = fuzzy_fleet(raw) or ""
            ok = fleet.lower() == gt.lower() if fleet and gt else False
            stats[mname]["total"] += 1
            if not raw:
                stats[mname]["no_text"] += 1
            if fleet:
                stats[mname]["fleet_hit"] += 1
            if any_fleet:
                stats[mname]["any_line_hit"] += 1
            if ok:
                stats[mname]["correct"] += 1
            row[f"{mname}_raw"] = raw
            row[f"{mname}_fleet"] = fleet
            row[f"{mname}_ok"] = ok

        # Bonus: fleet from ANY candidate line (best quality among fleet matches)
        best_any = ""
        best_q = 0.0
        for c in cands:
            f = fuzzy_fleet(c["text"])
            if not f:
                continue
            q = ocr_guess_score(c["text"], c["confidence"])
            if q > best_q:
                best_q, best_any = q, f
        m6 = "6_fleet_any_candidate"
        ok6 = best_any.lower() == gt.lower() if best_any and gt else False
        stats[m6]["total"] += 1
        if best_any:
            stats[m6]["fleet_hit"] += 1
        if any_fleet:
            stats[m6]["any_line_hit"] += 1
        if ok6:
            stats[m6]["correct"] += 1
        row[f"{m6}_fleet"] = best_any
        row[f"{m6}_ok"] = ok6

        rows_out.append(row)

    # Write detail CSV
    if rows_out:
        fields = sorted({k for r in rows_out for k in r})
        with detail_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows_out)

    # Summary
    summary_rows = []
    print("\n=== METHOD COMPARISON (fleet fuzzy match vs expected) ===")
    print(f"{'Method':<28} {'Correct':>8} {'Fleet':>8} {'AnyLine':>8} {'Empty':>6} {'Acc%':>7}")
    for mname in sorted(stats.keys()):
        s = stats[mname]
        t = s["total"] or 1
        acc = 100.0 * s["correct"] / t
        summary_rows.append({
            "method": mname,
            "correct": s["correct"],
            "fleet_mapped": s["fleet_hit"],
            "any_line_had_fleet": s["any_line_hit"],
            "no_text": s["no_text"],
            "total": s["total"],
            "accuracy_pct": round(acc, 1),
        })
        print(f"{mname:<28} {s['correct']:>8} {s['fleet_hit']:>8} {s['any_line_hit']:>8} {s['no_text']:>6} {acc:>6.1f}%")

    with summary_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=summary_rows[0].keys())
        w.writeheader()
        w.writerows(summary_rows)

    # Per-vessel breakdown for best method
    best_m = max(summary_rows, key=lambda r: r["correct"])
    print(f"\nBest method by correct count: {best_m['method']} ({best_m['accuracy_pct']}%)")
    print(f"\nDetail CSV: {detail_path}")
    print(f"Summary CSV: {summary_path}")
    if not args.labels_csv:
        print("\nNote: Expected vessel per file assumed from filename order in 6 blocks:")
        for v, n in zip(FLEET_ORDER, _block_sizes(len(paths), len(FLEET_ORDER))):
            print(f"  {v}: {n} images")
        print("Provide --labels-csv filename,expected_vessel for exact ground truth.")
    return 0


def _block_sizes(n: int, k: int) -> list[int]:
    per, rem = divmod(n, k)
    return [per + (1 if i < rem else 0) for i in range(k)]


if __name__ == "__main__":
    raise SystemExit(main())
