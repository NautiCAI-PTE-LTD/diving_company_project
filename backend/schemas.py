"""Pydantic request / response models."""
from __future__ import annotations
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr


class RegionPred(BaseModel):
    id: str
    display: str
    confidence: float


class StagePred(BaseModel):
    id: str           # before | after
    confidence: float


class SpeciesPoint(BaseModel):
    id: str
    display: str
    prob: float


class SpeciesPred(BaseModel):
    top: str
    top_display: str
    distribution: List[SpeciesPoint]


class OcrLine(BaseModel):
    text: str
    confidence: float
    box: List[List[float]]   # 4 corners


class AnalyzeResult(BaseModel):
    image_id: str
    filename: str
    width: int
    height: int
    region: RegionPred
    stage: StagePred
    species: SpeciesPred
    fouling_pct: float
    severity: str            # A | B | C | D
    is_overview: bool = False  # True if filtered out as a whole-ship cover shot


class VesselResolution(BaseModel):
    """OCR matched to company fleet or flagged as new vessel."""
    display_name: str = ""
    match_kind: str = ""       # auto | exact | fuzzy | discovery | no_nameplate | pinned | conflict
    confidence: float = 0.0
    score: float = 0.0
    raw_ocr: str = ""
    registry_id: Optional[str] = None
    needs_review: bool = False
    review_reason: str = ""
    alternatives: List[Dict[str, Any]] = Field(default_factory=list)


class VesselOcrResult(BaseModel):
    candidates: List[OcrLine] = Field(default_factory=list)
    best_guess: str = ""
    best_confidence: float = 0.0
    image_id: Optional[str] = None
    vessel_resolution: Optional[VesselResolution] = None


# ---------------- Vessels directory ----------------------------------------
class VesselCreate(BaseModel):
    name: str = Field(..., min_length=1)
    aliases: List[str] = Field(default_factory=list)
    imo_number: str = ""
    notes: str = ""


class VesselRow(VesselCreate):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VesselSuggestRequest(BaseModel):
    image_ids: List[str] = Field(default_factory=list)
    pinned_vessel_name: str = ""


class CoverAlternateRow(BaseModel):
    """One nameplate / whole-ship photo and the OCR vessel name read from it."""
    image_id: str
    display_name: str = ""
    confidence: float = 0.0
    score: float = 0.0
    raw_ocr: str = ""
    matches_best_name: bool = False
    likely_truncated: bool = False


class VesselSuggestResponse(BaseModel):
    display_name: str = ""
    match_kind: str = ""
    confidence: float = 0.0
    score: float = 0.0
    raw_ocr: str = ""
    registry_id: Optional[str] = None
    needs_review: bool = False
    review_reason: str = ""
    cover_image_id: Optional[str] = None
    cover_alternates: List[CoverAlternateRow] = Field(default_factory=list)


class CoverAlternatesResponse(BaseModel):
    cover_alternates: List[CoverAlternateRow] = Field(default_factory=list)
    total: int = 0


# ---------------- Clients directory --------------------------------------
class ClientCreate(BaseModel):
    """Body for POST/PUT /api/clients — what the user fills in once."""
    name:            str          = Field(..., min_length=1)
    address:         str          = ""
    contact_person:  str          = ""
    contact_email:   str          = ""
    contact_phone:   str          = ""
    country:         str          = ""
    notes:           str          = ""


class ClientRow(ClientCreate):
    """Full row returned by GET /api/clients."""
    id:         str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------------- Report payloads ----------------------------------------
class ClientInfo(BaseModel):
    company:         str = ""
    address:         str = ""
    contact_person:  str = ""
    contact_email:   str = ""
    contact_phone:   str = ""


class ClientRepresentative(BaseModel):
    """A representative from the client/vessel side (e.g. ship's Captain)."""
    role: str = "Captain"
    name: str = ""


class TeamMember(BaseModel):
    role: str = "Diver"
    name: str = ""


class CrewDay(BaseModel):
    """One day of work performed by a single dive crew."""
    date: str = ""                       # optional explicit date
    time_left_base: str = ""
    time_arrived_jobsite: str = ""
    dive_ops_started: str = ""
    dive_ops_completed: str = ""
    time_left_jobsite: str = ""
    time_arrived_base: str = ""
    standby_from: str = ""
    standby_to: str = ""
    remarks: str = ""


class CrewSea(BaseModel):
    """Per-crew sea conditions — they often differ between teams that dive
    on different days / different tide windows."""
    weather:    str = ""
    sea:        str = ""
    visibility: str = ""
    tide:       str = ""


class CrewBlock(BaseModel):
    """One full dive crew on the job. The template can have several of these
    (DIVING TEAM - 1, DIVING TEAM - 2, …), each with its own days + sea state."""
    label:        str = "Diving Team - 1"
    supervisor:   str = ""
    divers:       str = ""               # free-form "Eugenio, Arivu, Khairul" list
    boat_captain: str = ""
    sea:          CrewSea = Field(default_factory=CrewSea)
    days:         List[CrewDay] = Field(default_factory=list)
    remarks:      str = ""


class VesselInfo(BaseModel):
    vesselName: str = ""
    vesselType: str = ""
    vesselClass: str = ""
    jobNo: str = ""
    jobScope: str = "Under-Hull Cleaning & Propeller Polishing"
    loa: str = ""
    draft: str = ""
    location: str = ""
    diveDate: str = ""
    weather: str = ""
    sea: str = ""
    visibility: str = ""
    tide: str = ""
    captain: str = ""
    diveSupervisor: str = ""
    divers: str = ""             # legacy text field, kept for back-compat
    boatCaptain: str = ""
    notes: str = ""
    # NEW: client (vessel owner) — the priority brand on the report
    client: Optional[ClientInfo] = Field(default_factory=ClientInfo)
    # Client-side reps (e.g. ship's Captain, Chief Officer)
    client_reps: List[ClientRepresentative] = Field(default_factory=list)
    # Dive team list — legacy flat list (role + name). Still accepted for
    # back-compat. New multi-crew operations use `crews` below instead.
    team:   List[TeamMember]    = Field(default_factory=list)
    # NEW: one or more dive crews. Each has its own supervisor, divers,
    # boat captain, sea conditions, and days. Renders as DIVING TEAM - 1 / 2 / …
    crews:  List[CrewBlock]     = Field(default_factory=list)
    extra:  Dict[str, Any]      = Field(default_factory=dict)


class RegionFindings(BaseModel):
    """Manual entries for a single hull region (mirrors the per-region pages of the PDF)."""
    inspection_done:   bool = True
    overall_condition: str  = "Good"          # "Good" | "Poor"
    damage_observed:   bool = False
    damage_notes:      str  = ""
    notes:             str  = ""
    # Region-specific (only the relevant block is filled in by the UI)
    bilge_keels:  Optional[Dict[str, Any]] = None
    sea_chest:    Optional[Dict[str, Any]] = None
    propeller:    Optional[Dict[str, Any]] = None
    rudder:       Optional[Dict[str, Any]] = None
    rope_guard:   Optional[Dict[str, Any]] = None


class ReportCreate(BaseModel):
    vessel: VesselInfo
    image_ids: List[str] = Field(default_factory=list)
    region_inspections: Dict[str, RegionFindings] = Field(default_factory=dict)
    vessel_image_id: Optional[str] = ""
    client_id: Optional[str] = None           # link to saved Clients directory


class ReportPatch(BaseModel):
    vessel: Optional[VesselInfo] = None
    image_ids: Optional[List[str]] = None
    region_inspections: Optional[Dict[str, RegionFindings]] = None
    vessel_image_id: Optional[str] = None
    status: Optional[str] = None
    client_id: Optional[str] = None


# ---------------- Company branding settings -------------------------------
class SettingsModel(BaseModel):
    company_name:    str = "Your Diving Company"
    company_tagline: str = "Marine inspection & cleaning services"
    company_address: str = ""
    company_phone:   str = ""
    company_email:   str = ""
    company_website: str = ""
    report_footer:   str = "Powered by NautiCAI"
    # Extended company profile — every field shows up on the report cover
    country:              str = ""
    registration_number:  str = ""
    tax_number:           str = ""
    class_approvals:      List[str] = Field(default_factory=list)
    diving_certifications: str = ""
    insurance:            str = ""
    report_prefix:        str = "NAUTICAI-REP"
    established_year:     str = ""
    has_logo:             bool = False
    logo_url:             Optional[str] = None
    updated_at:           Optional[datetime] = None


class ImageRow(BaseModel):
    id: str
    filename: str
    url: str
    region: str
    region_display: str
    stage: str
    species_top: str
    fouling_pct: float
    severity: str
    width: int
    height: int

    class Config:
        from_attributes = True


class ReportRow(BaseModel):
    id: str
    vesselName: str
    vesselType: str
    jobNo: str
    status: str
    severity: str
    avg_fouling: float
    images: int
    pdf_url: Optional[str] = None
    createdAt: datetime
    updatedAt: datetime


class ReportDetail(ReportRow):
    vessel: VesselInfo
    images_detail: List[ImageRow] = Field(default_factory=list)
    clusters: Dict[str, Dict[str, List[str]]] = Field(default_factory=dict)
    # clusters[region_id] = { "before": [image_id...], "after": [image_id...] }


# ---------------- Auth ----------------------------------------------------
class RegisterPayload(BaseModel):
    # --- account ---
    company_name: str = Field(..., min_length=2, max_length=120)
    full_name:    str = Field(..., min_length=1, max_length=120)
    email:        EmailStr
    password:     str = Field(..., min_length=6, max_length=200)
    # --- optional company profile (also editable later in Settings) ---
    tagline:                Optional[str]       = ""
    address:                Optional[str]       = ""
    phone:                  Optional[str]       = ""
    website:                Optional[str]       = ""
    country:                Optional[str]       = ""
    registration_number:    Optional[str]       = ""
    tax_number:             Optional[str]       = ""
    class_approvals:        Optional[List[str]] = None
    diving_certifications:  Optional[str]       = ""
    insurance:              Optional[str]       = ""
    established_year:       Optional[str]       = ""


class LoginPayload(BaseModel):
    email:    EmailStr
    password: str


class UserOut(BaseModel):
    id:         str
    email:      str
    full_name:  str
    role:       str
    company_id: str
    created_at: Optional[datetime] = None


class AuthResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user:         UserOut
    company:      "SettingsModel"


class StatsResponse(BaseModel):
    vessels_inspected: int
    images_processed: int
    reports_generated: int
    avg_fouling: float
    activity:    List[Dict[str, Any]]
    species_mix: List[Dict[str, Any]]
    region_index: List[Dict[str, Any]]
    recent: List[ReportRow]
