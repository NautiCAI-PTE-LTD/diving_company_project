# Deploying NautiCAI on NVIDIA Jetson Orin Nano

End-to-end recipe for getting the FastAPI backend + React frontend running
on a Jetson Orin Nano with TensorRT FP16 inference. Tested against
**JetPack 6.0 / L4T 36.3 (CUDA 12.2, cuDNN 8.9, TensorRT 8.6)**.

> All commands assume you're SSH'd or TeamViewer'd into the Jetson, and that
> you have `sudo`. Replace `~/diving_company_project` with wherever you
> cloned the repo if different.

---

## 0. One-time host checks

```bash
# Verify JetPack components
dpkg -l | grep -E "nvidia-l4t-core|nvidia-jetpack|tensorrt|cuda-toolkit"
nvidia-smi || sudo /usr/bin/jetson_clocks --show   # nvidia-smi isn't shipped on Orin Nano

# Max out the clocks for benchmark runs
sudo nvpmodel -m 0          # MAXN profile
sudo jetson_clocks
```

If `jetson_clocks` isn't available you're on an older L4T — upgrade JetPack
before proceeding. Lower power modes (15 W) are fine for production but will
roughly halve inference throughput.

---

## 1. Clone the repo and install Python deps

```bash
cd ~
git clone https://github.com/NautiCAI-PTE-LTD/diving_company_project.git
cd diving_company_project

# System packages required by opencv / pillow / psycopg2
sudo apt update
sudo apt install -y python3-pip python3-venv python3-dev \
                    libopenblas-dev libomp-dev \
                    libjpeg-dev libpng-dev libtiff-dev \
                    libpq-dev

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel setuptools
```

### 1a. Install the NVIDIA-built PyTorch wheel

PyPI's `torch` does **not** include CUDA support for aarch64. Pull the
matching aarch64+CUDA wheel from NVIDIA's index. Check the latest URL at:
<https://developer.download.nvidia.com/compute/redist/jp/v60/pytorch/>.

```bash
# Example for PyTorch 2.3 on JetPack 6.0 — adjust filename for your JP version
wget https://developer.download.nvidia.com/compute/redist/jp/v60/pytorch/torch-2.3.0-cp310-cp310-linux_aarch64.whl
pip install torch-2.3.0-cp310-cp310-linux_aarch64.whl

# Build torchvision from source against the installed torch
pip install --no-build-isolation \
    "torchvision @ git+https://github.com/pytorch/vision.git@v0.18.0"
```

Sanity check:

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
# → 2.3.0 True
```

### 1b. Install the rest of the project requirements

```bash
pip install -r backend/requirements-jetson.txt
# easyocr's wheel re-pins torch on PyPI; install it without its deps after torch is set.
pip install --no-deps easyocr
```

---

## 2. Drop in the model weights

The repo ships **without** the `.pth/.keras/.pt` weights — they live on
Google Drive. Download `Models_for_Jetson.zip` from the shared folder and
unzip into the repo:

```bash
cd ~/diving_company_project
unzip ~/Downloads/Models_for_Jetson.zip -d Models/
ls Models/
#   Ship_classification_v2.pth
#   Before_and_after_v2.keras
#   species_classifier_bundle.pt
```

---

## 3. Convert models to TensorRT FP16

You need ONNX files first (produced on the dev workstation with TensorFlow
installed) **OR** you can produce them on the Jetson too — but TensorFlow on
aarch64 is painful, so the recommended flow is:

| Step                                | Where                       |
| ----------------------------------- | --------------------------- |
| `python scripts/export_onnx.py`     | Dev workstation (Windows)   |
| Copy the `*.onnx` files onto Jetson | scp / TeamViewer file xfer  |
| `python scripts/build_trt.py --fp16`| Jetson                      |

### 3a. On the dev workstation

```bash
# In the project root with the original .venv that has tensorflow installed
pip install tf2onnx onnx
python scripts/export_onnx.py
# → produces Models/Ship_classification_v2.onnx, Models/species_classifier_bundle.onnx,
#   Models/Before_and_after_v2.onnx
```

Add the three `.onnx` files into `Models_for_Jetson.zip` (or just transfer
them separately to the Jetson under `~/diving_company_project/Models/`).

### 3b. On the Jetson

```bash
cd ~/diving_company_project
source .venv/bin/activate
python scripts/build_trt.py --fp16
# → produces Models/*.engine — a 1-5 minute one-off cost per model.
```

Verify the engines exist:

```bash
ls Models/*.engine
#   Models/Ship_classification_v2.engine
#   Models/species_classifier_bundle.engine
#   Models/Before_and_after_v2.engine
```

---

## 4. Configure environment

```bash
cat > backend/.env <<'EOF'
DATABASE_URL=postgresql://postgres:<password>@<host>:5432/postgres?sslmode=require
JWT_SECRET=<replace-with-a-long-random-string>
JWT_ALG=HS256
JWT_EXPIRE_MIN=10080

# Optional — force a specific inference backend (default: auto)
# NAUTICAI_BACKEND=trt
NAUTICAI_FP16=1
EOF
chmod 600 backend/.env
```

---

## 5. Smoke test the backend

```bash
cd ~/diving_company_project
source .venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000

# In another terminal:
curl http://localhost:8000/api/system | python -m json.tool
```

Look for:

```json
{
  "device": "cuda",
  "warmup": "ready",
  "model_backends": {
    "region":       {"backend": "trt", "artefact": ".../Ship_classification_v2.engine"},
    "species":      {"backend": "trt", "artefact": ".../species_classifier_bundle.engine"},
    "before_after": {"backend": "trt", "artefact": ".../Before_and_after_v2.engine"}
  }
}
```

If any backend says `"native"`, the engine file is missing — re-run step 3b.

---

## 6. Build and serve the frontend

```bash
cd frontend
# Install Node 20 if it isn't already there
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

npm ci
npm run build        # produces frontend/dist
```

Serve it however you prefer. The lightest option is to let nginx (already
shipped with JetPack) handle static files and proxy `/api` to uvicorn:

```nginx
# /etc/nginx/sites-available/nauticai
server {
    listen 80;
    server_name _;

    root /home/<user>/diving_company_project/frontend/dist;
    index index.html;

    location / {
        try_files $uri /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_read_timeout 600s;        # PDF generation can take a while
        client_max_body_size 100M;      # large image uploads
    }
}
```

```bash
sudo ln -sf /etc/nginx/sites-available/nauticai /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 7. Run as a service (so it survives reboots)

```bash
sudo tee /etc/systemd/system/nauticai.service > /dev/null <<EOF
[Unit]
Description=NautiCAI backend
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/diving_company_project
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/$USER/diving_company_project/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now nauticai
sudo systemctl status nauticai
```

---

## 8. Expected performance on Orin Nano (8 GB, MAXN, FP16)

These are ballpark figures from similar EffNet-B0 / Swin-T workloads:

| Model              | PyTorch FP16 | TensorRT FP16 | Speed-up |
| ------------------ | ------------ | ------------- | -------- |
| Region (Swin-T)    | ~110 ms/img  | ~25 ms/img    | ~4.4×    |
| Species (EffNet-B0)| ~28 ms/img   | ~6 ms/img     | ~4.7×    |
| Before/After       | ~30 ms/img   | ~7 ms/img     | ~4.3×    |

End-to-end per image (preprocess + region + species + before_after): roughly
**40-50 ms with TensorRT** vs **~170 ms with native PyTorch**. EasyOCR adds
~120-200 ms when an image is flagged as a vessel-overview; that path stays
on PyTorch (the CRAFT detector isn't TRT-friendly out of the box).

If you push 1000+ images, expect ~1 min sustained throughput on the
backend, plus the network upload time from India → Singapore (the
frontend's 4-way concurrency cap and 10-minute axios timeout already
account for the queue).

---

## 9. Troubleshooting

- **`OSError: libnvinfer.so.X not found`** — TensorRT isn't on the loader
  path. Add `export LD_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu:$LD_LIBRARY_PATH`
  to the systemd unit's `Environment=`.
- **`/api/system` shows `"backend": "native"`** — engine file missing or
  TensorRT import failed. Run `python -c "import tensorrt; print(tensorrt.__version__)"`.
- **OOM on the species model** — drop the workspace pool: `python
  scripts/build_trt.py --workspace-mb 512`.
- **EasyOCR slow on the first inference** — that's the one-off model
  download (CRAFT + CRNN, ~80 MB) on the first run. Subsequent calls are
  fast.
