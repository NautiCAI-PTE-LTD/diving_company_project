# Test raw image upload on AWS-hosted UI

Use this after deploying `frontend/dist` to S3.

## Before you open the UI

1. **GCP VM running:** `sudo systemctl status nauticai-api` → active
2. **Health:** `curl http://YOUR_GCP_IP:8000/api/health` → `"ok":true,"db":"postgres"`
3. **Supabase:** network allows your GCP static IP (or allow all for testing)
4. **GCP firewall:** TCP **8000** open
5. **Fresh UI on S3:** `aws s3 sync dist/ s3://nauticai-ui-prasad/ --delete`

## Open the right URL

| URL type | Uploads |
| -------- | ------- |
| S3 website **HTTP** | Works with `http://GCP_IP:8000` API |
| CloudFront **HTTPS** | Often **blocked** until API has HTTPS |

Find HTTP website: S3 → bucket → **Properties** → **Static website hosting**.

Hard refresh: **Ctrl+F5**.

## Test steps (5 minutes)

1. **Register / Log in** on the S3 URL (not localhost).
2. **Settings** → **API connection** → confirm `http://YOUR_GCP_IP:8000` → **Test health + upload** → success toast.
3. **Upload Raw Data** → **Add Folder** or drop images → toast “Added N files”.
4. Click **Run AI on All**.
5. Browser **F12** → **Network** → filter `analyze`:
   - `POST https://...` or `http://YOUR_GCP_IP:8000/api/analyze`
   - Status **200** (slow first image is normal)
6. Rows should move from **pending** → **done** with region/species.

## If it fails

| Symptom | Fix |
| ------- | --- |
| Red banner HTTPS→HTTP | Use S3 HTTP website, or HTTPS on API |
| 401 on analyze | Log in again on same URL |
| Network Error, no response | Wrong API IP → Settings → API connection |
| 500 on analyze | `journalctl -u nauticai-api -f` on VM |
| Files added but never POST | Old S3 build — redeploy dist |

## Redeploy UI only

**CloudShell:**

```bash
cd ~/nauticai
git pull
export GCP_API_URL=http://YOUR_GCP_STATIC_IP:8000
export S3_BUCKET=nauticai-ui-prasad
bash deploy/aws/deploy-from-cloudshell.sh
```

**Windows (valid `aws configure`):**

```powershell
cd F:\Diving_company_project
.\deploy\aws\deploy-ui.ps1 -Bucket nauticai-ui-prasad -ApiUrl http://YOUR_GCP_STATIC_IP:8000
```
