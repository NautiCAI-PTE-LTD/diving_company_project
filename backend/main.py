"""NautiCAI FastAPI backend — multi-tenant.

Auth
----
POST /api/auth/register          public, creates a Company + owner User
POST /api/auth/login             public, returns JWT
GET  /api/auth/me                bearer, returns current user + company

Everything else requires `Authorization: Bearer <jwt>` and is scoped to the
calling user's company.
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict
import logging
import os
import uuid
import io

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image as PILImage

from . import config
from . import auth as auth_svc
from .db import init_db, db_session, Report, Image as ImageRow, Company, User, Client, Vessel
from .schemas import (
    VesselInfo, ReportCreate, ReportPatch, ReportRow,
    StatsResponse, SettingsModel,
    RegisterPayload, LoginPayload, AuthResponse, UserOut,
    ClientCreate, ClientRow,
    VesselCreate, VesselRow, VesselSuggestRequest, VesselSuggestResponse,
    CoverAlternatesResponse, CoverAlternateRow,
)
from .services import storage as storage_svc
from .services import analyze as analyze_svc
from .services import cluster as cluster_svc
from . import config as app_config
from .services import pdf_report as pdf_report_marine
from .services import pdf_report_uw
from .services import video as video_svc
from .services import vessel_discovery as vessel_disc
from .services import vessel_registry as vessel_reg
from .services import vessel_auto as vessel_auto_svc
from .inference import ocr as ocr_inference

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s")
log = logging.getLogger("nauticai.api")

app = FastAPI(title="NautiCAI API", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)


_WARMUP_STATE = {"status": "pending"}     # pending | warming | ready | failed


def _tune_torch() -> None:
    """Enable Tensor-Core friendly knobs on CUDA. No-op on CPU or
    unsupported hardware. Called once before warmup."""
    try:
        import torch
        if torch.cuda.is_available():
            # Same-shape inputs (224x224) → cuDNN can pick the fastest kernel
            torch.backends.cudnn.benchmark = True
            # TF32 matmul on Ampere+ (L4/A10/A100/RTX-30/40); ignored on T4
            try:
                torch.set_float32_matmul_precision(config.MATMUL_PRECISION)
                torch.backends.cuda.matmul.allow_tf32 = True
                torch.backends.cudnn.allow_tf32 = True
            except Exception:
                pass
            log.info("Torch tuned · cudnn.benchmark=on  fp16=%s  matmul=%s",
                     config.USE_FP16, config.MATMUL_PRECISION)
    except Exception:
        log.exception("torch tuning failed (continuing)")


def _warmup_models() -> None:
    """Pre-load the three vision models in a background thread so the
    first user request doesn't pay the ~5-15 s cold-start tax.
    """
    _WARMUP_STATE["status"] = "warming"
    try:
        from .inference import region as r_, before_after as b_, species as s_
        from .inference import ocr as ocr_
        # touch each model's lazy loader
        r_.class_names()
        from . import species_registry as species_reg
        species_reg.sync_config()
        s_.class_names()
        log.info("Species classes: %s", ", ".join(species_reg.load_class_names()))
        from PIL import Image as _PI
        dummy = _PI.new("RGB", (224, 224), (0, 0, 0))
        b_.predict(dummy)
        r_.predict(dummy)
        s_.predict(dummy)
        try:
            ocr_._load()
        except Exception:
            log.debug("OCR warmup skipped", exc_info=True)
        _WARMUP_STATE["status"] = "ready"
        log.info("Models warmed up · device=%s", config.DEVICE)
    except Exception as e:
        _WARMUP_STATE["status"] = "failed"
        _WARMUP_STATE["error"] = str(e)
        log.exception("Model warmup failed")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    try:
        from . import species_registry as species_reg
        species_reg.sync_config()
    except Exception:
        log.debug("species registry sync skipped", exc_info=True)
    log.info("NautiCAI backend ready · models dir = %s · device = %s",
              config.MODELS_DIR, config.DEVICE)
    # CUDA context must exist on the main thread before TRT engines load in the
    # warmup thread (pycuda + autoinit in a daemon thread aborts on exit).
    _tune_torch()
    try:
        from .inference import _runtime as rt_
        rt_.init_trt_cuda()
    except Exception:
        log.debug("TRT CUDA init skipped (no pycuda / CPU-only)", exc_info=True)
    # Warm models on a background thread so /docs / /health stay snappy.
    import threading
    threading.Thread(target=_warmup_models,
                     daemon=True, name="nauticai-warmup").start()


# =============================================================================
# Helpers
# =============================================================================
def _row_to_image(row: ImageRow) -> dict:
    return {
        "id": row.id,
        "filename": row.filename,
        "url": f"/api/images/{row.id}/file",
        "region": row.region or "",
        "region_display": config.HULL_REGION_DISPLAY.get(row.region or "", row.region or ""),
        "stage": row.stage or "",
        "species_top": row.species_top or "",
        "fouling_pct": row.fouling_pct or 0.0,
        "severity": row.severity or "A",
        "width": row.width or 0,
        "height": row.height or 0,
    }


def _row_to_report(rep: Report, image_count: Optional[int] = None) -> dict:
    if image_count is None:
        image_count = len(rep.images)
    return {
        "id": rep.id,
        "vesselName": rep.vessel_name,
        "vesselType": rep.vessel_type,
        "jobNo": rep.job_no,
        "status": rep.status,
        "severity": rep.severity,
        "avg_fouling": rep.avg_fouling,
        "images": image_count,
        "pdf_url": f"/api/reports/{rep.id}/pdf" if rep.pdf_path else None,
        "createdAt": rep.created_at,
        "updatedAt": rep.updated_at,
    }


def _vessel_to_db(rep: Report, v: VesselInfo) -> None:
    rep.vessel_name      = v.vesselName
    rep.vessel_type      = v.vesselType
    rep.vessel_class     = v.vesselClass
    rep.job_no           = v.jobNo
    rep.job_scope        = v.jobScope
    rep.loa              = v.loa
    rep.draft            = v.draft
    rep.location         = v.location
    rep.dive_date        = v.diveDate
    rep.weather          = v.weather
    rep.sea              = v.sea
    rep.visibility       = v.visibility
    rep.tide             = v.tide
    rep.captain          = v.captain
    rep.dive_supervisor  = v.diveSupervisor
    rep.divers           = v.divers
    rep.boat_captain     = v.boatCaptain
    rep.notes            = v.notes
    # Persist client / team / crews / client_reps through the JSON `extra`
    # column. The reports table has flat columns for legacy single-team
    # fields; everything multi-tenant-or-multi-crew goes into `extra`.
    extra = dict(v.extra or {})
    if v.client is not None:
        extra["client"] = v.client.dict() if hasattr(v.client, "dict") else dict(v.client)
    if v.client_reps:
        extra["client_reps"] = [
            r.dict() if hasattr(r, "dict") else dict(r) for r in v.client_reps
        ]
    if v.team:
        extra["team"] = [m.dict() if hasattr(m, "dict") else dict(m) for m in v.team]
    if v.crews:
        extra["crews"] = [
            c.dict() if hasattr(c, "dict") else dict(c) for c in v.crews
        ]
    rep.extra = extra


def _db_to_vessel(rep: Report) -> VesselInfo:
    extra = dict(rep.extra or {})
    client_raw       = extra.pop("client",       None) or {}
    client_reps_raw  = extra.pop("client_reps",  None) or []
    team_raw         = extra.pop("team",         None) or []
    crews_raw        = extra.pop("crews",        None) or []
    return VesselInfo(
        vesselName=rep.vessel_name, vesselType=rep.vessel_type,
        vesselClass=rep.vessel_class, jobNo=rep.job_no, jobScope=rep.job_scope,
        loa=rep.loa, draft=rep.draft, location=rep.location, diveDate=rep.dive_date,
        weather=rep.weather, sea=rep.sea, visibility=rep.visibility, tide=rep.tide,
        captain=rep.captain, diveSupervisor=rep.dive_supervisor,
        divers=rep.divers, boatCaptain=rep.boat_captain,
        notes=rep.notes,
        client=client_raw,
        client_reps=client_reps_raw,
        team=team_raw,
        crews=crews_raw,
        extra=extra,
    )


def _company_to_settings(c: Company) -> SettingsModel:
    has_logo = bool(c.logo_path and Path(c.logo_path).exists())
    return SettingsModel(
        company_name=c.name,
        company_tagline=c.tagline or "",
        company_address=c.address or "",
        company_phone=c.phone or "",
        company_email=c.email or "",
        company_website=c.website or "",
        report_footer=c.report_footer or "Powered by NautiCAI",
        country=c.country or "",
        registration_number=c.registration_number or "",
        tax_number=c.tax_number or "",
        class_approvals=list(c.class_approvals or []),
        diving_certifications=c.diving_certifications or "",
        insurance=c.insurance or "",
        report_prefix=c.report_prefix or "NAUTICAI-REP",
        established_year=c.established_year or "",
        has_logo=has_logo,
        logo_url=f"/api/settings/logo?cid={c.id}" if has_logo else None,
        updated_at=c.updated_at,
    )


def _user_to_out(u: User) -> UserOut:
    return UserOut(
        id=u.id, email=u.email, full_name=u.full_name or "",
        role=u.role or "owner", company_id=u.company_id,
        created_at=u.created_at,
    )


def _company_logo_dest(company_id: str, suffix: str) -> Path:
    suffix = suffix.lower() if suffix.startswith(".") else ".png"
    if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
        suffix = ".png"
    return config.STORAGE_DIR / f"logo_{company_id}{suffix}"


# =============================================================================
# Health / Meta
# =============================================================================
@app.get("/api/health")
def health():
    return {"ok": True, "ts": datetime.utcnow().isoformat(),
            "db": "postgres" if config.DATABASE_URL else "sqlite"}


@app.get("/api/system")
def system_info():
    """Runtime info for the UI status badge: CPU vs GPU, model warm-up
    state, optional GPU name + memory."""
    info: Dict[str, Any] = {
        "device":   config.DEVICE,
        "warmup":   _WARMUP_STATE["status"],
        "ocr_gpu":  config.OCR_GPU,
        "fp16":     config.USE_FP16,
        "matmul":   config.MATMUL_PRECISION,
        "inference_max_edge": config.INFERENCE_MAX_EDGE,
        "analyze_concurrency": _default_analyze_concurrency(),
        "pdf_fast": app_config.PDF_FAST,
        "pdf_max_photos_per_stage": app_config.PDF_MAX_PHOTOS_PER_STAGE,
    }
    try:
        import torch
        info["cuda_available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            i = 0
            info["gpu_name"]      = torch.cuda.get_device_name(i)
            free, total = torch.cuda.mem_get_info(i)
            info["gpu_mem_total"] = int(total)
            info["gpu_mem_free"]  = int(free)
    except Exception:
        info["cuda_available"] = False

    # Per-model runtime backend (trt / onnx / native) — only meaningful once
    # the model has been loaded, so guard everything.
    backends: Dict[str, Any] = {}
    try:
        from .inference import region as region_inf
        backends["region"] = region_inf.runtime_info()
    except Exception as e:
        backends["region"] = {"backend": "unknown", "reason": str(e)[:120]}
    try:
        from .inference import species as species_inf
        backends["species"] = species_inf.runtime_info()
    except Exception as e:
        backends["species"] = {"backend": "unknown", "reason": str(e)[:120]}
    try:
        from .inference import before_after as ba_inf
        backends["before_after"] = ba_inf.runtime_info()
    except Exception as e:
        backends["before_after"] = {"backend": "unknown", "reason": str(e)[:120]}
    info["model_backends"] = backends
    return info


@app.get("/api/meta")
def meta():
    return {
        "regions": [
            {"id": r, "display": config.HULL_REGION_DISPLAY.get(r, r)}
            for r in config.HULL_REGIONS
        ],
        "species": [
            {"id": s, "display": config.SPECIES_DISPLAY.get(s, s)}
            for s in config.SPECIES
        ],
        "stages": [
            {"id": s, "display": {"before": "Before cleaning", "after": "After cleaning",
                                   "not_hull": "Cover / not hull"}.get(s, s)}
            for s in config.STAGES
        ],
        "automations": [
            {"name": "Hull Zone Detector",      "desc": "Sorts photos into 11 hull regions"},
            {"name": "Cleaning Stage Detector", "desc": "Before / after / not hull (overwater rejected)"},
            {"name": "Fouling Identifier",      "desc": "11 classes: slime, algae, grass, tubeworms, barnacles, mussels, …"},
            {"name": "Vessel-Name Reader",      "desc": "Reads the painted vessel name from cover photos"},
        ],
    }


# =============================================================================
# AUTH
# =============================================================================
@app.post("/api/auth/register", response_model=AuthResponse)
def register(payload: RegisterPayload):
    with db_session() as s:
        existing = s.query(User).filter(User.email == payload.email.lower()).first()
        if existing:
            raise HTTPException(409, "An account with this email already exists")
        company = Company(
            name=payload.company_name.strip(),
            tagline=(payload.tagline or "").strip() or "Marine inspection & cleaning services",
            address=(payload.address or "").strip(),
            phone=(payload.phone or "").strip(),
            website=(payload.website or "").strip(),
            email=str(payload.email).lower(),
            country=(payload.country or "").strip(),
            registration_number=(payload.registration_number or "").strip(),
            tax_number=(payload.tax_number or "").strip(),
            class_approvals=[s for s in (payload.class_approvals or []) if s],
            diving_certifications=(payload.diving_certifications or "").strip(),
            insurance=(payload.insurance or "").strip(),
            established_year=(payload.established_year or "").strip(),
            report_prefix="NAUTICAI-REP",
            report_footer="Powered by NautiCAI",
        )
        s.add(company); s.flush()
        user = User(
            company_id=company.id,
            email=str(payload.email).lower(),
            password_hash=auth_svc.hash_password(payload.password),
            full_name=payload.full_name.strip(),
            role="owner",
            is_active=True,
            last_login_at=datetime.utcnow(),
        )
        s.add(user); s.flush()
        token = auth_svc.issue_token(user.id, company.id, user.email)
        return AuthResponse(
            access_token=token, token_type="bearer",
            user=_user_to_out(user),
            company=_company_to_settings(company),
        )


@app.post("/api/auth/login", response_model=AuthResponse)
def login(payload: LoginPayload):
    with db_session() as s:
        user = s.query(User).filter(User.email == payload.email.lower()).first()
        if not user or not user.is_active:
            raise HTTPException(401, "Invalid email or password")
        if not auth_svc.verify_password(payload.password, user.password_hash):
            raise HTTPException(401, "Invalid email or password")
        user.last_login_at = datetime.utcnow()
        company = s.get(Company, user.company_id)
        token = auth_svc.issue_token(user.id, company.id, user.email)
        return AuthResponse(
            access_token=token, token_type="bearer",
            user=_user_to_out(user),
            company=_company_to_settings(company),
        )


@app.get("/api/auth/me", response_model=AuthResponse)
def me(user: User = Depends(auth_svc.get_current_user)):
    with db_session() as s:
        company = s.get(Company, user.company_id)
        # Re-issue a token to refresh the expiry on app load
        token = auth_svc.issue_token(user.id, company.id, user.email)
        return AuthResponse(
            access_token=token, token_type="bearer",
            user=_user_to_out(user),
            company=_company_to_settings(company),
        )


# =============================================================================
# ANALYZE  (scoped to company)
# =============================================================================
# Bound how many /api/analyze calls run concurrently. On a small GPU
# (laptop 4-8 GB) running many forward passes in parallel quickly
# exhausts VRAM and process RAM. We serialise the *model* phase but
# still let uploads/saves happen freely. Cloud T4/L4/A10 can safely
# raise this via NAUTICAI_ANALYZE_CONCURRENCY.
import asyncio as _asyncio


def _default_analyze_concurrency() -> int:
    from .inference import _runtime as rt_
    r = rt_.resolve(config.SHIP_REGION_CKPT)
    s = rt_.resolve(config.SPECIES_CKPT)
    return config.default_analyze_concurrency(
        region_backend=r.backend, species_backend=s.backend,
    )


_ANALYZE_SEMAPHORE = _asyncio.Semaphore(_default_analyze_concurrency())


@app.post("/api/analyze")
async def analyze(image: UploadFile = File(...),
                  region_hint: Optional[str] = Form(None),
                  vessel_name: Optional[str] = Form(None),
                  company: Company = Depends(auth_svc.get_current_company)):
    content = await image.read()
    image_id, dest = storage_svc.save_upload(content, image.filename or "upload.jpg")
    log.info("analyze upload %s · %s · %d bytes", image_id,
             image.filename or "upload.jpg", len(content))
    try:
        async with _ANALYZE_SEMAPHORE:
            # Run the (sync) model phase in a worker thread so we don't
            # block the event loop while we hold the semaphore.
            result = await _asyncio.to_thread(
                analyze_svc.analyze_file,
                dest,
                original_filename=image.filename or dest.name,
                image_id=image_id,
                region_hint=region_hint,
                company_id=company.id,
                pinned_vessel_name=(vessel_name or "").strip(),
            )
    except Exception as e:
        log.exception("analyze failed")
        raise HTTPException(500, f"analysis failed: {e}")

    # Tag the newly-created Image row with the company_id
    with db_session() as s:
        row = s.get(ImageRow, image_id)
        if row is not None:
            row.company_id = company.id
    result["url"] = f"/api/images/{image_id}/file"
    return result


@app.post("/api/analyze/video")
async def analyze_video(
    video: UploadFile = File(...),
    stride_sec: float = Form(2.0),
    max_frames: int = Form(24),
    vessel_name: Optional[str] = Form(None),
    company: Company = Depends(auth_svc.get_current_company),
):
    """Accept an ROV / dive video, extract sharp frames, run the 3 vision
    models on each, and try to OCR the vessel name from the sharpest frame."""
    content = await video.read()
    fname = video.filename or "dive.mp4"
    if not video_svc.is_video(fname):
        raise HTTPException(400, "Unsupported video format. Try MP4, MOV, MKV, or WEBM.")

    try:
        frames, meta = video_svc.extract_frames(
            content, fname, stride_sec=stride_sec, max_frames=max_frames,
        )
    except Exception as e:
        log.exception("video frame-extraction failed")
        raise HTTPException(500, f"Frame extraction failed: {e}")

    if not frames:
        raise HTTPException(
            422,
            "No usable frames found in the video. The footage may be too dark, "
            "too blurry, or entirely featureless water.",
        )

    results: list[dict] = []
    for fr in frames:
        try:
            r = analyze_svc.analyze_file(
                fr.path,
                original_filename=f"{Path(fname).stem}__t{fr.ts_sec:06.2f}s.jpg",
                image_id=fr.image_id,
                extra_meta={"ts_sec": fr.ts_sec, "source": "video",
                            "source_filename": fname},
                company_id=company.id,
                pinned_vessel_name=(vessel_name or "").strip(),
            )
        except Exception as e:
            log.warning("video frame %s failed analyze: %s", fr.image_id, e)
            continue

        # Tag with the calling company (multi-tenant isolation).
        with db_session() as s:
            row = s.get(ImageRow, fr.image_id)
            if row is not None:
                row.company_id = company.id
        r["url"] = f"/api/images/{fr.image_id}/file"
        r["ts_sec"] = fr.ts_sec
        results.append(r)

    # Best-effort vessel OCR on the sharpest frame
    vessel_guess = ""; vessel_conf = 0.0; vessel_image_id = ""
    if frames:
        best_frame = max(frames, key=lambda f: f.blurriness)
        try:
            pil = PILImage.open(best_frame.path).convert("RGB")
            ocr_result = ocr_inference.extract(pil)
            vessel_guess = ocr_result.get("best_guess", "") or ""
            vessel_conf = ocr_result.get("best_confidence", 0.0)
            vessel_image_id = best_frame.image_id
        except Exception:
            log.exception("vessel OCR pass on video failed (non-fatal)")

    return {
        "source_filename": fname,
        "video": meta,
        "frame_count": len(results),
        "frames": results,
        "vessel_ocr": {
            "best_guess": vessel_guess,
            "confidence": vessel_conf,
            "image_id": vessel_image_id,
        },
    }


@app.post("/api/ocr/vessel")
async def ocr_vessel(image: UploadFile = File(...),
                     persist: bool = Query(False),
                     company: Company = Depends(auth_svc.get_current_company)):
    content = await image.read()
    try:
        pil = PILImage.open(io.BytesIO(content)).convert("RGB")
        result = ocr_inference.extract(pil)
    except Exception as e:
        log.exception("ocr failed")
        raise HTTPException(500, f"OCR failed: {e}")

    if persist:
        try:
            image_id, dest = storage_svc.save_upload(content, image.filename or "vessel.jpg")
            W, H = pil.size
            with db_session() as s:
                row = ImageRow(
                    id=image_id, company_id=company.id,
                    filename=image.filename or dest.name, path=str(dest),
                    width=W, height=H,
                    region="vessel_cover", region_conf=1.0,
                    stage="", species_top="", species_dist={},
                    fouling_pct=0.0, severity="D",
                    ocr_text=[{"text": c["text"], "confidence": c["confidence"]}
                               for c in result.get("candidates", [])],
                    vessel_guess=result.get("best_guess", ""),
                )
                s.add(row)
            result["image_id"] = image_id
            result["url"] = f"/api/images/{image_id}/file"
        except Exception as e:
            log.exception("vessel image persist failed")
    return result


# =============================================================================
# IMAGES  (scoped)
# =============================================================================
@app.get("/api/images")
def list_images(report_id: Optional[str] = None, limit: int = Query(200, le=2000),
                company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        q = s.query(ImageRow).filter(ImageRow.company_id == company.id).order_by(ImageRow.created_at.desc())
        if report_id:
            q = q.filter(ImageRow.report_id == report_id)
        rows = q.limit(limit).all()
        return [_row_to_image(r) for r in rows]


@app.get("/api/images/{image_id}/file")
def image_file(image_id: str,
               company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        row = s.get(ImageRow, image_id)
        if row is None or (row.company_id and row.company_id != company.id):
            raise HTTPException(404, "image not found")
        resolved = storage_svc.resolve_image_path(image_id, row.path)
        if not resolved or not Path(resolved).exists():
            raise HTTPException(404, "image file missing")
        return FileResponse(resolved)


@app.get("/api/images/{image_id}/vessel-ocr")
def image_vessel_ocr(
    image_id: str,
    refresh: bool = Query(False, description="Re-run OCR on disk (fixes stale best_guess)"),
    company: Company = Depends(auth_svc.get_current_company),
):
    """Return ranked vessel-name OCR for a saved image (used by Photographic cover panel)."""
    with db_session() as s:
        row = s.get(ImageRow, image_id)
        if row is None or (row.company_id and row.company_id != company.id):
            raise HTTPException(404, "image not found")
        resolved = storage_svc.resolve_image_path(image_id, row.path)
        if not resolved or not Path(resolved).exists():
            raise HTTPException(404, "image file missing")

        stored = row.ocr_text if isinstance(row.ocr_text, list) else []
        need_run = refresh or len(stored) < 1

        if need_run:
            try:
                pil = PILImage.open(resolved).convert("RGB")
                raw = ocr_inference.extract(pil)
            except Exception as e:
                log.exception("vessel OCR refresh failed for %s", image_id)
                raise HTTPException(500, f"OCR failed: {e}") from e
            stored = [
                {"text": c["text"], "confidence": c["confidence"], "box": c.get("box")}
                for c in raw.get("candidates", [])
            ]
            payload = vessel_disc.vessel_ocr_from_candidate_list(stored, image_id=image_id)
            row.ocr_text = [{"text": c["text"], "confidence": c["confidence"]} for c in stored]
            row.vessel_guess = payload.get("best_guess") or ""
            s.add(row)
        else:
            payload = vessel_disc.vessel_ocr_from_candidate_list(stored, image_id=image_id)

        fleet = vessel_reg.load_fleet_entries(s, company.id)
        pinned = ""
        if row.report_id:
            rep = s.get(Report, row.report_id)
            if rep and rep.company_id == company.id:
                pinned = (rep.vessel_name or "").strip()
        _resolved, payload = vessel_reg.resolve_ocr_payload_for_company(
            payload,
            fleet,
            pinned_name=pinned,
        )
        if _resolved.display_name:
            row.vessel_guess = _resolved.display_name
            s.add(row)

    return payload


@app.delete("/api/images/{image_id}")
def delete_image(image_id: str,
                 company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        row = s.get(ImageRow, image_id)
        if row is None or row.company_id != company.id:
            raise HTTPException(404, "image not found")
        try:
            Path(row.path).unlink(missing_ok=True)
        except Exception:
            pass
        s.delete(row)
    return {"ok": True}


# =============================================================================
# REPORTS  (scoped)
# =============================================================================
def _gen_report_id() -> str:
    return "NCAI-" + uuid.uuid4().hex[:8].upper()


def _apply_saved_client(s, payload_vessel: VesselInfo, client_id: Optional[str],
                         company_id: str) -> None:
    """If the wizard picked a saved client, fold its details back into the
    report payload so the PDF prints exactly what's in the directory."""
    if not client_id:
        return
    cl = s.get(Client, client_id)
    if cl is None or cl.company_id != company_id:
        return
    payload_vessel.client = (payload_vessel.client.copy(update={
        "company":        cl.name        or payload_vessel.client.company,
        "address":        cl.address     or payload_vessel.client.address,
        "contact_person": cl.contact_person or payload_vessel.client.contact_person,
        "contact_email":  cl.contact_email  or payload_vessel.client.contact_email,
        "contact_phone":  cl.contact_phone  or payload_vessel.client.contact_phone,
    }) if hasattr(payload_vessel.client, "copy") else payload_vessel.client)


@app.post("/api/reports")
def create_report(payload: ReportCreate,
                  company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        # Hydrate the vessel.client from saved directory if linked
        _apply_saved_client(s, payload.vessel, payload.client_id, company.id)
        rep = Report(id=_gen_report_id(), company_id=company.id,
                     client_id=payload.client_id or None)
        _vessel_to_db(rep, payload.vessel)
        if payload.region_inspections:
            rep.region_inspections = {
                k: v.model_dump() for k, v in payload.region_inspections.items()
            }
        cover_id = (payload.vessel_image_id or "").strip() or None
        if cover_id:
            rep.vessel_image_id = cover_id
            if not (rep.vessel_name or "").strip():
                cover_row_early = s.get(ImageRow, cover_id)
                if cover_row_early and (cover_row_early.vessel_guess or "").strip():
                    rep.vessel_name = cover_row_early.vessel_guess.strip()
        s.add(rep); s.flush()
        if cover_id:
            cover = s.get(ImageRow, cover_id)
            if cover is not None and cover.company_id == company.id:
                cover.report_id = rep.id
        attached: list[ImageRow] = []
        image_ids = list(dict.fromkeys(list(payload.image_ids or []) + ([cover_id] if cover_id else [])))
        if image_ids:
            rows = s.query(ImageRow).filter(
                ImageRow.id.in_(image_ids),
                ImageRow.company_id == company.id,
            ).all()
            for r in rows:
                r.report_id = rep.id
                r.company_id = company.id
            attached = rows
            roll = cluster_svc.report_rollup(rows)
            rep.avg_fouling = roll["avg_fouling"]
            rep.severity    = roll["severity"]
        # Photographic Report cover = same image as best OCR on a model-cover shot.
        cover_pool = list(attached)
        if cover_id:
            hint = s.get(ImageRow, cover_id)
            if hint is not None and hint not in cover_pool:
                cover_pool.append(hint)
        vessel_nm = (rep.vessel_name or payload.vessel.vesselName or "").strip()
        auto_cover_id = cover_id
        if attached:
            fleet = vessel_reg.load_fleet_entries(s, company.id)
            auto = vessel_auto_svc.auto_discover_from_images(
                attached, fleet, pinned_name=vessel_nm,
            )
            if auto.display_name and not vessel_nm:
                vessel_nm = auto.display_name
                rep.vessel_name = auto.display_name
                log.info(
                    "report %s · auto vessel OCR: %s (kind=%s, nameplates=%d)",
                    rep.id, vessel_nm, auto.match_kind, auto.nameplate_count,
                )
            if auto.cover_image_id:
                auto_cover_id = auto.cover_image_id
            if auto.needs_review:
                extra = dict(rep.extra or {})
                extra["vessel_auto_review"] = {
                    "reason": auto.review_reason,
                    "candidates": auto.candidates,
                }
                rep.extra = extra
        cover_row = vessel_disc.pick_photographic_cover_image(
            cover_pool,
            preferred_id=auto_cover_id or cover_id or rep.vessel_image_id or None,
            vessel_name=vessel_nm or None,
        )
        if cover_row is not None:
            rep.vessel_image_id = cover_row.id
            cover_row.report_id = rep.id
            if not (rep.vessel_name or "").strip() and (cover_row.vessel_guess or "").strip():
                rep.vessel_name = cover_row.vessel_guess.strip()
        return _row_to_report(rep, image_count=len(image_ids))


@app.get("/api/reports", response_model=List[ReportRow])
def list_reports(status: Optional[str] = None, q: Optional[str] = None,
                 limit: int = Query(100, le=500),
                 company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        query = s.query(Report).filter(Report.company_id == company.id) \
                                .order_by(Report.created_at.desc())
        if status and status != "all":
            query = query.filter(Report.status == status)
        if q:
            ql = f"%{q.lower()}%"
            query = query.filter(
                (Report.vessel_name.ilike(ql)) |
                (Report.job_no.ilike(ql)) |
                (Report.id.ilike(ql))
            )
        rows = query.limit(limit).all()
        return [_row_to_report(r) for r in rows]


@app.get("/api/reports/{report_id}")
def get_report(report_id: str,
               company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        rep = s.get(Report, report_id)
        if rep is None or rep.company_id != company.id:
            raise HTTPException(404, "report not found")
        clusters_raw = cluster_svc.cluster_images(rep.images)
        clusters = {
            r: {
                "before": [i["id"] for i in b.get("before", [])],
                "after":  [i["id"] for i in b.get("after",  [])],
                "meta":   b["_meta"],
            }
            for r, b in clusters_raw.items()
        }
        vessel_img = None
        if rep.vessel_image_id:
            vi = s.get(ImageRow, rep.vessel_image_id)
            if vi and (not vi.company_id or vi.company_id == company.id):
                vessel_img = _row_to_image(vi)
        return {
            **_row_to_report(rep),
            "vessel": _db_to_vessel(rep).model_dump(),
            "images_detail": [_row_to_image(i) for i in rep.images],
            "clusters": clusters,
            "region_inspections": rep.region_inspections or {},
            "vessel_image": vessel_img,
        }


@app.patch("/api/reports/{report_id}")
def patch_report(report_id: str, payload: ReportPatch,
                 company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        rep = s.get(Report, report_id)
        if rep is None or rep.company_id != company.id:
            raise HTTPException(404, "report not found")
        if payload.vessel:
            _vessel_to_db(rep, payload.vessel)
        if payload.status:
            rep.status = payload.status
        if payload.region_inspections is not None:
            rep.region_inspections = {
                k: v.model_dump() for k, v in payload.region_inspections.items()
            }
        if payload.vessel_image_id is not None:
            rep.vessel_image_id = payload.vessel_image_id
        if payload.image_ids is not None:
            current = {i.id: i for i in rep.images}
            wanted = set(payload.image_ids)
            for img_id in list(current.keys()):
                if img_id not in wanted:
                    current[img_id].report_id = None
            new_rows = s.query(ImageRow).filter(
                ImageRow.id.in_(list(wanted - set(current.keys()))),
                ImageRow.company_id == company.id,
            ).all()
            for r in new_rows:
                r.report_id = rep.id
            rep_imgs = s.query(ImageRow).filter(ImageRow.report_id == rep.id).all()
            roll = cluster_svc.report_rollup(rep_imgs)
            rep.avg_fouling = roll["avg_fouling"]
            rep.severity    = roll["severity"]
        return _row_to_report(rep)


@app.delete("/api/reports/{report_id}")
def delete_report(report_id: str,
                  company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        rep = s.get(Report, report_id)
        if rep is None or rep.company_id != company.id:
            raise HTTPException(404, "report not found")
        if rep.pdf_path:
            try: Path(rep.pdf_path).unlink(missing_ok=True)
            except Exception: pass
        s.delete(rep)
    return {"ok": True}


@app.post("/api/reports/{report_id}/generate")
def generate_report_pdf(report_id: str,
                        company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        rep = s.get(Report, report_id)
        if rep is None or rep.company_id != company.id:
            raise HTTPException(404, "report not found")
        clusters = cluster_svc.cluster_images(rep.images)
        out = storage_svc.report_pdf_path(rep.id)

        # ---- Photographic Report cover (wizard id + OCR name match) ----
        cover_candidates = list(rep.images)
        if rep.vessel_image_id:
            hint = s.get(ImageRow, rep.vessel_image_id)
            if hint is not None and hint.id not in {i.id for i in cover_candidates}:
                if not hint.company_id or hint.company_id == company.id:
                    cover_candidates.append(hint)
        vessel_nm = (rep.vessel_name or "").strip()
        ocr_pool: list[ImageRow] = []
        if vessel_nm:
            ocr_pool = s.query(ImageRow).filter(
                ImageRow.company_id == company.id,
                ImageRow.vessel_guess != "",
            ).all()
            ocr_pool = [
                i for i in ocr_pool
                if vessel_disc.names_match(i.vessel_guess or "", vessel_nm)
                and storage_svc.resolve_image_path(i.id, i.path)
            ]
        by_id = {i.id: i for i in cover_candidates}
        for i in ocr_pool:
            by_id.setdefault(i.id, i)
        vi = vessel_auto_svc.ensure_cover_image_with_ocr(
            list(by_id.values()),
            vessel_name=vessel_nm or "",
            preferred_id=rep.vessel_image_id or None,
        )
        if vi is None and rep.vessel_image_id:
            hint = s.get(ImageRow, rep.vessel_image_id)
            if hint is not None and storage_svc.resolve_image_path(hint.id, hint.path):
                vi = hint
                log.info("report %s: photographic cover fallback to vessel_image_id %s", rep.id, hint.id)
        if vi is None:
            log.warning(
                "report %s: no photographic cover image (vessel_image_id=%r, images=%d, name=%r)",
                rep.id, rep.vessel_image_id, len(rep.images), vessel_nm,
            )
        vessel_image_path = None
        if vi is not None:
            rep.vessel_image_id = vi.id
            vi.path = str(storage_svc.resolve_image_path(vi.id, vi.path) or vi.path)
            vessel_image_path = vi.path
            log.info(
                "report %s: photographic cover %s (region=%s stage=%s ocr=%.2f guess=%r)",
                rep.id, vi.id, vi.region, vi.stage,
                vessel_disc.ocr_confidence_from_row(vi), vi.vessel_guess,
            )
            if not (rep.vessel_name or "").strip() and (vi.vessel_guess or "").strip():
                rep.vessel_name = vi.vessel_guess.strip()

        # Branding comes from the report's company
        c = s.get(Company, rep.company_id) or company
        settings_dict = {
            "vessel_image_path":      vessel_image_path,
            "company_name":           c.name,
            "company_tagline":        c.tagline,
            "company_address":        c.address,
            "company_phone":          c.phone,
            "company_email":          c.email,
            "company_website":        c.website,
            "company_logo_path":      c.logo_path,
            "report_footer":          c.report_footer,
            "country":                c.country,
            "registration_number":    c.registration_number,
            "tax_number":             c.tax_number,
            "class_approvals":        list(c.class_approvals or []),
            "diving_certifications":  c.diving_certifications,
            "insurance":              c.insurance,
            "report_prefix":          c.report_prefix or "NAUTICAI-REP",
            "established_year":       c.established_year,
        }

        try:
            import time as _time
            t0 = _time.perf_counter()
            build_pdf = (
                pdf_report_uw.build_pdf
                if app_config.REPORT_TEMPLATE in ("uw", "birch", "client", "synergy")
                else pdf_report_marine.build_pdf
            )
            vessel_dict = _db_to_vessel(rep).model_dump()
            source_pdf = os.environ.get("NAUTICAI_SOURCE_PDF", "").strip() or None
            log.info(
                "report %s: PDF build start (images=%d, fast=%s, cap_per_stage=%s)",
                rep.id, len(rep.images), app_config.PDF_FAST,
                app_config.PDF_MAX_PHOTOS_PER_STAGE,
            )
            build_pdf(
                out,
                vessel=vessel_dict,
                clusters=clusters,
                region_inspections=rep.region_inspections or {},
                vessel_image_path=vessel_image_path,
                source_pdf_path=source_pdf,
                settings=settings_dict,
                report_id=rep.id,
                created_at=rep.created_at,
            )
            log.info(
                "report %s: PDF built in %.1fs → %s",
                rep.id, _time.perf_counter() - t0, out,
            )
        except Exception as e:
            log.exception("pdf build failed")
            raise HTTPException(500, f"PDF build failed: {e}")
        if not out.exists() or out.stat().st_size < 100:
            raise HTTPException(500, f"PDF file missing or empty after build: {out}")
        rep.pdf_path = str(out.resolve())
        rep.status = "completed" if rep.images else "draft"
        s.flush()
        return {"ok": True, "pdf_url": f"/api/reports/{rep.id}/pdf"}


@app.get("/api/reports/{report_id}/pdf")
def download_pdf(report_id: str,
                 company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        rep = s.get(Report, report_id)
        if rep is None or rep.company_id != company.id:
            raise HTTPException(404, "report not found")
        if not rep.pdf_path or not Path(rep.pdf_path).exists():
            raise HTTPException(404, "PDF not generated yet — POST /generate first")
        filename = f"NautiCAI_{(rep.vessel_name or 'report').replace(' ', '_')}_{rep.id}.pdf"
        return FileResponse(rep.pdf_path, media_type="application/pdf", filename=filename)


# =============================================================================
# STATS  (scoped)
# =============================================================================
@app.get("/api/stats", response_model=StatsResponse)
def stats(company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        all_imgs = s.query(ImageRow).filter(ImageRow.company_id == company.id).all()
        all_reps = s.query(Report).filter(Report.company_id == company.id) \
                                  .order_by(Report.created_at.desc()).all()

        vessels = {r.vessel_name for r in all_reps if r.vessel_name}
        avg_f = round(sum((i.fouling_pct or 0.0) for i in all_imgs) /
                      max(1, len(all_imgs)), 1) if all_imgs else 0.0

        now = datetime.utcnow().replace(day=1)
        months = [(now - timedelta(days=30 * i)).strftime("%b") for i in range(5, -1, -1)]
        bucket = {m: 0 for m in months}
        for r in all_reps:
            label = r.created_at.strftime("%b")
            if label in bucket:
                bucket[label] += 1
        activity = [{"m": k, "inspections": v,
                     "foulingIdx": round(avg_f, 0) if all_imgs else 0}
                    for k, v in bucket.items()]

        species_counts = defaultdict(int)
        region_pct     = defaultdict(list)
        for img in all_imgs:
            if img.species_top:
                species_counts[img.species_top] += 1
            if img.region:
                region_pct[img.region].append(img.fouling_pct or 0.0)

        species_palette = {
            "algae": "#84cc16", "macroalgae": "#22c55e",
            "barnacles": "#f59e0b", "mussels": "#ef4444",
            "clean_paint": "#10b981",
        }
        species_mix = [
            {"name": config.SPECIES_DISPLAY.get(k, k.title()),
             "value": v, "color": species_palette.get(k, "#64748b")}
            for k, v in species_counts.items() if k in config.SPECIES_DISPLAY
        ]
        region_index = [
            {"name": config.HULL_REGION_DISPLAY[k].split(" ")[0],
             "fouling": round(sum(v) / len(v), 1)}
            for k, v in region_pct.items()
            if v and k in config.HULL_REGION_DISPLAY
        ]

        recent = [_row_to_report(r) for r in all_reps[:5]]

        return StatsResponse(
            vessels_inspected=len(vessels),
            images_processed=len(all_imgs),
            reports_generated=sum(1 for r in all_reps if r.pdf_path),
            avg_fouling=avg_f,
            activity=activity,
            species_mix=species_mix,
            region_index=region_index,
            recent=recent,
        )


# =============================================================================
# CLIENTS  (vessel-owner directory — entered once, reused across reports)
# =============================================================================
def _client_to_row(c: Client) -> ClientRow:
    return ClientRow(
        id=c.id, name=c.name, address=c.address or "",
        contact_person=c.contact_person or "", contact_email=c.contact_email or "",
        contact_phone=c.contact_phone or "", country=c.country or "",
        notes=c.notes or "",
        created_at=c.created_at, updated_at=c.updated_at,
    )


@app.get("/api/clients", response_model=List[ClientRow])
def list_clients(q: Optional[str] = None,
                 limit: int = Query(200, le=500),
                 company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        query = s.query(Client).filter(Client.company_id == company.id) \
                               .order_by(Client.name.asc())
        if q:
            ql = f"%{q.lower()}%"
            query = query.filter(
                (Client.name.ilike(ql)) |
                (Client.contact_person.ilike(ql)) |
                (Client.contact_email.ilike(ql))
            )
        return [_client_to_row(c) for c in query.limit(limit).all()]


@app.post("/api/clients", response_model=ClientRow)
def create_client(payload: ClientCreate,
                  company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        cl = Client(
            company_id=company.id,
            name=payload.name.strip(),
            address=payload.address,
            contact_person=payload.contact_person,
            contact_email=payload.contact_email,
            contact_phone=payload.contact_phone,
            country=payload.country,
            notes=payload.notes,
        )
        s.add(cl); s.flush()
        return _client_to_row(cl)


@app.get("/api/clients/{client_id}", response_model=ClientRow)
def get_client(client_id: str,
               company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        cl = s.get(Client, client_id)
        if cl is None or cl.company_id != company.id:
            raise HTTPException(404, "client not found")
        return _client_to_row(cl)


@app.put("/api/clients/{client_id}", response_model=ClientRow)
def update_client(client_id: str, payload: ClientCreate,
                  company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        cl = s.get(Client, client_id)
        if cl is None or cl.company_id != company.id:
            raise HTTPException(404, "client not found")
        cl.name           = payload.name.strip()
        cl.address        = payload.address
        cl.contact_person = payload.contact_person
        cl.contact_email  = payload.contact_email
        cl.contact_phone  = payload.contact_phone
        cl.country        = payload.country
        cl.notes          = payload.notes
        s.flush()
        return _client_to_row(cl)


@app.delete("/api/clients/{client_id}")
def delete_client(client_id: str,
                  company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        cl = s.get(Client, client_id)
        if cl is None or cl.company_id != company.id:
            raise HTTPException(404, "client not found")
        s.delete(cl)
        return {"ok": True}


# =============================================================================
# VESSELS  (company fleet directory — OCR resolution)
# =============================================================================
def _vessel_to_row(v: Vessel) -> VesselRow:
    aliases = v.aliases if isinstance(v.aliases, list) else []
    return VesselRow(
        id=v.id,
        name=v.name,
        aliases=aliases,
        imo_number=v.imo_number or "",
        notes=v.notes or "",
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


@app.get("/api/vessels", response_model=List[VesselRow])
def list_vessels(q: Optional[str] = None,
                 limit: int = Query(200, le=500),
                 company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        query = s.query(Vessel).filter(Vessel.company_id == company.id) \
                               .order_by(Vessel.name.asc())
        if q:
            ql = f"%{q.lower()}%"
            query = query.filter(Vessel.name.ilike(ql))
        return [_vessel_to_row(v) for v in query.limit(limit).all()]


@app.post("/api/vessels", response_model=VesselRow)
def create_vessel(payload: VesselCreate,
                  company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        aliases = [a.strip() for a in (payload.aliases or []) if str(a).strip()]
        v = Vessel(
            company_id=company.id,
            name=payload.name.strip(),
            aliases=aliases,
            imo_number=(payload.imo_number or "").strip(),
            notes=payload.notes or "",
        )
        s.add(v)
        s.flush()
        return _vessel_to_row(v)


@app.get("/api/vessels/{vessel_id}", response_model=VesselRow)
def get_vessel(vessel_id: str,
               company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        v = s.get(Vessel, vessel_id)
        if v is None or v.company_id != company.id:
            raise HTTPException(404, "vessel not found")
        return _vessel_to_row(v)


@app.put("/api/vessels/{vessel_id}", response_model=VesselRow)
def update_vessel(vessel_id: str, payload: VesselCreate,
                  company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        v = s.get(Vessel, vessel_id)
        if v is None or v.company_id != company.id:
            raise HTTPException(404, "vessel not found")
        v.name = payload.name.strip()
        v.aliases = [a.strip() for a in (payload.aliases or []) if str(a).strip()]
        v.imo_number = (payload.imo_number or "").strip()
        v.notes = payload.notes or ""
        s.flush()
        return _vessel_to_row(v)


@app.delete("/api/vessels/{vessel_id}")
def delete_vessel(vessel_id: str,
                  company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        v = s.get(Vessel, vessel_id)
        if v is None or v.company_id != company.id:
            raise HTTPException(404, "vessel not found")
        s.delete(v)
        return {"ok": True}


def _auto_detect_from_image_ids(
    s,
    image_ids: list[str],
    company_id: str,
    *,
    pinned_vessel_name: str = "",
) -> vessel_auto_svc.AutoVesselBatchResult:
    rows: list[ImageRow] = []
    if image_ids:
        rows = s.query(ImageRow).filter(
            ImageRow.id.in_(image_ids),
            ImageRow.company_id == company_id,
        ).all()
    fleet = vessel_reg.load_fleet_entries(s, company_id)
    return vessel_auto_svc.auto_discover_from_images(
        rows, fleet, pinned_name=(pinned_vessel_name or "").strip(),
    )


@app.post("/api/vessels/auto-detect", response_model=VesselSuggestResponse)
def auto_detect_vessel(
    payload: VesselSuggestRequest,
    company: Company = Depends(auth_svc.get_current_company),
):
    """Fully automated vessel name + cover photo from analysed raw images (no manual fleet)."""
    with db_session() as s:
        auto = _auto_detect_from_image_ids(
            s, payload.image_ids, company.id,
            pinned_vessel_name=payload.pinned_vessel_name,
        )
        alts = vessel_auto_svc.list_cover_alternates(rows, fleet)
        return VesselSuggestResponse(
            display_name=auto.display_name,
            match_kind=auto.match_kind,
            confidence=auto.confidence,
            score=auto.score,
            raw_ocr=auto.raw_ocr,
            registry_id=auto.registry_id,
            needs_review=auto.needs_review,
            review_reason=auto.review_reason or "",
            cover_image_id=auto.cover_image_id,
            cover_alternates=[CoverAlternateRow(**a) for a in alts],
        )


@app.post("/api/vessels/cover-alternates", response_model=CoverAlternatesResponse)
def list_cover_alternates(
    payload: VesselSuggestRequest,
    refresh: bool = Query(False, description="Re-run OCR on every nameplate photo"),
    company: Company = Depends(auth_svc.get_current_company),
):
    """Ranked list of nameplate photos + OCR names (cycle when one angle mis-reads)."""
    with db_session() as s:
        rows: list[ImageRow] = []
        if payload.image_ids:
            rows = s.query(ImageRow).filter(
                ImageRow.id.in_(payload.image_ids),
                ImageRow.company_id == company.id,
            ).all()
        fleet = vessel_reg.load_fleet_entries(s, company.id)
        alts = vessel_auto_svc.list_cover_alternates(
            rows, fleet, refresh_ocr=refresh,
        )
        return CoverAlternatesResponse(
            cover_alternates=[CoverAlternateRow(**a) for a in alts],
            total=len(alts),
        )


@app.post("/api/vessels/suggest", response_model=VesselSuggestResponse)
def suggest_vessel(payload: VesselSuggestRequest,
                   company: Company = Depends(auth_svc.get_current_company)):
    """Alias for auto-detect (backward compatible)."""
    return auto_detect_vessel(payload, company)


# =============================================================================
# SETTINGS  (company branding)
# =============================================================================
@app.get("/api/settings", response_model=SettingsModel)
def get_settings(company: Company = Depends(auth_svc.get_current_company)):
    return _company_to_settings(company)


@app.put("/api/settings", response_model=SettingsModel)
def put_settings(payload: SettingsModel,
                 company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        c = s.get(Company, company.id)
        c.name                  = payload.company_name
        c.tagline               = payload.company_tagline
        c.address               = payload.company_address
        c.phone                 = payload.company_phone
        c.email                 = payload.company_email
        c.website               = payload.company_website
        c.report_footer         = payload.report_footer
        c.country               = payload.country
        c.registration_number   = payload.registration_number
        c.tax_number            = payload.tax_number
        c.class_approvals       = list(payload.class_approvals or [])
        c.diving_certifications = payload.diving_certifications
        c.insurance             = payload.insurance
        c.report_prefix         = payload.report_prefix or "NAUTICAI-REP"
        c.established_year      = payload.established_year
        s.flush()
        return _company_to_settings(c)


@app.post("/api/settings/logo", response_model=SettingsModel)
async def upload_logo(image: UploadFile = File(...),
                      company: Company = Depends(auth_svc.get_current_company)):
    content = await image.read()
    dest = _company_logo_dest(company.id, Path(image.filename or ".png").suffix)
    dest.write_bytes(content)
    with db_session() as s:
        c = s.get(Company, company.id)
        # Clean up an older logo with a different extension
        try:
            if c.logo_path and Path(c.logo_path) != dest:
                Path(c.logo_path).unlink(missing_ok=True)
        except Exception:
            pass
        c.logo_path = str(dest)
        s.flush()
        return _company_to_settings(c)


@app.get("/api/settings/logo")
def get_logo(cid: Optional[str] = None,
             company: Optional[Company] = Depends(auth_svc.get_current_company)):
    """Returns the calling company's logo. `cid` is informational (cache-bust)."""
    if not company:
        raise HTTPException(401, "auth required")
    with db_session() as s:
        c = s.get(Company, company.id)
        if not c or not c.logo_path or not Path(c.logo_path).exists():
            raise HTTPException(404, "no logo set")
        return FileResponse(c.logo_path)


@app.delete("/api/settings/logo", response_model=SettingsModel)
def delete_logo(company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        c = s.get(Company, company.id)
        if c and c.logo_path:
            try: Path(c.logo_path).unlink(missing_ok=True)
            except Exception: pass
            c.logo_path = ""
            s.flush()
        return _company_to_settings(c)


# =============================================================================
# Vessel-image attach (kept for compatibility)
# =============================================================================
@app.post("/api/reports/{report_id}/vessel-image")
async def attach_vessel_image(report_id: str, image: UploadFile = File(...),
                              company: Company = Depends(auth_svc.get_current_company)):
    with db_session() as s:
        rep = s.get(Report, report_id)
        if rep is None or rep.company_id != company.id:
            raise HTTPException(404, "report not found")
    content = await image.read()
    image_id, dest = storage_svc.save_upload(content, image.filename or "vessel.jpg")
    try:
        pil = PILImage.open(io.BytesIO(content)).convert("RGB")
        W, H = pil.size
    except Exception:
        W = H = 0
    with db_session() as s:
        row = ImageRow(
            id=image_id, company_id=company.id,
            filename=image.filename or dest.name, path=str(dest),
            width=W, height=H, region="vessel_cover", region_conf=1.0,
        )
        s.add(row)
        rep = s.get(Report, report_id)
        rep.vessel_image_id = image_id
    return {"ok": True, "image_id": image_id, "url": f"/api/images/{image_id}/file"}
