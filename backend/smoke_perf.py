"""Quick perf check: how long do the 3 models + OCR take on this box?

Runs cold (first call = lazy load) and warm (steady state) for a single
1280x720 underwater photo, then reports per-model wall-clock so we can
verify the auto-GPU + ThreadPool changes.

Usage:
    cd backend
    python smoke_perf.py
"""
from __future__ import annotations
import sys, time
from pathlib import Path

# Make `python smoke_perf.py` work from the backend folder
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

# Configure stdout for unicode on Windows.
try: sys.stdout.reconfigure(encoding="utf-8")          # type: ignore[attr-defined]
except Exception: pass

from backend import config                              # noqa: E402
from backend.inference import region, before_after, species, ocr  # noqa: E402
from backend.inference import _runtime as inf_runtime   # noqa: E402
from backend.services.analyze import _serial_inference  # noqa: E402

print(f"== device={config.DEVICE}  backend={inf_runtime._FORCE}  ocr_gpu={config.OCR_GPU} ==")
for ckpt in (config.SHIP_REGION_CKPT, config.BEFORE_AFTER_CKPT, config.SPECIES_CKPT):
    ch = inf_runtime.resolve(ckpt)
    print(f"   {ckpt.name:40s} -> {ch.backend} ({ch.reason})")
try:
    import torch
    if torch.cuda.is_available():
        print("   GPU:", torch.cuda.get_device_name(0))
except Exception:
    pass

img = Image.new("RGB", (1280, 720), (40, 70, 110))
# Throw a small pattern in to give models something to think about
import random
px = img.load()
random.seed(0)
for _ in range(2000):
    x = random.randint(0, 1279); y = random.randint(0, 719)
    px[x, y] = (random.randint(180, 255), random.randint(150, 220), 90)

def _bench(label, fn, runs=3):
    t0 = time.perf_counter(); fn(); cold = time.perf_counter() - t0
    warm_runs = []
    for _ in range(runs):
        t = time.perf_counter(); fn(); warm_runs.append(time.perf_counter() - t)
    warm = sum(warm_runs) / len(warm_runs)
    print(f"  {label:18s}  cold={cold*1000:7.1f} ms   warm={warm*1000:7.1f} ms")
    return cold, warm

print("\nPer-model wall-clock:")
_bench("region",        lambda: region.predict(img))
_bench("before_after",  lambda: before_after.predict(img))
_bench("species",       lambda: species.predict(img))

# Combined sequential vs parallel
from concurrent.futures import ThreadPoolExecutor
pool = ThreadPoolExecutor(max_workers=3)

def run_three(_img=img):
    region.predict(_img); before_after.predict(_img); species.predict(_img)

def run_three_parallel(_img=img):
    f1 = pool.submit(region.predict, _img)
    f2 = pool.submit(before_after.predict, _img)
    f3 = pool.submit(species.predict, _img)
    f1.result(); f2.result(); f3.result()

print("\nThree-model combo (one /api/analyze call):")
_bench("seq 3 models",  run_three, runs=3)
if _serial_inference():
    print("  (parallel skipped — TRT or dual native-PyTorch on CUDA)")
else:
    _bench("par 3 models",  run_three_parallel, runs=3)

# Real dive photos (BW Birch reference set)
_birch = sorted((Path(__file__).resolve().parent / "assets/birch_reference/extracted").glob("*.jpg"))
if _birch:
    n = min(20, len(_birch))
    sample = _birch[:n]
    print(f"\nBatch over {n} birch photos ({sample[0].name} …):")
    t0 = time.perf_counter()
    for p in sample:
        run_three(Image.open(p).convert("RGB"))
    ms = (time.perf_counter() - t0) / n * 1000
    print(f"  seq 3 models / image   avg={ms:7.1f} ms  ({1000/ms:.1f} img/s)")
    t0 = time.perf_counter()
    for p in sample:
        run_three_parallel(Image.open(p).convert("RGB"))
    ms = (time.perf_counter() - t0) / n * 1000
    print(f"  par 3 models / image   avg={ms:7.1f} ms  ({1000/ms:.1f} img/s)")

# OCR
import tempfile, os
tmp = Path(tempfile.gettempdir()) / "perf_ocr.jpg"
img2 = img.copy()
from PIL import ImageDraw, ImageFont
d = ImageDraw.Draw(img2)
try:
    font = ImageFont.truetype("arialbd.ttf", 96)
except Exception:
    font = ImageFont.load_default()
d.text((180, 280), "MV WOLVERINE", fill="white", font=font)
img2.save(tmp, "JPEG", quality=88)

print("\nOCR vessel-name (the slow one):")
_bench("ocr.extract", lambda: ocr.extract(img2), runs=2)

print("\nDone.")
