# Whole-ship cover photos

## Purpose

- **Photographic Report**: one overwater / whole-ship image per job, vessel name via **OCR**.
- **Not** used in before/after hull grids or species fouling tables.

## How cover vs hull is decided

**Models only** (no pixel/heuristic configuration):

| Signal | Model | Meaning |
|--------|--------|---------|
| `stage.id == not_hull` | Before/after (3-class) | Not an underwater hull inspection shot |
| `species.top == vessel_cover` | Species (11-class) | Whole-ship / cover class |

All 704 uploads run **region + before/after + species**. Cover shots get OCR; hull shots go to region grids.

The UI picks the best vessel name from OCR on **model-selected** cover images (`pick_best_vessel_ocr`).

## Optional reference folder (`F:\ship_image`)

`NAUTICAI_SHIP_COVER_DIR` is only used for **training** extra `vessel_cover` examples — not for runtime routing.

## Training (improve cover detection)

```powershell
cd "D:\test species model\marine_report"
python scripts/ingest_ship_cover_reference.py
python -m marine_report.scripts.train_species_classifier --classes data/species_classes_client.yaml ...
```

Retrain the **before/after** model with `not_hull` negatives from the same ship-image set for better hull vs cover separation at upload time.
