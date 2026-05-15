#!/usr/bin/env bash
# Build the React UI on Jetson / edge hosts. Uses npm install (not npm ci)
# because npm 10.8 on Ubuntu 20.04 often rejects lockfile nested picomatch entries.
set -euo pipefail
cd "$(dirname "$0")"

need_node=18
ver="$(node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1 || echo 0)"
if [ "${ver:-0}" -lt "$need_node" ]; then
  echo "Node $(node -v 2>/dev/null || echo missing) is too old; need >= ${need_node}."
  echo "Install Node 20: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -"
  echo "                 sudo apt install -y nodejs"
  exit 1
fi

rm -rf node_modules
if ! npm ci 2>/dev/null; then
  echo "npm ci failed — using npm install (normal on Jetson)."
  npm install
fi
npm run build
echo "Done → $(pwd)/dist"
