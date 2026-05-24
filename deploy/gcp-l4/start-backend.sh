#!/usr/bin/env bash
# Start NautiCAI API on the GCP L4 VM (same Supabase DB as local dev).
# Run on the VM:  bash /opt/nauticai/app/deploy/gcp-l4/start-backend.sh
set -euo pipefail

APP="${NAUTICAI_APP:-/opt/nauticai/app}"
ENV_FILE="$APP/backend/.env"

echo "==> App: $APP"
cd "$APP"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: missing $ENV_FILE"
  echo "Copy deploy/gcp-l4/env.production.example and set DATABASE_URL + JWT_SECRET"
  exit 1
fi

# Same pooler as local PC (port 6543, not direct 5432)
if grep -q ':5432/' "$ENV_FILE" && ! grep -q 'pooler' "$ENV_FILE"; then
  echo "WARN: DATABASE_URL uses :5432 direct — prefer Supabase pooler :6543 (see local backend/.env)"
fi

if [[ -L Models ]] || [[ -d Models ]]; then
  echo "==> Models: $(readlink -f Models 2>/dev/null || echo Models)"
else
  echo "WARN: Models symlink missing — ln -sfn /opt/nauticai/Models Models"
fi

nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo "WARN: nvidia-smi failed"

# systemd user may be prasad on your VM
UNIT=/etc/systemd/system/nauticai-api.service
if [[ -f "$UNIT" ]] && grep -q '^User=ubuntu' "$UNIT" 2>/dev/null; then
  if id prasad &>/dev/null; then
    echo "TIP: if service fails, run: sudo sed -i 's/User=ubuntu/User=prasad/;s/Group=ubuntu/Group=prasad/' $UNIT && sudo systemctl daemon-reload"
  fi
fi

sudo systemctl daemon-reload
sudo systemctl enable nauticai-api
sudo systemctl restart nauticai-api

echo "==> Waiting for startup (up to 120s)..."
for i in $(seq 1 24); do
  if curl -sf http://127.0.0.1:8000/api/health >/tmp/nauticai-health.json 2>/dev/null; then
    cat /tmp/nauticai-health.json
    echo ""
    echo "==> External IP (use in S3 VITE_API_URL): $(curl -sf ifconfig.me || true)"
    echo "OK — test from PC: curl http://\$(curl -sf ifconfig.me):8000/api/health"
    exit 0
  fi
  sleep 5
done

echo "ERROR: health check failed"
sudo systemctl status nauticai-api --no-pager || true
journalctl -u nauticai-api -n 40 --no-pager
exit 1
