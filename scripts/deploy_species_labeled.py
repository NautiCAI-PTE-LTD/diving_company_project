"""Deploy species_classifier_labeled_v1.pt to production Models/ + ONNX export."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(r"D:\test species model\marine_report\models\species_classifier_labeled_v1.pt")
DST = ROOT / "Models" / "species_classifier_bundle.pt"


def main() -> int:
    if not SRC.is_file():
        print(f"Missing trained weights: {SRC}")
        print("Wait for training to finish (Saved checkpoint in train_labeled_v1_resume.log).")
        return 1

    DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC, DST)
    meta_src = SRC.with_suffix(".json")
    if meta_src.is_file():
        shutil.copy2(meta_src, DST.with_suffix(".json"))

    ckpt = __import__("torch").load(str(DST), map_location="cpu", weights_only=False)
    names = ckpt["meta"]["class_names"]
    print("Deployed", DST)
    print("Classes:", names)

    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_onnx.py"), "--only", "species"],
        cwd=str(ROOT),
    )
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
