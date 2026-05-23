# NautiCAI backend — CPU image for Oracle Cloud (and generic Linux VMs).
# Mount Models/ and backend/storage/ as volumes in production.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    NAUTICAI_DEVICE=cpu \
    NAUTICAI_FP16=0

WORKDIR /app

# OpenCV, EasyOCR, Postgres client libs, healthcheck curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/requirements.txt

# CPU wheels keep the image smaller than default CUDA torch.
RUN pip install --no-cache-dir --upgrade pip wheel setuptools \
    && pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend/ /app/backend/

# Placeholder so the directory exists; real weights must be volume-mounted.
RUN mkdir -p /app/Models /app/backend/storage/uploads /app/backend/storage/reports

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -sf http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
