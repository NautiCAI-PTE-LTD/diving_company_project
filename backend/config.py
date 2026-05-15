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
SPECIES = ["algae", "barnacles", "clean_paint", "macroalgae", "mussels"]
SPECIES_DISPLAY = {
    "algae": "Algae", "barnacles": "Barnacles", "clean_paint": "Clean Paint",
    "macroalgae": "Macroalgae", "mussels": "Mussels",
}
STAGES = ["before", "after"]

# Mapping species severity → A/B/C/D scale used in the marine PDF
def severity_from(fouling_pct: float, top_species: str) -> str:
    if top_species == "clean_paint" or fouling_pct < 10:
        return "D"  # Clean
    if fouling_pct < 35:
        return "A"  # Light
    if fouling_pct < 65:
        return "B"  # Moderate
    return "C"      # Heavy
