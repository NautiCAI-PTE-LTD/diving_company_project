#!/usr/bin/env bash
# Build NautiCAI UI and sync to S3 — run in AWS CloudShell (credentials already work).
#
#   export GCP_API_URL=http://YOUR_STATIC_IP:8000
#   export S3_BUCKET=nauticai-ui-prasad
#   bash deploy/aws/deploy-from-cloudshell.sh
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FRONTEND="$REPO_ROOT/frontend"
BUCKET="${S3_BUCKET:-nauticai-ui-prasad}"
API_URL="${GCP_API_URL:-}"

if [[ -z "$API_URL" ]]; then
  echo "ERROR: set GCP_API_URL, e.g. export GCP_API_URL=http://34.x.x.x:8000"
  exit 1
fi

API_URL="${API_URL%/}"

echo "==> API: $API_URL"
echo "==> S3:  s3://$BUCKET/"

if [[ ! -d "$FRONTEND/node_modules" ]]; then
  (cd "$FRONTEND" && npm install)
fi

cat > "$FRONTEND/.env.production" << EOF
VITE_API_URL=$API_URL
VITE_USE_MOCK=false
EOF

# Baked into bundle + loadable without rebuild if you only change this file on S3
cat > "$FRONTEND/public/runtime-config.js" << EOF
window.__NAUTICAI_API_URL__ = '$API_URL'
EOF

(cd "$FRONTEND" && npm run build)

if ! grep -rq "${API_URL#http://}" "$FRONTEND/dist/assets/" 2>/dev/null; then
  echo "WARN: API URL may not be in JS bundle — runtime-config.js will still point the UI at $API_URL"
fi

# Sync dist/ contents to bucket root (not dist/ as a prefix)
aws s3 sync "$FRONTEND/dist/" "s3://$BUCKET/" --delete

echo ""
echo "Done. Open your S3 **HTTP** website URL (not CloudFront HTTPS unless API is HTTPS)."
echo "Test: log in -> Settings -> Test health + upload -> Upload Raw Data -> Run AI on All"

if [[ -n "${CLOUDFRONT_DISTRIBUTION_ID:-}" ]]; then
  aws cloudfront create-invalidation \
    --distribution-id "$CLOUDFRONT_DISTRIBUTION_ID" --paths "/*"
  echo "CloudFront invalidation sent."
fi
