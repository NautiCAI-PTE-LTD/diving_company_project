# Automated vessel naming (raw uploads)

## Default: fully automatic — no client vessel list

When you upload raw photos/videos:

1. **Region + before/after + species models** route each image (hull vs cover).
2. **Cover / nameplate** shots get **EasyOCR** automatically.
3. **Smart pick** chooses the painted vessel name (not `MONROVIA`, not short mis-reads like `VERSTONE` vs `SILVERSTONE`).
4. **Batch clustering** groups the same name across many photos → one **vessel name + cover photo** for the report.

The surveyor does **not** need to type or maintain a vessel directory for this to work.

## API (automation)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/vessels/auto-detect` | `{ image_ids[], pinned_vessel_name? }` → name + cover + confidence |
| POST | `/api/analyze` | Per-image; returns `vessel_ocr` + `vessel_resolution` with `match_kind: auto` |
| GET | `/api/images/{id}/vessel-ocr` | Re-run OCR on cover photo |

Example response:

```json
{
  "display_name": "Silverstone",
  "match_kind": "auto",
  "confidence": 0.92,
  "cover_image_id": "abc123",
  "needs_review": false,
  "candidates": [
    { "name": "Silverstone", "votes": 2, "weight": 4.1, "cover_image_id": "..." }
  ]
}
```

`needs_review: true` when several different vessel names appear in one upload, or OCR confidence is low.

## Optional: company vessel list

`GET/POST /api/vessels` is **optional** — only improves spelling when you already know the fleet. Automation works with an **empty** list.

## Report create

`POST /api/reports` runs auto-detect on all attached `image_ids` and sets `vessel_name` + `vessel_image_id` when empty.

## Frontend

After upload batch completes, the wizard calls **`autoDetectVesselFromUpload()`** (no manual steps).
