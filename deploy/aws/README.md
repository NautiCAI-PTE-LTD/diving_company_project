# Deploy NautiCAI UI on AWS (S3)

Static React app on S3. **API + GPU inference stay on GCP** (`VITE_API_URL`).

Your bucket: **`nauticai-ui-prasad`**

---

## Prerequisites

| Item | Check |
| ---- | ----- |
| GCP API | `curl http://YOUR_GCP_STATIC_IP:8000/api/health` → `"ok":true` |
| Supabase | Allows GCP VM IP (or allow all for testing) |
| GCP firewall | TCP **8000** ingress |
| AWS | CLI working (`aws sts get-caller-identity`) |

---

## Option A — AWS CloudShell (recommended if PC `aws configure` fails)

```bash
cd ~
git clone https://github.com/NautiCAI-PTE-LTD/Diving_company_project.git nauticai
# or: cd ~/nauticai && git pull

export GCP_API_URL=http://YOUR_GCP_STATIC_IP:8000
export S3_BUCKET=nauticai-ui-prasad

bash nauticai/deploy/aws/deploy-from-cloudshell.sh
```

Replace `YOUR_GCP_STATIC_IP` with the VM’s **static** external IP (GCP → VPC → IP addresses → `nauticai-api-ip`).

**Website URL:** S3 → `nauticai-ui-prasad` → **Properties** → **Static website hosting** → copy the **http://** endpoint.

Full upload test: [TEST-RAW-UPLOAD.md](./TEST-RAW-UPLOAD.md)

---

## Option B — Windows PC

```powershell
aws configure   # must succeed: aws sts get-caller-identity

cd F:\Diving_company_project
.\deploy\aws\deploy-ui.ps1 -Bucket nauticai-ui-prasad -ApiUrl http://YOUR_GCP_STATIC_IP:8000
```

Optional CloudFront cache clear:

```powershell
.\deploy\aws\deploy-ui.ps1 -Bucket nauticai-ui-prasad -ApiUrl http://YOUR_GCP_STATIC_IP:8000 -DistributionId EXXXXXXXXX
```

---

## S3 bucket setup (one-time)

| Setting | Value |
| ------- | ----- |
| Name | `nauticai-ui-prasad` |
| Region | e.g. `ap-southeast-1` |
| Public access | Off block (for website hosting) |

**Static website hosting**

- Index: `index.html`
- Error: `index.html` (SPA routes)

**Bucket policy** (public read):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "PublicReadGetObject",
    "Effect": "Allow",
    "Principal": "*",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::nauticai-ui-prasad/*"
  }]
}
```

Sync must upload **`dist/` contents to bucket root**:

```text
s3://nauticai-ui-prasad/index.html
s3://nauticai-ui-prasad/assets/...
```

Not `s3://nauticai-ui-prasad/dist/index.html` — remove stray prefix:

```bash
aws s3 rm s3://nauticai-ui-prasad/dist/ --recursive
```

---

## Important: HTTP vs HTTPS

| UI URL | API `http://IP:8000` |
| ------ | -------------------- |
| S3 website **HTTP** | Uploads work |
| CloudFront **HTTPS** | Browser may **block** uploads (mixed content) |

Use **S3 HTTP website** for raw-upload testing until the GCP API has HTTPS.

The UI also shows a red banner if HTTPS UI + HTTP API is detected.

**Without rebuild:** **Settings → API connection** can change the API URL in the browser (e.g. after VM IP change).

---

## What this deploy includes (upload fixes)

- FormData uploads without broken `Content-Type` (multipart boundary)
- Folder picker toasts when empty / success
- **Settings → Test health + upload** (`POST /api/diagnostics/upload-echo`)
- API URL override in Settings for IP changes

Ensure GCP VM has latest backend (`git pull` + `sudo systemctl restart nauticai-api`) for the upload-echo test endpoint.

---

## Troubleshooting

See [TEST-RAW-UPLOAD.md](./TEST-RAW-UPLOAD.md).

| Issue | Fix |
| ----- | --- |
| `InvalidAccessKeyId` on PC | Use **CloudShell** (Option A) or new IAM keys for `nauticai-deploy` |
| Works on `npm run dev`, not S3 | Redeploy dist; log in on S3 URL; use HTTP website |
| VM IP changed | Reserve **static IP** in GCP; update `GCP_API_URL` and redeploy |

---

## Config template

Copy [aws-deploy.env.example](./aws-deploy.env.example) → `aws-deploy.env` (local only, not committed).

---

## Quick reference

| Item | Value |
| ---- | ----- |
| S3 bucket | `nauticai-ui-prasad` |
| Build env | `frontend/.env.production` |
| API | `http://YOUR_GCP_STATIC_IP:8000` |
| CloudShell deploy | `deploy/aws/deploy-from-cloudshell.sh` |
| Windows deploy | `deploy/aws/deploy-ui.ps1` |
