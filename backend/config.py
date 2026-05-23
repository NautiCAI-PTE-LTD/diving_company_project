"""Centralised configuration: paths, model files, runtime knobs."""
from __future__ import annotations
from pathlib import Path
import os

# Load backend/.env if it exists, so DATABASE_URL / JWT_SECRET can live there.
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

# Jetson / offline edge: force local SQLite even if .env still has Supabase.
# Usage on the edge box:  export NAUTICAI_USE_SQLITE=1
if os.environ.get("NAUTICAI_USE_SQLITE", "").strip().lower() in ("1", "true", "yes"):
    os.environ["DATABASE_URL"] = ""

# ----- paths -------------------------------------------------------------
BACKEND_DIR  = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
MODELS_DIR   = PROJECT_ROOT / "Models"

STORAGE_DIR  = BACKEND_DIR / "storage"
UPLOADS_DIR  = STORAGE_DIR / "uploads"
REPORTS_DIR  = STORAGE_DIR / "reports"
DB_PATH      = STORAGE_DIR / "nauticai.db"

for d in (STORAGE_DIR, UPLOADS_DIR, REPORTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# PDF layout: "marine" = NautiCAI report (default); "uw" = client BW BIRCH / Synergy template
REPORT_TEMPLATE = os.environ.get("NAUTICAI_REPORT_TEMPLATE", "marine").strip().lower()

# ----- model files -------------------------------------------------------
SHIP_REGION_CKPT  = MODELS_DIR / "Ship_classification_v2.pth"
# Production Before/After classifier. The v2 model is an EfficientNetV2-B0
# fine-tune trained by `train_before_after.py` (~90% test acc on the
# extracted dive photos, vs ~50% for the original MobileNetV2 .h5 which is
# kept around as `Before_and_after.h5.bak` for fallback / comparison).
BEFORE_AFTER_CKPT = MODELS_DIR / "Before_and_after_v2.keras"
SPECIES_CKPT      = MODELS_DIR / "species_classifier_bundle.pt"

# ----- runtime ---------------------------------------------------------
# Auto-detect a CUDA GPU at import time so PyTorch-backed models
# (region, species classifier, EasyOCR) run on the GPU when one is
# present. The env var `NAUTICAI_DEVICE` still wins if set explicitly
# (useful for forcing CPU during debugging or on a shared GPU box).
def _auto_device() -> str:
    explicit = os.environ.get("NAUTICAI_DEVICE", "").strip().lower()
    if explicit in ("cpu", "cuda"):
        return explicit
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


DEVICE          = _auto_device()
OCR_LANGS       = ["en"]
OCR_GPU         = DEVICE == "cuda"
INFERENCE_BATCH = 8
# Downscale 12 MP phone photos before CNNs (models still see 224×224).
INFERENCE_MAX_EDGE = int(os.environ.get("NAUTICAI_INFERENCE_MAX_EDGE", "1280") or 1280)
# OCR keeps more pixels than classifiers (painted names stay readable).
OCR_MAX_EDGE = int(os.environ.get("NAUTICAI_OCR_MAX_EDGE", "2000") or 2000)
# Concurrent /api/analyze on GPU — override with NAUTICAI_ANALYZE_CONCURRENCY.
# l4/a10 profiles default to 4 when using ONNX/TRT (24 GB class cards).
ANALYZE_CONCURRENCY = int(os.environ.get("NAUTICAI_ANALYZE_CONCURRENCY", "0") or 0)


def _auto_gpu_profile() -> str:
    """Best-effort GPU name → profile slug (empty on CPU / unknown)."""
    try:
        import subprocess
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
        )
        name = (out.strip().splitlines() or [""])[0].upper()
        if "L4" in name:
            return "l4"
        if "A10" in name or "A100" in name:
            return "a10"
        if "T4" in name:
            return "t4"
        if "ORIN" in name or "XAVIER" in name:
            return "jetson"
    except Exception:
        pass
    return ""


# Cloud GPU profile: l4 | a10 | t4 | jetson — tunes analyze concurrency.
GPU_PROFILE = os.environ.get("NAUTICAI_GPU_PROFILE", "").strip().lower() or _auto_gpu_profile()

# Photographic Report opener: use the image whose OCR matches the report vessel name
# (same photo as step-1 detection), not a random hull shot.
PHOTO_COVER_MATCH_OCR_NAME = os.environ.get(
    "NAUTICAI_PHOTO_COVER_MATCH_OCR_NAME", "1",
).strip().lower() not in ("0", "false", "no")

# ----- GPU performance knobs --------------------------------------------
# FP16 autocast on CUDA forward passes. Safe for inference (weights stay
# FP32) and gives a big boost on any Tensor-Core GPU (T4, L4, A10, A100,
# RTX 30/40-series). Set NAUTICAI_FP16=0 to force FP32.
USE_FP16 = (
    DEVICE == "cuda"
    and os.environ.get("NAUTICAI_FP16", "1").strip() not in ("0", "false", "no")
)
# TF32 matmuls on Ampere+ (A10/A100/L4/RTX-30/40). Harmless on Turing
# (T4) — PyTorch just ignores it there.
MATMUL_PRECISION = os.environ.get("NAUTICAI_MATMUL", "high")  # high | medium | highest


def _tune_torch_once() -> None:
    """Apply CUDA performance flags at import time.

    Runs unconditionally; no-op on CPU. Idempotent — safe to call from
    multiple places (config import, FastAPI startup, smoke scripts).
    """
    try:
        import torch
        if not torch.cuda.is_available():
            return
        torch.backends.cudnn.benchmark = True          # fastest conv kernels for fixed shapes
        try:
            torch.set_float32_matmul_precision(MATMUL_PRECISION)
        except Exception:
            pass
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
    except Exception:
        pass


_tune_torch_once()


def default_analyze_concurrency(*, region_backend: str, species_backend: str) -> int:
    """How many /api/analyze calls may run models at once."""
    if ANALYZE_CONCURRENCY > 0:
        return ANALYZE_CONCURRENCY
    if DEVICE != "cuda":
        return 2
    onnx_family = region_backend in ("onnx", "trt") and species_backend in ("onnx", "trt")
    if GPU_PROFILE in ("l4", "a10", "a100"):
        return 4 if onnx_family else 2
    if GPU_PROFILE == "t4":
        return 2
    return 2 if onnx_family else 1


# ----- database & auth --------------------------------------------------
# If DATABASE_URL is set (Supabase / generic Postgres), use it. Otherwise the
# local SQLite file under storage/ is used so dev still works out-of-the-box.
DATABASE_URL    = os.environ.get("DATABASE_URL", "").strip()
# JWT signing secret — MUST be overridden in production via env var
JWT_SECRET      = os.environ.get("JWT_SECRET", "change-me-in-production-please")
JWT_ALG         = os.environ.get("JWT_ALG", "HS256")
JWT_EXPIRE_MIN  = int(os.environ.get("JWT_EXPIRE_MIN", "10080") or 10080)  # default 7 days

# ----- region / species class names (mirror the React side EXACTLY) ----
HULL_REGIONS = [
    "Bilege_keels", "Bow", "Cathodic_Protection", "EGCS", "Flat_bottom",
    "Propeller", "Radder", "Rope", "Sea_chest", "Verticle_Slide", "stren",
]
HULL_REGION_DISPLAY = {
    "Bilege_keels": "Bilge Keels",
    "Bow": "Bow",
    "Cathodic_Protection": "Cathodic Protection / Anodes",
    "EGCS": "EGCS Outlets",
    "Flat_bottom": "Flat Bottom",
    "Propeller": "Propeller",
    "Radder": "Rudder",
    "Rope": "Rope Guard",
    "Sea_chest": "Sea Chest Gratings",
    "Verticle_Slide": "Vertical Side (Hull)",
    "stren": "Stern Frame",
}
SPECIES_FALLBACK = [
    "algae", "barnacles", "clean_paint", "macroalgae", "mussels",
]
SPECIES = list(SPECIES_FALLBACK)
SPECIES_VESSEL_COVER_ID = "vessel_cover"
SPECIES_DISPLAY: dict[str, str] = {}
# Whole-ship photos for OCR + Photographic Report cover (negative examples for species/BA).
SHIP_COVER_REFERENCE_DIR = Path(
    os.environ.get("NAUTICAI_SHIP_COVER_DIR", r"F:\ship_image")
)
STAGES = ["before", "after", "not_hull"]

# Temporary species ↔ before/after gating (until dataset retrain).
# Before: never keep clean_paint as top — use fouling classes only.
# After: prefer clean_paint when prob >= min; skip if fouling class is dominant.
SPECIES_STAGE_GATE = os.environ.get("NAUTICAI_SPECIES_STAGE_GATE", "1").strip().lower() in (
    "1", "true", "yes",
)
SPECIES_CLEAN_AFTER_MIN_PROB = float(
    os.environ.get("NAUTICAI_SPECIES_CLEAN_AFTER_MIN_PROB", "0.30") or 0.30
)
SPECIES_AFTER_KEEP_FOULING_MIN = float(
    os.environ.get("NAUTICAI_SPECIES_AFTER_KEEP_FOULING_MIN", "0.72") or 0.72
)

# ----- PDF generation (fast mode on by default for large batches) ----------
PDF_FAST = os.environ.get("NAUTICAI_PDF_FAST", "1").strip().lower() not in (
    "0", "false", "no",
)
# Max photos per before/after grid per region (0 = embed every photo — slow).
PDF_MAX_PHOTOS_PER_STAGE = int(
    os.environ.get(
        "NAUTICAI_PDF_MAX_PHOTOS_PER_STAGE",
        "9" if PDF_FAST else "0",
    ) or 0,
)
# BIRCH template normally builds the PDF twice for TOC page numbers; skip when fast.
PDF_BIRCH_SINGLE_PASS = os.environ.get(
    "NAUTICAI_PDF_BIRCH_SINGLE_PASS",
    "1" if PDF_FAST else "0",
).strip().lower() not in ("0", "false", "no")
PDF_THUMB_WORKERS = max(1, int(os.environ.get("NAUTICAI_PDF_THUMB_WORKERS", "8") or 8))
PDF_THUMB_QUALITY = max(
    50,
    min(95, int(os.environ.get("NAUTICAI_PDF_THUMB_QUALITY", "72" if PDF_FAST else "80") or 80)),
)
PDF_THUMB_CACHE_LIMIT = int(
    os.environ.get("NAUTICAI_PDF_THUMB_CACHE_LIMIT", "4096" if PDF_FAST else "256") or 256,
)


# Mapping species severity → A/B/C/D scale used in the marine PDF
def severity_from(fouling_pct: float, top_species: str) -> str:
    if top_species == "clean_paint" or fouling_pct < 10:
        return "D"  # Clean
    if fouling_pct < 35:
        return "A"  # Light
    if fouling_pct < 65:
        return "B"  # Moderate
    return "C"      # Heavy
