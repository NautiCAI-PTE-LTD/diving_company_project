"""Persistence layer (multi-tenant).

If `DATABASE_URL` is set (e.g. Supabase Postgres connection string), the
backend uses that. Otherwise it falls back to a local SQLite file under
`backend/storage/nauticai.db` so dev still works out-of-the-box.

Schema
------
companies (1) ──< users (N)
companies (1) ──< reports (N) ──< images (N)
"""
from __future__ import annotations
from datetime import datetime
import uuid as _uuid
import logging
from contextlib import contextmanager

from sqlalchemy import (
    create_engine, Column, String, Integer, Float, DateTime, ForeignKey,
    JSON, Text, Boolean, text, UniqueConstraint, Index,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

from . import config

log = logging.getLogger("nauticai.db")


# ---------------------------------------------------------------- engine ----
_IS_PG = bool(config.DATABASE_URL) and config.DATABASE_URL.startswith(("postgres", "postgresql"))

if _IS_PG:
    # Normalise: Supabase gives `postgresql://`, SQLAlchemy is happy with that.
    url = config.DATABASE_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(url, future=True, pool_pre_ping=True)
    log.info("DB · Postgres backend in use")
else:
    engine = create_engine(
        f"sqlite:///{config.DB_PATH}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    log.info("DB · SQLite backend in use (no DATABASE_URL set)")

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def _uid() -> str:
    return _uuid.uuid4().hex


# ---------------------------------------------------------------- models ----
class Company(Base):
    """A tenant — one diving company. Every report/image/user belongs to one."""
    __tablename__ = "companies"
    id              = Column(String, primary_key=True, default=_uid)
    name            = Column(String, nullable=False)
    tagline         = Column(String, default="Marine inspection & cleaning services")
    address         = Column(Text,   default="")
    phone           = Column(String, default="")
    email           = Column(String, default="")
    website         = Column(String, default="")
    logo_path       = Column(String, default="")           # filesystem path
    report_footer   = Column(String, default="Powered by NautiCAI")
    # Extended profile — these appear on the report cover so the surveyor
    # never has to retype them per job:
    country               = Column(String, default="")
    registration_number   = Column(String, default="")     # business / company reg.
    tax_number            = Column(String, default="")     # VAT / GST / EIN
    class_approvals       = Column(JSON,   default=list)   # ["BV","DNV","ABS",…]
    diving_certifications = Column(Text,   default="")     # IMCA, ADCI, free-form
    insurance             = Column(Text,   default="")     # underwriter, policy
    report_prefix         = Column(String, default="NAUTICAI-REP")
    established_year      = Column(String, default="")
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    users   = relationship("User",   back_populates="company", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="company", cascade="all, delete-orphan")
    images  = relationship("Image",  back_populates="company", cascade="all, delete-orphan")
    clients = relationship("Client", back_populates="company", cascade="all, delete-orphan")
    vessels = relationship("Vessel", back_populates="company", cascade="all, delete-orphan")


class User(Base):
    """A login. One company can have many users (owner / supervisor / viewer)."""
    __tablename__ = "users"
    id            = Column(String, primary_key=True, default=_uid)
    company_id    = Column(String, ForeignKey("companies.id", ondelete="CASCADE"),
                            index=True, nullable=False)
    email         = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name     = Column(String, default="")
    role          = Column(String, default="owner")        # owner | supervisor | viewer
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    company = relationship("Company", back_populates="users")

    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_company_id_email", "company_id", "email"),
    )


class Client(Base):
    """A client / vessel-owner that the diving company services. Stored once
    per company so the same details aren't re-typed every inspection.

    A Report can optionally reference a Client; when it does, the report
    payload pulls the client info from this row at render time.
    """
    __tablename__ = "clients"
    id              = Column(String, primary_key=True, default=_uid)
    company_id      = Column(String, ForeignKey("companies.id", ondelete="CASCADE"),
                              index=True, nullable=False)
    name            = Column(String, nullable=False)         # company / vessel-owner name
    address         = Column(Text,   default="")
    contact_person  = Column(String, default="")
    contact_email   = Column(String, default="")
    contact_phone   = Column(String, default="")
    country         = Column(String, default="")
    notes           = Column(Text,   default="")
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company", back_populates="clients")

    __table_args__ = (
        Index("ix_clients_company_id_name", "company_id", "name"),
    )


class Vessel(Base):
    """Company vessel directory — canonical names + OCR aliases (Silverstone, Patris, …)."""
    __tablename__ = "vessels"
    id         = Column(String, primary_key=True, default=_uid)
    company_id = Column(String, ForeignKey("companies.id", ondelete="CASCADE"),
                         index=True, nullable=False)
    name       = Column(String, nullable=False)
    aliases    = Column(JSON, default=list)   # ["SILVERSTONE", "SS SILVERSTONE"]
    imo_number = Column(String, default="")
    notes      = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company", back_populates="vessels")

    __table_args__ = (
        Index("ix_vessels_company_id_name", "company_id", "name"),
    )


class Report(Base):
    __tablename__ = "reports"
    id          = Column(String, primary_key=True)
    company_id  = Column(String, ForeignKey("companies.id", ondelete="CASCADE"),
                          index=True, nullable=True)   # nullable for SQLite back-compat
    client_id   = Column(String, ForeignKey("clients.id", ondelete="SET NULL"),
                          index=True, nullable=True)
    vessel_name = Column(String, default="")
    vessel_type = Column(String, default="")
    vessel_class = Column(String, default="")
    job_no      = Column(String, default="")
    job_scope   = Column(String, default="")
    loa         = Column(String, default="")
    draft       = Column(String, default="")
    location    = Column(String, default="")
    dive_date   = Column(String, default="")
    weather     = Column(String, default="")
    sea         = Column(String, default="")
    visibility  = Column(String, default="")
    tide        = Column(String, default="")
    captain     = Column(String, default="")
    dive_supervisor = Column(String, default="")
    divers      = Column(String, default="")
    boat_captain = Column(String, default="")
    status      = Column(String, default="draft")          # draft | in_review | completed
    severity    = Column(String, default="A")              # rolled-up A/B/C/D
    avg_fouling = Column(Float,  default=0.0)
    notes       = Column(Text,   default="")
    extra       = Column(JSON,   default=dict)             # any other key/value
    pdf_path    = Column(String, default="")
    region_inspections = Column(JSON, default=dict)        # {region_id: {...}}
    vessel_image_id    = Column(String, default="")        # Image.id for OCR vessel photo
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company", back_populates="reports")
    images  = relationship("Image", back_populates="report",
                            cascade="all, delete-orphan", order_by="Image.created_at",
                            foreign_keys="Image.report_id")


class Image(Base):
    __tablename__ = "images"
    id          = Column(String, primary_key=True)
    company_id  = Column(String, ForeignKey("companies.id", ondelete="CASCADE"),
                          index=True, nullable=True)
    report_id   = Column(String, ForeignKey("reports.id"), index=True, nullable=True)
    filename    = Column(String, nullable=False)
    path        = Column(String, nullable=False)
    width       = Column(Integer, default=0)
    height      = Column(Integer, default=0)
    region      = Column(String, default="")
    region_conf = Column(Float,  default=0.0)
    stage       = Column(String, default="")
    stage_conf  = Column(Float,  default=0.0)
    species_top = Column(String, default="")
    species_dist = Column(JSON,  default=dict)
    fouling_pct = Column(Float,  default=0.0)
    severity    = Column(String, default="A")
    ocr_text    = Column(JSON,   default=list)
    vessel_guess = Column(String, default="")
    created_at  = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="images")
    report  = relationship("Report", back_populates="images", foreign_keys=[report_id])


# ---------------------------------------------------------------- migrate ----
def _migrate_sqlite() -> None:
    """Light-weight migration so existing dev SQLite DBs keep working."""
    with engine.begin() as conn:
        # reports
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(reports)")).all()}
        if cols:
            if "region_inspections" not in cols:
                conn.execute(text("ALTER TABLE reports ADD COLUMN region_inspections JSON DEFAULT '{}'"))
            if "vessel_image_id" not in cols:
                conn.execute(text("ALTER TABLE reports ADD COLUMN vessel_image_id TEXT DEFAULT ''"))
            if "company_id" not in cols:
                conn.execute(text("ALTER TABLE reports ADD COLUMN company_id TEXT"))
            if "client_id" not in cols:
                conn.execute(text("ALTER TABLE reports ADD COLUMN client_id TEXT"))
        # images
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(images)")).all()}
        if cols and "company_id" not in cols:
            conn.execute(text("ALTER TABLE images ADD COLUMN company_id TEXT"))
        # companies — extended profile fields
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(companies)")).all()}
        if cols:
            for cname, ddl in _EXTENDED_COMPANY_COLS:
                if cname not in cols:
                    conn.execute(text(f"ALTER TABLE companies ADD COLUMN {ddl}"))


# Column name → DDL fragment used by both SQLite and Postgres migrators.
_EXTENDED_COMPANY_COLS = [
    ("country",               "country TEXT DEFAULT ''"),
    ("registration_number",   "registration_number TEXT DEFAULT ''"),
    ("tax_number",            "tax_number TEXT DEFAULT ''"),
    ("class_approvals",       "class_approvals JSON DEFAULT '[]'"),
    ("diving_certifications", "diving_certifications TEXT DEFAULT ''"),
    ("insurance",             "insurance TEXT DEFAULT ''"),
    ("report_prefix",         "report_prefix TEXT DEFAULT 'NAUTICAI-REP'"),
    ("established_year",      "established_year TEXT DEFAULT ''"),
]


def _migrate_postgres() -> None:
    """Idempotent migrator for Supabase Postgres — uses ADD COLUMN IF NOT EXISTS."""
    with engine.begin() as conn:
        for cname, _ddl in _EXTENDED_COMPANY_COLS:
            # JSON in SQLite ↔ JSONB in Postgres
            pg_type = "jsonb DEFAULT '[]'::jsonb" if cname == "class_approvals" \
                else ("text DEFAULT 'NAUTICAI-REP'" if cname == "report_prefix" else "text DEFAULT ''")
            conn.execute(text(
                f"ALTER TABLE public.companies "
                f"ADD COLUMN IF NOT EXISTS {cname} {pg_type}"
            ))
        # reports.client_id — link to clients directory (added later)
        conn.execute(text(
            "ALTER TABLE public.reports ADD COLUMN IF NOT EXISTS client_id text"
        ))


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if _IS_PG:
        _migrate_postgres()
    else:
        _migrate_sqlite()


@contextmanager
def db_session() -> Session:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
