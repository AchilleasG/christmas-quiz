#!/usr/bin/env bash
set -euo pipefail

# Deployment helper: pulls latest main and restarts via Docker Compose.
# Run from repo root. Requires sudo for docker access.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$REPO_DIR"

echo "[deploy] Updating repository..."
git fetch origin main
git checkout main
git pull origin main

echo "[deploy] Building containers..."
sudo docker-compose build

echo "[deploy] Stopping containers..."
sudo docker-compose down

echo "[deploy] Starting containers..."
sudo docker-compose up -d

echo "[deploy] Deployment complete."
