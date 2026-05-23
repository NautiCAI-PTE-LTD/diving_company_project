"""Seed the 6-vessel fleet for the logged-in company (dev helper).

Usage (from project root, after register/login or with existing DB):
  python scripts/seed_vessel_fleet.py
  python scripts/seed_vessel_fleet.py --company-id YOUR_COMPANY_ID
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.db import init_db, db_session, Vessel, Company

FLEET = [
    ("Silverstone", ["SILVERSTONE", "SS SILVERSTONE"]),
    ("Patris", ["PATRIS", "PATRLS"]),
    ("Atlanta", ["ATLANTA", "ATALANTA"]),
    ("Dalma", ["DALMA"]),
    ("Skiathos", ["SKIATHOS", "SKIATKOS", "BKIATHOS"]),
    ("Wolverine", ["WOLVERINE", "WOLVERINE"]),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company-id", default="")
    args = ap.parse_args()
    init_db()
    with db_session() as s:
        cid = args.company_id.strip()
        if not cid:
            co = s.query(Company).order_by(Company.created_at.asc()).first()
            if not co:
                print("No company in DB — register a user first.")
                return 1
            cid = co.id
        for name, aliases in FLEET:
            exists = s.query(Vessel).filter(
                Vessel.company_id == cid,
                Vessel.name == name,
            ).first()
            if exists:
                print(f"skip {name}")
                continue
            s.add(Vessel(company_id=cid, name=name, aliases=aliases))
            print(f"add {name}")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
