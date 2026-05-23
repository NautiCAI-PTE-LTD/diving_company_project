#!/usr/bin/env bash
# Bootstrap an Ubuntu 22.04/24.04 OCI Compute VM for NautiCAI backend (Docker).
#
# Run on the VM as a user with sudo:
#   chmod +x deploy/oracle-cloud/bootstrap.sh
#   ./deploy/oracle-cloud/bootstrap.sh
#
# Optional env:
#   REPO_URL=https://github.com/NautiCAI-PTE-LTD/diving_company_project.git
#   INSTALL_DIR=/opt/nauticai/app
#   DATA_DIR=/opt/nauticai/data
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/NautiCAI-PTE-LTD/diving_company_project.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/nauticai/app}"
DATA_DIR="${DATA_DIR:-/opt/nauticai/data}"
BRANCH="${BRANCH:-main}"

echo "══════════════════════════════════════════════════════════════"
echo " NautiCAI · Oracle Cloud bootstrap"
echo " Install: $INSTALL_DIR"
echo " Data:    $DATA_DIR"
echo "══════════════════════════════════════════════════════════════"

sudo apt-get update
sudo apt-get install -y \
    ca-certificates curl git gnupg \
    libgl1 libglib2.0-0

# Docker Engine + Compose plugin
if ! command -v docker >/dev/null; then
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo usermod -aG docker "$USER" || true
    echo "[!] Log out and back in (or newgrp docker) so you can run docker without sudo."
fi

sudo mkdir -p "$INSTALL_DIR" "$DATA_DIR/Models" "$DATA_DIR/storage/uploads" "$DATA_DIR/storage/reports"
sudo chown -R "$USER:$USER" /opt/nauticai

if [[ ! -d "$INSTALL_DIR/.git" ]]; then
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
else
    git -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH"
    git -C "$INSTALL_DIR" checkout "$BRANCH"
    git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH" || true
fi

cd "$INSTALL_DIR"

if [[ ! -f .env ]]; then
    cp deploy/oracle-cloud/env.production.example .env
    echo ""
    echo "[!] Edit $INSTALL_DIR/.env — set DATABASE_URL, JWT_SECRET, paths."
    echo "    Then: docker compose build && docker compose up -d"
fi

# Symlink-friendly .env values
if ! grep -q "^DATA_DIR=" .env 2>/dev/null; then
    echo "DATA_DIR=$DATA_DIR" >> .env
fi

cat <<EOF

────────────────────────────────────────────────────────────────
 Next steps on this VM:

 1. Copy model weights into:
      $DATA_DIR/Models/
    (Ship_classification_v2.pth, Before_and_after_v2.keras, species_classifier_bundle.pt)

 2. Edit secrets:
      nano $INSTALL_DIR/.env

 3. Build and start:
      cd $INSTALL_DIR
      docker compose build
      docker compose up -d
      docker compose logs -f api

 4. Health check:
      curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool

 5. (Optional) nginx + TLS — see deploy/oracle-cloud/README.md
────────────────────────────────────────────────────────────────
EOF
