# Deploy NautiCAI backend on Oracle Cloud Infrastructure (OCI)

This guide deploys the **FastAPI backend** (inference, PDF reports, auth, storage) on an **OCI Compute** VM using **Docker**. The React frontend can be built on the same VM behind nginx, or hosted separately (Vercel, Object Storage static site, etc.).

---

## Architecture

```
Internet → OCI Security List (80/443/22)
         → Ubuntu VM
              nginx :80/:443  →  /api/*  →  Docker :8000 (uvicorn)
              optional static  →  frontend/dist
         → Block volume /opt/nauticai/data
              Models/          (PyTorch weights, ~172 MB)
              storage/         (uploads, reports, SQLite fallback)
         → Postgres (pick one)
              • Supabase / existing DATABASE_URL, or
              • OCI Autonomous PostgreSQL, or
              • `docker compose --profile local-db` (dev/small prod only)
```

**Recommended VM (CPU inference):** Ubuntu 22.04, **VM.Standard.E4.Flex** (2 OCPU, 16 GB RAM) or **VM.Standard.A1.Flex** (Ampere, 4 OCPU, 24 GB — cost-effective). ML runs on CPU in this image (`NAUTICAI_DEVICE=cpu`).

For GPU inference on OCI, use a GPU shape (e.g. VM.GPU.A10.1), install the NVIDIA driver, and set `NAUTICAI_DEVICE=cuda` — not covered in the default Dockerfile (CPU wheels).

---

## 1. OCI console checklist

Create these in your **tenancy / compartment** (or use an existing VCN):

| Resource | Notes |
| -------- | ----- |
| **VCN** | e.g. `10.0.0.0/16` with Internet Gateway |
| **Public subnet** | Route `0.0.0.0/0` → Internet Gateway |
| **Security list ingress** | TCP **22** (SSH, your IP), **80**, **443** (world or load balancer) |
| **Compute instance** | Ubuntu 22.04/24.04, public IP, SSH key |
| **Block volume** (optional) | 50 GB+, attach and mount at `/opt/nauticai` |

**Boot volume** alone works for trials; use a **block volume** so uploads/reports survive instance replacement.

---

## 2. Attach and mount block storage (recommended)

On the VM after first SSH:

```bash
# List block device (often /dev/sdb on OCI)
lsblk

sudo mkfs.ext4 /dev/sdb    # only once, if new volume
sudo mkdir -p /opt/nauticai
echo '/dev/sdb /opt/nauticai ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
sudo mount -a
sudo chown -R "$USER:$USER" /opt/nauticai
```

---

## 3. Bootstrap the VM

```bash
ssh ubuntu@<PUBLIC_IP>

git clone https://github.com/NautiCAI-PTE-LTD/diving_company_project.git /opt/nauticai/app
cd /opt/nauticai/app
chmod +x deploy/oracle-cloud/bootstrap.sh
./deploy/oracle-cloud/bootstrap.sh
```

Log out and back in if Docker was just installed (`docker` group).

---

## 4. Upload model weights

Weights are **not** in git. From your Windows laptop:

```powershell
cd F:\Diving_company_project
.\deploy\oracle-cloud\upload-from-windows.ps1 -Host <PUBLIC_IP> -User ubuntu -KeyPath C:\path\to\ssh-key.pem
```

Or manually:

```bash
scp Models/*.pth Models/*.keras Models/*.pt ubuntu@<IP>:/opt/nauticai/data/Models/
```

---

## 5. Configure environment

```bash
cd /opt/nauticai/app
cp deploy/oracle-cloud/env.production.example .env
chmod 600 .env
nano .env
```

Set at minimum:

- `DATABASE_URL` — Supabase or OCI Autonomous Postgres connection string (`?sslmode=require`)
- `JWT_SECRET` — long random string:
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(64))"
  ```
- `DATA_DIR=/opt/nauticai/data`

Optional PDF annex (BW BIRCH reference photos):

```bash
# After uploading the PDF to /opt/nauticai/data/Final_Report_BW_BIRCH.pdf
echo 'REFERENCE_PDF=/opt/nauticai/data/Final_Report_BW_BIRCH.pdf' >> .env
```

---

## 6. Build and run

```bash
cd /opt/nauticai/app
docker compose build
docker compose up -d
docker compose logs -f api
```

With reference PDF mount:

```bash
docker compose -f docker-compose.yml -f docker-compose.oci.yml up -d --build
```

Verify:

```bash
curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool
curl -s http://127.0.0.1:8000/api/system | python3 -m json.tool
```

First inference request loads models (1–3 minutes on CPU). `warmup` in `/api/system` becomes `ready` when finished.

---

## 7. nginx reverse proxy + HTTPS

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
sudo cp /opt/nauticai/app/deploy/oracle-cloud/nginx-nauticai.conf /etc/nginx/sites-available/nauticai
sudo nano /etc/nginx/sites-available/nauticai   # set server_name to your domain
sudo ln -sf /etc/nginx/sites-available/nauticai /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d your.domain.com
```

Point your DNS **A record** to the instance public IP.

---

## 8. Frontend (optional, same VM)

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
cd /opt/nauticai/app/frontend
npm ci && npm run build
```

nginx `root` in `nginx-nauticai.conf` already points to `frontend/dist`. Set the production API URL in the UI if you host the frontend elsewhere (env / build-time `VITE_API_URL` if you add it).

---

## 9. OCI Autonomous PostgreSQL (optional)

1. OCI Console → **Oracle Database** → **Autonomous Database** → Create **PostgreSQL**.
2. Download wallet or copy connection string; allow the compute **subnet CIDR** in DB access rules.
3. Set `DATABASE_URL` in `.env`, restart:

   ```bash
   docker compose up -d --force-recreate api
   ```

Tables are created on first boot via SQLAlchemy `init_db()`.

---

## 10. Operations

| Task | Command |
| ---- | ------- |
| Update code | `cd /opt/nauticai/app && git pull && docker compose build && docker compose up -d` |
| Logs | `docker compose logs -f api` |
| Restart | `docker compose restart api` |
| Disk usage | `du -sh /opt/nauticai/data/storage` |
| Backup DB | `pg_dump` (managed DB) or snapshot block volume |

**Firewall on instance:** Ubuntu images on OCI usually rely on the **security list**; ensure ingress 8000 is **not** public if nginx terminates TLS on 443 only (bind API to localhost via compose — default publishes 8000 on all interfaces; restrict in security list to SSH + 80/443 only).

To bind API to localhost only, change `ports` in `docker-compose.yml` to:

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

---

## 11. Environment reference

| Variable | Production suggestion |
| -------- | --------------------- |
| `DATABASE_URL` | Managed Postgres (Supabase / OCI Autonomous) |
| `JWT_SECRET` | Required, 32+ random bytes |
| `NAUTICAI_DEVICE` | `cpu` on standard VM |
| `NAUTICAI_FP16` | `0` on CPU |
| `NAUTICAI_REPORT_TEMPLATE` | `marine` |
| `NAUTICAI_SOURCE_PDF` | Path inside container if using `docker-compose.oci.yml` |
| `DATA_DIR` | `/opt/nauticai/data` |

See also `backend/.env.example`.

---

## Troubleshooting

| Symptom | Fix |
| ------- | --- |
| `warmup: failed` | Check `docker compose logs api`; confirm three files under `DATA_DIR/Models/` |
| 502 from nginx | `curl localhost:8000/api/health`; restart `docker compose up -d` |
| Out of memory | Use 16 GB+ RAM shape; keep `NAUTICAI_ANALYZE_CONCURRENCY=1` |
| Slow PDF / analyze | Expected on CPU; consider larger shape or GPU instance |
| DB SSL errors | Add `?sslmode=require` to `DATABASE_URL` |

---

## Related

- Edge GPU (Jetson): [`deploy/jetson/README.md`](../jetson/README.md)
- Models download: [`Models/README.md`](../../Models/README.md)
