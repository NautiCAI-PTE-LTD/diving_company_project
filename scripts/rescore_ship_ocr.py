import csv
from collections import defaultdict
from pathlib import Path

detail = Path(__file__).parent / "output" / "ship_image_ocr_detail.csv"
labels_path = Path(__file__).parent / "output" / "ship_image_labels_inferred.csv"
labels = {r["filename"]: r["expected_vessel"] for r in csv.DictReader(labels_path.open(encoding="utf-8"))}

methods = [
    ("1_raw_top_score", "1_raw_top_score_fleet"),
    ("2_max_confidence", "2_max_confidence_fleet"),
    ("3_longest_line", "3_longest_line_fleet"),
    ("4_smart_pick", "4_smart_pick_fleet"),
    ("5_discovery_resolve", "5_discovery_resolve_fleet"),
    ("6_fleet_any_candidate", "6_fleet_any_candidate_fleet"),
]

rows = list(csv.DictReader(detail.open(encoding="utf-8")))
stats = {m[0]: {"ok": 0, "fleet": 0, "no_np": 0} for m in methods}
per_v = {m[0]: defaultdict(lambda: {"ok": 0, "n": 0}) for m in methods}

for r in rows:
    gt = labels.get(r["file"], "")
    has_line = bool(r.get("any_fleet_in_lines"))
    for mname, col in methods:
        fleet = (r.get(col) or "").strip()
        if fleet:
            stats[mname]["fleet"] += 1
        if not has_line and not fleet:
            stats[mname]["no_np"] += 1
        if gt:
            per_v[mname][gt]["n"] += 1
            if fleet.lower() == gt.lower():
                stats[mname]["ok"] += 1
                per_v[mname][gt]["ok"] += 1

print("=== ACCURACY (camera-prefix ground truth) ===")
for mname, _ in methods:
    s = stats[mname]
    print(f"{mname:28} {s['ok']:3}/75  {100*s['ok']/75:5.1f}%  fleet_id={s['fleet']}  no_nameplate={s['no_np']}")

print("\n=== PER VESSEL — smart_pick ===")
for v in ["Silverstone", "Patris", "Atlanta", "Dalma", "Skiathos", "Wolverine"]:
    d = per_v["4_smart_pick"][v]
    print(f"  {v:12} {d['ok']:2}/{d['n']:2}")

print("\n=== PER VESSEL — fleet_any_candidate ===")
for v in ["Silverstone", "Patris", "Atlanta", "Dalma", "Skiathos", "Wolverine"]:
    d = per_v["6_fleet_any_candidate"][v]
    print(f"  {v:12} {d['ok']:2}/{d['n']:2}")
